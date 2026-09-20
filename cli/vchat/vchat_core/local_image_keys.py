"""Recover macOS image keys from local account metadata, without process access.

Independently implemented from the public algorithm description at
https://github.com/erbanku/weixin-cli#附件提取图片 : ASCII MD5 prefix of
decimal UIN + account id; the low UIN byte is the tail XOR value. Only cache
filenames are read. No brute force, network access, or native scanner is used.
Every candidate must pass a complete Pillow decode before configuration changes.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import time
import warnings

from . import decrypt_pipeline
from .image_codec import v2_decrypt
from .image_keys import _choose_sample, _read_config, _publish_config, _sample_header


def recover_local_image_key(data_dir: Path, timeout_seconds: int = 300,
                            sample: Path | None = None) -> dict:
    config_path = Path(data_dir).expanduser().absolute() / 'config.json'

    def result(success, reason):
        return {'success': success, 'reason': reason, 'config_path': str(config_path)}

    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        return result(False, '超时参数必须为 1 到 600 秒的整数')
    if not config_path.parent.is_dir():
        return result(False, '数据目录不存在；未创建配置')
    try:
        from PIL import Image
    except ImportError:
        return result(False, '完整图片验证需要当前 Python 环境安装 Pillow；未更新配置')
    deadline = time.monotonic() + timeout_seconds
    try:
        config, previous = _read_config(config_path)
        storage = decrypt_pipeline.find_db_storage()
        if storage is None:
            return result(False, '找不到当前账号的数据库目录')
        storage = Path(storage).resolve(strict=True)
        if storage.name != 'db_storage' or storage.parent.parent.name != 'xwechat_files':
            return result(False, '数据库目录结构不符合当前 macOS 本地缓存格式')
        if 'db_dir' in config:
            bound = config['db_dir']
            if not isinstance(bound, str) or not bound or Path(bound).expanduser().resolve(strict=True) != storage:
                return result(False, '配置账号与当前数据目录不一致；未更新配置')
        match = re.fullmatch(r'(.+)_([0-9a-fA-F]{4})', storage.parent.name)
        if match is None:
            return result(False, '账号目录没有可核验的缓存后缀；未推测账号')
        account_id, suffix = match.groups()
        attachments = (storage.parent / 'msg/attach').resolve(strict=True)
        if not attachments.is_relative_to(storage.parent):
            return result(False, '附件目录超出当前账号；未读取样本')
        chosen = (_choose_sample(attachments, deadline) if sample is None
                  else Path(sample).expanduser().resolve(strict=True))
        if chosen is None or _sample_header(chosen, attachments) is None:
            return result(False, '没有当前账号可用的 V2 图片样本')
        if chosen.stat().st_size > 32 * 1024 * 1024:
            return result(False, '验证样本超过 32 MiB；请选择较小的本地图片')
        cache_root = (storage.parents[2] / 'app_data').resolve()
        candidates = set()
        for path in cache_root.glob('*/kvcomm/key_*.statistic'):
            if time.monotonic() >= deadline:
                raise TimeoutError
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(cache_root):
                continue
            found = re.fullmatch(r'key_([0-9]{1,10})_.+\.statistic', path.name)
            if found is None:
                continue
            uin = int(found[1])
            if not 0 < uin <= 0xffffffff:
                continue
            if hashlib.md5(str(uin).encode('ascii')).hexdigest()[:4] == suffix.lower():
                candidates.add(uin)
            if len(candidates) > 256:
                return result(False, '匹配缓存过多，拒绝猜测；未更新配置')
        if not candidates:
            return result(False, '本地缓存中没有与当前账号匹配的信息；未扫描内存或更新配置')
        for uin in sorted(candidates):
            if time.monotonic() >= deadline:
                raise TimeoutError
            key = hashlib.md5((str(uin) + account_id).encode('utf-8')).hexdigest()[:16].encode('ascii')
            with tempfile.TemporaryDirectory(prefix='.local-image-', dir=config_path.parent) as temporary:
                output, fmt = v2_decrypt(chosen, Path(temporary) / 'sample.bin', key, uin & 255)
                if output is None:
                    continue
                os.chmod(output, 0o600)
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', Image.DecompressionBombWarning)
                        with Image.open(output) as image:
                            if image.width * image.height > 40_000_000:
                                continue
                            image.verify()
                        with Image.open(output) as image:
                            image.load()
                            actual_format = image.format
                except Exception:
                    continue  # malformed or unsupported media; never print contents
            if time.monotonic() >= deadline:
                raise TimeoutError
            config.update(image_aes_key=key.hex(), image_xor_key=uin & 255,
                          db_dir=str(storage), _image_key_sample=str(chosen),
                          _image_key_verification={'method': 'local-cache', 'full_decode': True,
                                                   'format': actual_format, 'verified_at': time.time()})
            _publish_config(config_path, config, previous or storage.stat(), previous)
            return result(True, '已从本地缓存恢复图片密钥，完整图片解码验证通过；配置已安全保存')
        return result(False, '本地候选均未通过完整图片验证；未更新配置')
    except TimeoutError:
        return result(False, '本地图片验证超时；未更新配置')
    except (OSError, ValueError, TypeError, RuntimeError):
        return result(False, '本地缓存、样本或配置无法安全读取/保存；未报告恢复成功')


__all__ = ['recover_local_image_key']
