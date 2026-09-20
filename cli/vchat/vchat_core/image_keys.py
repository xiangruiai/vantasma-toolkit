"""Bounded, independently retryable image-key capture for the active local account.

The native scanner's stdout contains a secret and stderr can contain source
metadata. Neither stream, nor an exception containing them, leaves this module.
"""
from __future__ import annotations

import heapq
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import decrypt_pipeline
from .image_codec import V2_MAGIC_6, detect_format, normalize_aes_key, infer_v2_xor_key


def _pid_matches_account(pid: int, owner_uid: int,
                         timeout_seconds: float = 5) -> bool:
    """Reject a process outside the data owner's OS account before scanning.

    sudo's invoking UID, when present, must agree with the source directory's
    owner. ps output is only metadata; neither diagnostics nor exceptions are
    forwarded. Failure or an ambiguous result is a rejection, never a guess.
    """
    sudo_uid = os.environ.get("SUDO_UID")
    if sudo_uid is not None:
        if not re.fullmatch(r"[0-9]+", sudo_uid) or int(sudo_uid) != owner_uid:
            return False
    try:
        completed = subprocess.run(
            ["/bin/ps", "-o", "uid=", "-p", str(pid)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
        uid = completed.stdout.strip()
        return (completed.returncode == 0 and re.fullmatch(r"[0-9]+", uid) is not None
                and int(uid) == owner_uid)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def _sample_header(path: Path, attachment_root: Path) -> bytes | None:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(attachment_root) or not resolved.is_file():
            return None
        with resolved.open("rb") as stream:
            header = stream.read(31)
        return header if len(header) == 31 and header[:6] == V2_MAGIC_6 else None
    except (OSError, RuntimeError):
        return None


def _choose_sample(attachment_root: Path, deadline: float) -> Path | None:
    """Keep only the newest 30 local candidates; never search another account."""
    recent = []
    for candidate in attachment_root.rglob("*.dat"):
        if time.monotonic() >= deadline:
            raise TimeoutError
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            item = (candidate.stat().st_mtime_ns, str(candidate))
            if len(recent) < 30:
                heapq.heappush(recent, item)
            elif item > recent[0]:
                heapq.heapreplace(recent, item)
        except OSError:
            continue
    for _, filename in sorted(recent, reverse=True):
        if time.monotonic() >= deadline:
            raise TimeoutError
        candidate = Path(filename)
        if _sample_header(candidate, attachment_root) is not None:
            return candidate.resolve()
    return None


def _read_config(path: Path) -> tuple[dict, os.stat_result | None]:
    if not path.exists() and not path.is_symlink():
        return {}, None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
        raise ValueError("invalid config file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid config object")
    return value, info


def _publish_config(path: Path, value: dict, owner: os.stat_result,
                    previous: os.stat_result | None) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".image-key-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if previous is None:
            if path.exists() or path.is_symlink():
                raise ValueError("configuration appeared during capture")
        else:
            current = path.lstat()
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
            if not stat.S_ISREG(current.st_mode) or identity(current) != identity(previous):
                raise ValueError("configuration changed during capture")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def extract_image_key(data_dir: Path, native_dir: Path, timeout_seconds: int = 300,
                      sample: Path | None = None) -> dict:
    """Store a structure-checked V2 key candidate without returning or printing it.

    ``timeout_seconds`` bounds candidate selection and the native scan (1..600).
    An explicit sample must be under this account's ``msg/attach`` directory.
    The data directory must already exist. An existing ``db_dir`` must resolve
    to this same source account; old or invalid bindings are never guessed.
    Existing settings and file ownership are preserved; config is published as
    mode 0600 only after first-block format/structure checks. These checks are
    not full image validation: a complete decoder must verify the final image
    before claiming recovery. No image is exported here.
    """
    config_path = Path(data_dir).expanduser().absolute() / "config.json"

    def result(success: bool, reason: str) -> dict:
        return {"success": success, "reason": reason, "config_path": str(config_path)}

    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        return result(False, "超时参数必须为 1 到 600 秒的整数")
    if not config_path.parent.is_dir():
        return result(False, "数据目录不存在或不是目录；请先完成数据目录初始化，未创建任何目录")
    deadline = time.monotonic() + timeout_seconds
    try:
        config, previous = _read_config(config_path)
    except (OSError, ValueError, UnicodeError):
        return result(False, "现有配置无法安全读取或不是 JSON 对象；未覆盖配置")
    try:
        storage = decrypt_pipeline.find_db_storage()
        if storage is None:
            return result(False, "找不到当前账号的微信数据库目录")
        storage = Path(storage).resolve(strict=True)
        if "db_dir" in config:
            configured_storage = config["db_dir"]
            try:
                if not isinstance(configured_storage, str) or not configured_storage:
                    raise ValueError
                configured_storage = Path(configured_storage).expanduser().resolve(strict=True)
                if configured_storage != storage:
                    raise ValueError
            except (OSError, RuntimeError, ValueError):
                return result(False, "配置中的数据库目录与当前账号不一致或不可用；请核对账号及配置，未扫描或覆盖配置")
        account = storage.parent
        attachments = (account / "msg" / "attach").resolve()
        if not attachments.is_relative_to(account) or not attachments.is_dir():
            return result(False, "当前账号没有可用的本地附件目录")
        if sample is None:
            chosen = _choose_sample(attachments, deadline)
        else:
            chosen = Path(sample).expanduser().resolve(strict=True)
            if _sample_header(chosen, attachments) is None:
                return result(False, "样本必须是当前账号附件目录内的完整 V2 图片文件")
        if chosen is None:
            return result(False, "当前账号近期缓存中未找到 V2 样本；请先在微信里打开近期图片")
        header = _sample_header(chosen, attachments)
        if header is None:
            return result(False, "图片样本已变化或不可读；未更新配置")
        scanner = (Path(native_dir) / "find_image_key_macos").resolve()
        if not scanner.is_file() or not os.access(scanner, os.X_OK):
            return result(False, "图片扫描器不存在或不可执行；请先编译 vchat_native")
        pid = decrypt_pipeline.find_wechat_main_pid()
        if not pid:
            return result(False, "微信未运行；请启动并登录微信")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        if not _pid_matches_account(pid, storage.stat().st_uid,
                                    timeout_seconds=min(5, remaining)):
            return result(False, "微信进程所属用户与数据目录或 sudo 用户不一致，或无法核验；未扫描或更新配置")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        completed = subprocess.run(
            [str(scanner), "--pid", str(pid), "--sample", str(chosen)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=remaining, check=False,
        )
    except (subprocess.TimeoutExpired, TimeoutError):
        return result(False, "图片密钥扫描超时；未更新配置，可打开近期图片后重试")
    except (OSError, RuntimeError, ValueError):
        return result(False, "图片样本或扫描器不可用；未更新配置")

    if completed.returncode != 0:
        native_code = completed.returncode
        explanations = {
            2: "图片扫描器参数无效",
            3: "图片样本的 V2 格式、分段长度或读取状态无效",
            4: "扫描开始时微信未运行或进程已退出",
            5: "微信进程内存访问被系统拒绝；需要核对当前进程的调试权限",
            6: "未找到通过校验的图片密钥；可能是扫描覆盖范围、密钥未驻留或样本格式限制，不能仅归因于未打开图片",
        }
        explanation = explanations.get(native_code, "图片扫描器异常退出")
        return result(False, f"{explanation}（原生退出码 {native_code}）；未更新配置")
    try:
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise ValueError
        supplied = payload.get("image_aes_key")
        if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", supplied):
            raise ValueError
        key = normalize_aes_key(supplied)
        xor_key = payload.get("image_xor_key", 0x88)
        if type(xor_key) is not int or not 0 <= xor_key <= 255:
            raise ValueError
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        plain = decryptor.update(header[15:31]) + decryptor.finalize()
        fmt = detect_format(plain)
        if fmt == "bin":
            return result(False, "候选密钥未通过图片样本验证；未更新配置")
        if fmt == "jpg":
            # The native scanner checks only SOI + a weak marker prefix. With
            # millions of candidates this can match random plaintext. Reject
            # impossible first segments before trusting/persisting a candidate.
            marker = plain[3]
            valid_first_marker = (0xE0 <= marker <= 0xEF or marker == 0xFE
                                  or marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC4,
                                                0xC5, 0xC6, 0xC7, 0xC9, 0xCA,
                                                0xCB, 0xCC, 0xCD, 0xCE, 0xCF,
                                                0xDB, 0xDD))
            segment_length = int.from_bytes(plain[4:6], "big")
            if (not valid_first_marker or segment_length < 2
                    or 4 + segment_length > chosen.stat().st_size - 15):
                return result(False, "候选密钥未通过 JPEG 段结构检查；未更新配置")
        inferred_xor = infer_v2_xor_key(chosen, fmt)
    except (OSError, ValueError, TypeError):
        return result(False, "图片扫描器输出格式无效；未更新配置")

    config.update(image_aes_key=key.hex(), db_dir=str(storage), _image_key_sample=str(chosen))
    # A native structure check cannot inherit a previous key's full decode.
    config.pop('_image_key_verification', None)
    if inferred_xor is not None:
        config["image_xor_key"] = inferred_xor
    try:
        _publish_config(config_path, config, previous or storage.stat(), previous)
    except (OSError, ValueError, TypeError):
        return result(False, "配置写入失败或捕获期间已被修改；保留原有配置")
    tail_status = "尾部密钥未验证，未覆盖原值；" if inferred_xor is None else ""
    return result(True, "候选图片密钥已通过首段格式检查并安全写入配置；" + tail_status + "完整图片仍需验证")


__all__ = ["extract_image_key"]
