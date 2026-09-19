"""Full local-message corpus transport; only the vchat CLI opens snapshot DBs.

Keyset cursors bind one verified immutable generation. No UI limit is a corpus
limit. Counts are physical source rows; server IDs offer an additional dedup key.
"""
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from . import snapshot

VERSION = 1
SHARD = re.compile(r'^message/message_([0-9]+)\.db$')
TABLE = re.compile(r'^Msg_[0-9a-fA-F]{32}$')
PAGE_BYTES = 4 * 1024 * 1024
MAX_ITEM_BYTES = 16 * 1024 * 1024
MAX_PAGE_ROWS = 1000
CACHE = 'corpus-inventory-v1.json'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _timestamp(value):
    if type(value) not in (int, float):
        return None
    try:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat(timespec='seconds')
    except (ValueError, OverflowError, OSError):
        return None


def _window(since=None, until=None):
    """Timezone-explicit, half-open creation-time range; full scan is None."""
    if since is None and until is None: return None
    value = {}
    for key, raw in (('since', since), ('until', until)):
        if raw is None: value[key] = None; continue
        try:
            if not isinstance(raw, str) or len(raw) > 100: raise ValueError()
            moment = dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if moment.tzinfo is None: raise ValueError()
            value[key] = moment.astimezone(dt.timezone.utc).isoformat()
        except (ValueError, OverflowError):
            raise RuntimeError('微信时间窗口必须是含时区的 ISO 8601 时间') from None
    if value['since'] is not None and value['until'] is not None and dt.datetime.fromisoformat(value['since']) >= dt.datetime.fromisoformat(value['until']):
        raise RuntimeError('微信时间窗口起点必须早于终点')
    return value


def _time_sql(window):
    if window is None: return [], []
    clauses = ["typeof(create_time) IN ('integer','real')"]
    params = []
    for key, operator in (('since', '>='), ('until', '<')):
        if window[key] is not None:
            clauses.append('create_time ' + operator + ' ?')
            params.append(dt.datetime.fromisoformat(window[key]).timestamp())
    return clauses, params


def _progress(deadline):
    return 1 if time.monotonic() >= deadline else 0


@contextlib.contextmanager
def _connection(root, rel, deadline):
    path = snapshot.safe_child(root, rel)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.set_progress_handler(lambda: _progress(deadline), 5000)
    try:
        yield conn
    finally:
        conn.close()


def _binding(data_dir):
    value = snapshot.active(data_dir)
    if value is None:
        raise RuntimeError('需要先通过 vchat decrypt --snapshot-root 建立来源绑定快照')
    return value, Path(value['snapshot_root']) / value['output_relative']


def _check_same(data_dir, before):
    after, _ = _binding(data_dir)
    if after != before:
        raise RuntimeError('微信快照在读取期间改变，请从新快照重新开始；不能续用旧游标')


def _inventory(root, binding, deadline):
    """Metadata-only cache avoids rescanning every table's COUNT on every page."""
    receipt_hash = _hash(binding)
    cache_path = root.parent / CACHE
    try:
        cached = snapshot._read_metadata(cache_path)
        data = cached.get('inventory')
        if (cached.get('version') == VERSION and cached.get('receipt_sha256') == receipt_hash
                and isinstance(data, dict) and cached.get('inventory_sha256') == _hash(data)):
            return data
    except (OSError, ValueError, RuntimeError):
        pass
    shards = sorted((rel for rel in binding['outputs'] if SHARD.fullmatch(rel)),
                    key=lambda rel: int(SHARD.fullmatch(rel).group(1)))
    tables, issues = [], []
    total, first, last = 0, None, None
    for shard in shards:
        if time.monotonic() >= deadline:
            raise RuntimeError('微信全量目录统计达到本次时限，未保存不完整统计')
        with _connection(root, shard, deadline) as conn:
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%' ORDER BY name")]
            for name in names:
                if not TABLE.fullmatch(name):
                    issues.append({'shard': shard, 'table': name, 'reason': 'unrecognized-message-table-name'})
                    continue
                schema = [dict(row) for row in conn.execute('PRAGMA table_info(' + _quoted(name) + ')')]
                columns = {r['name'] for r in schema}
                key = next((alias for alias in ('rowid', '_rowid_', 'oid') if alias not in columns), None)
                try:
                    if key is None: raise sqlite3.OperationalError('no rowid alias')
                    conn.execute('SELECT ' + _quoted(key) + ' FROM ' + _quoted(name) + ' LIMIT 0')
                    # WITHOUT ROWID may accept a quoted unknown identifier as a
                    # literal; sqlite_master's declaration is authoritative here.
                    sql = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] or ''
                    if re.search(r'\bWITHOUT\s+ROWID\b', sql, re.I): raise sqlite3.OperationalError('without rowid')
                except sqlite3.OperationalError:
                    keys = [r for r in schema if r['pk']]
                    key = keys[0]['name'] if len(keys) == 1 and str(keys[0]['type']).upper() == 'INTEGER' else None
                expr = 'count(*) AS n'
                if 'create_time' in columns:
                    expr += ', min(CASE WHEN typeof(create_time) IN (\'integer\',\'real\') THEN create_time END) AS first, max(CASE WHEN typeof(create_time) IN (\'integer\',\'real\') THEN create_time END) AS last'
                row = conn.execute('SELECT ' + expr + ' FROM ' + _quoted(name)).fetchone()
                count = int(row['n'])
                start, end = (row['first'], row['last']) if 'create_time' in columns else (None, None)
                total += count
                if start is not None: first = start if first is None else min(first, start)
                if end is not None: last = end if last is None else max(last, end)
                if key is None: issues.append({'shard': shard, 'table': name, 'reason': 'unsupported-noninteger-row-key'})
                single_pk = next((r['name'] for r in schema if r['pk'] and sum(bool(x['pk']) for x in schema) == 1), None)
                tables.append({'shard': shard, 'table': name, 'columns': sorted(columns), 'key': key,
                               'local_id_unique': single_pk == 'local_id', 'rows': count,
                               'first': start, 'last': end})
    result = {'tables': tables, 'shards': shards, 'source_total': total, 'first': first, 'last': last,
              'issues': issues, 'count_complete': not any(x['reason'] == 'unrecognized-message-table-name' for x in issues)}
    value = {'version': VERSION, 'receipt_sha256': receipt_hash, 'inventory': result, 'inventory_sha256': _hash(result)}
    fd, tmp = tempfile.mkstemp(prefix='.corpus-inventory-', dir=root.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(value)); stream.flush(); os.fsync(stream.fileno())
        if cache_path.is_symlink(): raise RuntimeError('微信语料统计缓存入口无效')
        os.replace(tmp, cache_path)
    finally:
        try: Path(tmp).unlink()
        except FileNotFoundError: pass
    return result


def _common(binding, inventory):
    return {'version': VERSION, 'account_id': binding['source_identity']['id'],
            'source_identity': binding['source_identity'], 'snapshot_generation': binding['snapshot_id'],
            'snapshot_created_at': binding['created_at'], 'source_total': inventory['source_total'] if inventory['count_complete'] else None,
            'source_rows_counted': inventory['source_total'], 'source_total_kind': 'physical-message-rows-before-deduplication',
            'all_source_total': inventory.get('all_source_total', inventory['source_total']) if inventory['count_complete'] else None,
            'scan_scope': 'time-window' if inventory.get('time_filter') else 'full-history',
            'time_filter': inventory.get('time_filter'),
            'source_time_start': _timestamp(inventory['first']), 'source_time_end': _timestamp(inventory['last']),
            'source_shards': len(inventory['shards']), 'source_tables': len(inventory['tables']),
            'self_identity': {'verified': False, 'username': None, 'evidence': None},
            'coverage': {'snapshot': binding['coverage'], 'upstream_sync_complete': False,
                         'time_filter': inventory.get('time_filter'), 'time_bounds': '[since,until)',
                         'history_outside_window_checked': not bool(inventory.get('time_filter')),
                         'undated_messages_included': not bool(inventory.get('time_filter')),
                         'time_field_unavailable_tables': inventory.get('time_field_unavailable_tables', 0),
                         'all_snapshot_message_shards_counted': inventory['count_complete'], 'issues': inventory['issues'],
                         'identity_scope': 'local-source-namespace-not-real-wxid'}}


def _window_inventory(root, binding, inventory, window, deadline):
    if window is None: return inventory
    binding_hash = _hash({'binding': binding, 'inventory': inventory, 'window': window})
    cache_path = root.parent / ('corpus-window-' + _hash(window) + '.json')
    try:
        cached = snapshot._read_metadata(cache_path)
        data = cached.get('inventory')
        if (cached.get('binding_sha256') == binding_hash and isinstance(data, dict)
                and cached.get('inventory_sha256') == _hash(data)):
            return data
    except (OSError, ValueError, RuntimeError): pass
    tables, total, first, last, missing = [], 0, None, None, 0
    where, params = _time_sql(window)
    for shard in inventory['shards']:
        with _connection(root, shard, deadline) as conn:
            for table in (t for t in inventory['tables'] if t['shard'] == shard):
                if time.monotonic() >= deadline: raise RuntimeError('微信窗口统计达到时限，未发布不完整范围')
                if 'create_time' not in table['columns']:
                    count, start, end = 0, None, None; missing += 1
                else:
                    row = conn.execute('SELECT count(*),min(create_time),max(create_time) FROM ' +
                                       _quoted(table['table']) + ' WHERE ' + ' AND '.join(where), params).fetchone()
                    count, start, end = row
                tables.append({**table, 'rows': count, 'first': start, 'last': end})
                total += count
                if start is not None: first = start if first is None else min(first, start)
                if end is not None: last = end if last is None else max(last, end)
    result = {**inventory, 'tables': tables, 'source_total': total, 'first': first, 'last': last,
              'all_source_total': inventory['source_total'], 'time_filter': window,
              'time_field_unavailable_tables': missing}
    value = {'binding_sha256': binding_hash, 'inventory': result, 'inventory_sha256': _hash(result)}
    fd, tmp = tempfile.mkstemp(prefix='.corpus-window-', dir=root.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(value)); stream.flush(); os.fsync(stream.fileno())
        if cache_path.is_symlink(): raise RuntimeError('微信窗口缓存入口无效')
        os.replace(tmp, cache_path)
    finally:
        try: Path(tmp).unlink()
        except FileNotFoundError: pass
    return result


def stats(data_dir, since=None, until=None):
    window = _window(since, until)
    binding, root = _binding(data_dir)
    deadline = time.monotonic() + 60
    inventory = _window_inventory(root, binding, _inventory(root, binding, deadline), window, deadline)
    _check_same(data_dir, binding)
    return {**_common(binding, inventory), 'command': 'corpus stats', 'complete': inventory['count_complete'],
            'export_supported': not inventory['issues'],
            'message': ('统计全部分片内创建时间窗口的物理行；窗口外旧消息的编辑、晚到或无有效时间记录须全量复核。' if window else '统计全部已发布快照消息分片的物理行；重复消息去重后数量由接收方统计，未包含未解密库或上游未同步记录。')}


def _cursor(binding, inventory, table_index, after):
    value = {'version': VERSION, 'account_id': binding['source_identity']['id'], 'snapshot_id': binding['snapshot_id'],
             'inventory_sha256': _hash(inventory), 'table_index': table_index, 'after': after}
    if inventory.get('time_filter'): value['time_filter'] = inventory['time_filter']
    return base64.urlsafe_b64encode(_json(value)).decode().rstrip('=')


def _position(cursor, binding, inventory):
    if cursor is None or cursor == '': return 0, None
    if not isinstance(cursor, str) or len(cursor) > 4096: raise RuntimeError('微信导出游标无效')
    try:
        value = json.loads(base64.b64decode(cursor + '='*(-len(cursor)%4), altchars=b'-_', validate=True))
        expected = {'version': VERSION, 'account_id': binding['source_identity']['id'], 'snapshot_id': binding['snapshot_id'], 'inventory_sha256': _hash(inventory)}
        if inventory.get('time_filter'): expected['time_filter'] = inventory['time_filter']
        if not isinstance(value, dict) or set(value) != set(expected) | {'table_index','after'}: raise ValueError()
        if any(value.get(key) != expected[key] for key in expected): raise ValueError()
        index, after = value['table_index'], value['after']
        if type(index) is not int or not 0 <= index <= len(inventory['tables']): raise ValueError()
        if after is not None and (type(after) is not int or not -(2**63) <= after < 2**63): raise ValueError()
        return index, after
    except (ValueError, TypeError, UnicodeError):
        raise RuntimeError('微信导出游标无效或快照已改变；请从当前快照重新开始') from None


def _names(root, binding, deadline):
    names, conversations = {}, {}
    if 'contact/contact.db' in binding['outputs']:
        with _connection(root, 'contact/contact.db', deadline) as conn:
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(contact)')}
            if {'username','nick_name','remark'} <= cols:
                for row in conn.execute('SELECT username,nick_name,remark FROM contact'):
                    if isinstance(row['username'], str): names[row['username']] = row['remark'] or row['nick_name'] or row['username']
    candidates = set(names)
    if 'session/session.db' in binding['outputs']:
        with _connection(root, 'session/session.db', deadline) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='SessionTable'").fetchone():
                for row in conn.execute('SELECT username FROM SessionTable'):
                    if isinstance(row[0], str): candidates.add(row[0])
    for username in candidates:
        table = 'Msg_' + hashlib.md5(username.encode()).hexdigest()
        conversations.setdefault(table, set()).add(username)
    return names, conversations


def _decode(raw):
    if raw is None: return '', 'empty', None
    if isinstance(raw, str): return raw, 'text', None
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
        try: return raw.decode('utf-8'), 'utf8', None
        except UnicodeDecodeError: pass
        try:
            import zstandard
            import io
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
                value = reader.read(MAX_ITEM_BYTES+1)
                if len(value) > MAX_ITEM_BYTES: raise ValueError('decoded payload bound exceeded')
            return value.decode('utf-8'), 'zstd-utf8', None
        except Exception:
            # Preserve undecodable payload; no replacement or silent truncation.
            return '', 'binary-not-decoded', base64.b64encode(raw).decode('ascii')
    return str(raw), 'nontext-scalar', None


def _item(row, table, account, names, conversations, sender_map):
    keys = set(row.keys())
    get = lambda key: row[key] if key in keys else None
    locations = sorted(conversations.get(table['table'], set()))
    username = locations[0] if len(locations) == 1 else None
    conversation_id = username or 'table:' + table['table']
    sender = sender_map.get(get('real_sender_id'))
    raw = get('message_content')
    text, state, binary = _decode(raw)
    content_hash = hashlib.sha256(raw if isinstance(raw, bytes) else _json(raw)).hexdigest()
    server = get('server_id')
    # Preserve the source record identity. Local row IDs are not globally unique.
    source_key = [account, table['shard'], table['table'], get('local_id') if table['local_id_unique'] else row['__corpus_key']]
    if type(server) is int and server > 0:
        logical_key = [account, table['table'], 'server_id', str(server)]
        stable_scope = 'conversation-server-id'
    else:
        logical_key = [*source_key, 'local-source-position']
        stable_scope = 'local-shard-table-key-no-global-id'
    item = {'remote_id': 'wechat-message:' + _hash(logical_key), 'record_id': 'wechat-row:' + _hash(source_key),
            'kind': 'message', 'account_id': account, 'conversation_id': conversation_id,
            'conversation': names.get(username, username) if username else table['table'],
            'conversation_resolution': 'username-md5-match' if username else ('ambiguous-md5-match' if locations else 'unresolved-table-hash'),
            'conversation_kind': 'group' if username and username.endswith('@chatroom') else ('contact-or-service' if username else 'unknown'),
            'sender_id': sender, 'sender': names.get(sender, sender) if sender else None,
            'sender_resolution': 'shard-Name2Id-rowid' if sender else 'unresolved',
            'is_self': None, 'text': text, 'content_state': state, 'content_sha256': content_hash,
            'message_type': get('local_type'), 'occurred_at': _timestamp(get('create_time')),
            'raw_create_time': get('create_time'), 'server_id': str(server) if type(server) is int else None,
            'source_locator': {'shard': table['shard'], 'table': table['table'], 'row_key': row['__corpus_key'], 'local_id': get('local_id')},
            'identity_stability': stable_scope}
    if binary is not None: item['raw_content_base64'] = binary
    if 'message_content' not in keys: item['content_state'] = 'content-column-unavailable'
    return item


@contextlib.contextmanager
def _cached_connection(session, shard, deadline):
    connections = session.setdefault('connections', {})
    if shard not in connections:
        connections[shard] = session['stack'].enter_context(_connection(session['root'], shard, deadline))
    conn = connections[shard]
    conn.set_progress_handler(lambda: _progress(deadline), 5000)
    yield conn


def _export_page(data_dir, cursor, limit, page_bytes, session, window=None):
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_ROWS: raise RuntimeError('单页消息条数必须在 1 到 1000 之间')
    if type(page_bytes) is not int or not 65536 <= page_bytes <= PAGE_BYTES: raise RuntimeError('微信单页字节预算无效')
    deadline = time.monotonic()+60
    if 'binding' not in session:
        binding, root = _binding(data_dir)
        inventory = _window_inventory(root, binding, _inventory(root, binding, deadline), window, deadline)
        names, conversations = _names(root, binding, deadline)
        session.update(binding=binding, root=root, inventory=inventory, names=names, conversations=conversations, senders={})
    else:
        binding, root, inventory = session['binding'], session['root'], session['inventory']
        names, conversations = session['names'], session['conversations']
        _check_same(data_dir, binding)
    if inventory['issues']: raise RuntimeError('微信消息分片存在未支持表结构；请先查看 corpus stats 的具体覆盖问题')
    index, after = _position(cursor, binding, inventory)
    items, used, tables = [], 0, inventory['tables']
    start_index, start_after = index, after
    account = binding['source_identity']['id']
    while index < len(tables) and len(items) < limit:
        table = tables[index]
        if table['rows'] == 0:
            index += 1; after = None; continue
        if time.monotonic() >= deadline:
            if items or index != start_index or after != start_after: break
            raise RuntimeError('微信导出达到本次时限，游标未推进')
        with _cached_connection(session, table['shard'], deadline) as conn:
            if table['shard'] not in session['senders']:
                sender_map = {}
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Name2Id'").fetchone():
                    for r in conn.execute('SELECT rowid,user_name FROM Name2Id'):
                        if isinstance(r[1], str):
                            sender_map[r[0]] = r[1]
                            candidate = 'Msg_' + hashlib.md5(r[1].encode()).hexdigest()
                            conversations.setdefault(candidate, set()).add(r[1])
                session['senders'][table['shard']] = sender_map
            sender_map = session['senders'][table['shard']]
            key = _quoted(table['key'])
            sql = 'SELECT ' + key + ' AS __corpus_key, * FROM ' + _quoted(table['table'])
            clauses, params = _time_sql(window)
            if after is not None: clauses.append(key + ' > ?'); params.append(after)
            if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
            sql += ' ORDER BY ' + key + ' LIMIT ?'; params.append(limit-len(items)+1)
            rows = conn.execute(sql, params)
            exhausted, full = True, False
            for row in rows:
                if type(row['__corpus_key']) is not int: raise RuntimeError('微信消息表游标字段不是整数，未推进游标')
                item = _item(row, table, account, names, conversations, sender_map)
                size = len(_json(item))
                if size > MAX_ITEM_BYTES:
                    raise RuntimeError('单条微信消息超过 16MiB 安全上限，未截断内容或推进游标')
                if items and (len(items) >= limit or used+size > page_bytes):
                    exhausted, full = False, True; break
                items.append(item); used += size; after = row['__corpus_key']
                if len(items) >= limit or used >= page_bytes:
                    exhausted, full = False, True; break
            if full: break
            if exhausted: index += 1; after = None
    done = index >= len(tables)
    _check_same(data_dir, binding)
    return {**_common(binding, inventory), 'command': 'corpus export', 'items': items,
            'rows_returned': len(items), 'complete': done, 'has_more': not done,
            'next_cursor': None if done else _cursor(binding, inventory, index, after),
            'page_bytes': used, 'page_limit': limit,
            'message': ('完整遍历所有分片内 [since,until) 创建时间窗口；complete 只表示该窗口完成，窗口外历史编辑、晚到和无有效时间记录须全量复核。' if window else '完整遍历已发布快照的全部消息表；继续 next_cursor 直到 complete=true。正文不按字符截断，媒体正文保留消息载荷但不自动识别或转写。')}


def export(data_dir, cursor=None, limit=1000, page_bytes=PAGE_BYTES, since=None, until=None):
    window = _window(since, until)
    with contextlib.ExitStack() as stack:
        return _export_page(data_dir, cursor, limit, page_bytes, {'stack': stack}, window)


def iter_export(data_dir, cursor=None, limit=1000, pages=None, page_bytes=PAGE_BYTES, since=None, until=None):
    """Yield committed-frame candidates; the receiver commits each cursor.

    No page-count limit unless explicitly requested for one invocation. Closing
    the iterator/CLI closes every owned SQLite connection; last received cursor
    remains resumable by a new process against this same snapshot.
    """
    if pages is not None and (type(pages) is not int or pages < 1):
        raise RuntimeError('本次批量页数必须是正整数')
    window = _window(since, until)
    with contextlib.ExitStack() as stack:
        session = {'stack': stack}
        emitted = 0
        while pages is None or emitted < pages:
            value = _export_page(data_dir, cursor, limit, page_bytes, session, window)
            yield value
            emitted += 1
            if value['complete']: break
            cursor = value['next_cursor']
