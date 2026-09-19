"""Producer metadata for isolated CLI snapshots; never infer a real WeChat ID."""
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

POINTER = 'vchat-snapshot.json'
MANAGED = 'vchat-snapshot-managed.json'
MANAGED_VALUE = {'version': 1, 'mode': 'isolated-snapshots-no-legacy-fallback'}
MAX_FILES = 2048
ROOT_ENV = 'VCHAT_SNAPSHOT_ROOT'
DEFAULT_ROOT = Path.home() / '.vchat' / 'snapshots'


def snapshot_root(value=None):
    raw = value if value is not None else os.environ.get(ROOT_ENV) or DEFAULT_ROOT
    path = Path(os.path.expanduser(str(raw)))
    if not path.is_absolute():
        raise RuntimeError('snapshot root must be an absolute path')
    for node in [path, *path.parents]:
        if node.is_symlink():
            raise RuntimeError('snapshot root cannot contain symlinks')
    return path


def fingerprint(path):
    value = Path(path).lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise RuntimeError('snapshot source/output is not an ordinary unlinked file')
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def safe_child(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise RuntimeError('invalid snapshot child')
    here = root
    for part in rel.parts:
        here = here / part
        if here.is_symlink():
            raise RuntimeError('snapshot child cannot be a symlink')
    return here


@contextlib.contextmanager
def refresh_lock(data_dir):
    # POSIX flock; isolated snapshot mode targets macOS / Linux installs.
    try:
        import fcntl
    except ImportError:
        raise RuntimeError('隔离快照模式目前仅支持 macOS / Linux') from None
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root/'vchat-refresh.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise RuntimeError('invalid snapshot refresh lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一次 vchat 刷新正在进行，请稍后重试') from None
        yield
    finally:
        os.close(fd)


def begin(data_dir, configured_root=None):
    top = snapshot_root(configured_root)
    top.mkdir(mode=0o700, parents=True, exist_ok=True)
    ident = uuid.uuid4().hex
    generation = top / ident
    generation.mkdir(mode=0o700)
    output = generation / 'decrypted'
    output.mkdir(mode=0o700)
    return output


def _write_new(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _read_metadata(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 2*1024*1024 or before.st_nlink != 1:
            raise RuntimeError('invalid snapshot metadata file')
        with os.fdopen(fd, 'r', closefd=False) as stream:
            value = json.load(stream)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeError('snapshot metadata changed while reading')
    finally:
        os.close(fd)
    if not isinstance(value, dict):
        raise RuntimeError('invalid snapshot metadata value')
    return value


def _mark_managed(control):
    marker = safe_child(control, MANAGED)
    try:
        _write_new(marker, MANAGED_VALUE)
    except FileExistsError:
        if _read_metadata(marker) != MANAGED_VALUE:
            raise RuntimeError('invalid managed snapshot marker') from None


def publish(data_dir, output, summary):
    """Publish only one newly generated successful subset, never overlay old DBs."""
    output = Path(output)
    root = output.resolve().parent.parent
    control = Path(data_dir).resolve()
    relative = output.relative_to(root)
    if len(relative.parts) != 2 or relative.parts[1] != 'decrypted' or not re.fullmatch(r'[a-f0-9]{32}', relative.parts[0]):
        raise RuntimeError('snapshot output must be a new exclusive generation')
    safe_child(root, str(relative))
    generation = output.parent
    if (generation/'receipt.json').exists():
        raise RuntimeError('snapshot already published')
    results = summary.get('results')
    before = summary.get('source_fingerprints')
    if not isinstance(results, dict) or not isinstance(before, dict) or len(before) > MAX_FILES or not before:
        raise RuntimeError('invalid or oversized snapshot source manifest')
    storage = Path(summary['db_storage'])
    if not storage.is_absolute():
        raise RuntimeError('snapshot source namespace must be absolute')
    success, failures, missing = {}, {}, []
    for rel, original in before.items():
        if not isinstance(rel, str) or not rel.endswith('.db'):
            raise RuntimeError('invalid snapshot source member')
        target = safe_child(output, rel)
        source = safe_child(storage, rel)
        result = results.get(rel)
        valid = isinstance(result, dict) and result.get('ok') is True
        if valid:
            try:
                if fingerprint(source) != original:
                    raise RuntimeError('source changed during refresh')
                fingerprint(target)
                os.chmod(target, 0o600)
                # Durable signatures omit st_dev, which may change after a
                # host reboot; identity is inode + size + timestamps.
                success[rel] = fingerprint(target)[1:]
            except (OSError, RuntimeError):
                valid = False
        if not valid:
            if result is None:
                missing.append(rel)
            else:
                failures[rel] = 'decryption-or-stability-check-failed'
            # Failed products were created only inside this exclusive new
            # generation. They must never become readable as successful DBs.
            if target.exists():
                fingerprint(target)
                target.unlink()
    # No unlisted or partial output may be published. Do not inspect bytes.
    actual = set()
    for directory, dirs, names in os.walk(output, followlinks=False):
        for name in dirs:
            if (Path(directory)/name).is_symlink():
                raise RuntimeError('unexpected symlink in new snapshot')
        for name in names:
            p = Path(directory)/name
            fingerprint(p)
            actual.add(str(p.relative_to(output)))
            if len(actual) > MAX_FILES:
                raise RuntimeError('snapshot file bound exceeded')
    if actual != set(success):
        raise RuntimeError('snapshot contains unlisted outputs')
    ident = relative.parts[0]
    source_id = 'wechat-local-source:' + hashlib.sha256(str(storage.resolve()).encode()).hexdigest()
    coverage = {'source_databases': len(before), 'successful_databases': len(success),
                'failed': failures, 'missing_keys': missing,
                'local_source_complete': len(success) == len(before), 'upstream_sync_complete': False}
    value = {'version': 1, 'snapshot_id': ident, 'output_relative': str(relative), 'snapshot_root': str(root),
             'source_identity': {'id': source_id, 'kind': 'local-account-source',
                                 'verified': True, 'snapshot_id': ident,
                                 'scope': 'opaque-local-source-namespace-not-real-wxid'},
             'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
             'coverage': coverage, 'outputs': success, 'source_files': before}
    value['state'] = 'complete-local-copy' if coverage['local_source_complete'] else ('partial' if success else 'failed')
    receipt = generation/'receipt.json'
    _write_new(receipt, value)
    if not success:
        raise RuntimeError('本次刷新没有稳定成功的数据库，已记录失败，未发布新副本')
    # Verify manifest/outputs before changing the single active pointer.
    _validate(control, value)
    # Create the durable opt-in before the pointer. If publication is interrupted,
    # reads require explicit refresh instead of falling back to an unbound cache.
    _mark_managed(control)
    pointer = safe_child(control, POINTER)
    fd, temporary = tempfile.mkstemp(prefix='.vchat-pointer-', dir=control)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        if pointer.is_symlink():
            raise RuntimeError('active snapshot pointer cannot be a symlink')
        os.replace(temporary, pointer)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
    return value


def _validate(root, value):
    ident = value.get('snapshot_id')
    if value.get('version') != 1 or not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise RuntimeError('invalid active snapshot identity')
    root = snapshot_root(value.get('snapshot_root'))
    expected = ident + '/decrypted'
    if value.get('output_relative') != expected:
        raise RuntimeError('active snapshot path mismatch')
    receipt = _read_metadata(safe_child(root, ident + '/receipt.json'))
    if receipt != value:
        raise RuntimeError('active snapshot pointer and generation receipt differ')
    source = value.get('source_identity', {})
    if (source.get('snapshot_id') != ident or source.get('verified') is not True
            or source.get('kind') != 'local-account-source'
            or not re.fullmatch(r'wechat-local-source:[a-f0-9]{64}', source.get('id', ''))):
        raise RuntimeError('invalid source namespace')
    entries = value.get('outputs')
    if not isinstance(entries, dict) or not 1 <= len(entries) <= MAX_FILES:
        raise RuntimeError('invalid snapshot output manifest')
    output = safe_child(root, expected)
    for rel, saved in entries.items():
        if fingerprint(safe_child(output, rel))[1:] != saved:
            raise RuntimeError('active snapshot changed; refresh through vchat before reading')
    # Detect added DBs as well as changed registered ones, without opening data.
    actual = set()
    for directory, dirs, names in os.walk(output, followlinks=False):
        if any((Path(directory)/name).is_symlink() for name in dirs):
            raise RuntimeError('symlink in active snapshot')
        for name in names:
            actual.add(str((Path(directory)/name).relative_to(output)))
            if len(actual) > MAX_FILES:
                raise RuntimeError('active snapshot bound exceeded')
    if actual != set(entries):
        raise RuntimeError('active snapshot contains unregistered files')
    return output


def source_status(value, storage):
    """Metadata only, through CLI. Does not establish upstream/WAL completeness."""
    if storage is None:
        return {'current_source_id': None, 'source_check': 'unavailable'}
    storage = Path(storage)
    current_id = 'wechat-local-source:' + hashlib.sha256(str(storage.resolve()).encode()).hexdigest()
    if current_id != value['source_identity']['id']:
        return {'current_source_id': current_id, 'source_check': 'changed-source'}
    try:
        observed = {}
        for p in storage.rglob('*.db'):
            if len(observed) >= MAX_FILES:
                raise RuntimeError('source bound exceeded')
            observed[str(p.relative_to(storage))] = fingerprint(p)
        same = observed == value.get('source_files')
        return {'current_source_id': current_id, 'source_check': 'unchanged-db-metadata' if same else 'changed-db-metadata'}
    except (OSError, RuntimeError):
        return {'current_source_id': current_id, 'source_check': 'unavailable'}


def active(data_dir):
    root = Path(data_dir).resolve()
    path = safe_child(root, POINTER)
    try:
        value = _read_metadata(path)
    except FileNotFoundError:
        marker = safe_child(root, MANAGED)
        if marker.exists():
            raise RuntimeError('managed snapshot pointer missing; explicit refresh required, no legacy fallback') from None
        return None
    if _read_metadata(safe_child(root, MANAGED)) != MANAGED_VALUE:
        raise RuntimeError('invalid managed snapshot marker')
    _validate(root, value)
    return value
