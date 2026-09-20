"""Local derivation tests use an invented account and generated PNG only."""
import contextlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class LocalImageKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.storage = self.root / 'Documents/xwechat_files/wxid_synthetic_25f9/db_storage'
        self.storage.mkdir(parents=True)
        self.cache = self.root / 'Documents/app_data/radium/kvcomm'
        self.cache.mkdir(parents=True)
        (self.cache / 'key_123456789_1.statistic').write_bytes(b'not read by recovery')
        self.data = self.root / 'data'
        self.data.mkdir()
        self.config = self.data / 'config.json'
        self.config.write_text(json.dumps({'preserved': True}))
        self.sample = self.storage.parent / 'msg/attach/test/2026-09/Img/test.dat'
        self.sample.parent.mkdir(parents=True)
        stream = io.BytesIO()
        Image.new('RGB', (12, 9), (11, 22, 33)).save(stream, format='PNG')
        self.write_sample(stream.getvalue())

    def write_sample(self, plain):
        key = b'67800d8d9c7be92f'  # fixed test vector; not a real account key
        n = 32
        cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        encrypted = cipher.update(plain[:n] + b'\x10' * 16) + cipher.finalize()
        self.sample.write_bytes(b'\x07\x08V2\x08\x07' + struct.pack('<LL', n, len(plain)-n)
                               + b'\x00' + encrypted + bytes(x ^ 21 for x in plain[n:]))

    def recover(self, sample=None):
        spec = importlib.util.find_spec('vchat_core.local_image_keys')
        self.assertIsNotNone(spec, 'missing local cache image-key recovery')
        module = importlib.import_module('vchat_core.local_image_keys')
        out, err = io.StringIO(), io.StringIO()
        with patch.object(module.decrypt_pipeline, 'find_db_storage', return_value=self.storage), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = module.recover_local_image_key(self.data, sample=sample or self.sample)
        self.assertEqual(out.getvalue() + err.getvalue(), '')
        self.assertNotIn('67800d8d9c7be92f', json.dumps(result))
        self.assertEqual(list(self.data.glob('.local-image-*')), [])
        return result

    def test_full_decode_required_before_private_atomic_config_publish(self):
        result = self.recover()
        self.assertTrue(result['success'], result)
        cfg = json.loads(self.config.read_text())
        self.assertEqual(cfg['image_aes_key'], b'67800d8d9c7be92f'.hex())
        self.assertEqual(cfg['image_xor_key'], 21)
        self.assertTrue(cfg['preserved'])
        self.assertEqual(cfg['db_dir'], str(self.storage))
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertIn('完整', result['reason'])

    def test_header_magic_with_corrupted_png_is_rejected(self):
        self.write_sample(b'\x89PNG\r\n\x1a\n' + b'not a valid image' * 10)
        before = self.config.read_bytes()
        self.assertFalse(self.recover()['success'])
        self.assertEqual(self.config.read_bytes(), before)

    def test_unrelated_cached_account_is_not_used(self):
        (self.cache / 'key_123456789_1.statistic').rename(self.cache / 'key_987654321_1.statistic')
        before = self.config.read_bytes()
        self.assertFalse(self.recover()['success'])
        self.assertEqual(self.config.read_bytes(), before)

    def test_sample_outside_selected_account_is_rejected(self):
        other = self.root / 'other.dat'
        other.write_bytes(self.sample.read_bytes())
        self.assertFalse(self.recover(other)['success'])

    def test_mismatched_config_account_is_preserved(self):
        other = self.root / 'other/db_storage'
        other.mkdir(parents=True)
        self.config.write_text(json.dumps({'db_dir': str(other)}))
        before = self.config.read_bytes()
        self.assertFalse(self.recover()['success'])
        self.assertEqual(self.config.read_bytes(), before)

    def test_malformed_config_is_preserved(self):
        self.config.write_text('{broken')
        self.assertFalse(self.recover()['success'])
        self.assertEqual(self.config.read_text(), '{broken')

    def test_absent_local_cache_reports_failure_without_config_change(self):
        (self.cache / 'key_123456789_1.statistic').unlink()
        before = self.config.read_bytes()
        self.assertFalse(self.recover()['success'])
        self.assertEqual(self.config.read_bytes(), before)

    def test_symlinked_cache_file_is_ignored(self):
        p = self.cache / 'key_123456789_1.statistic'
        p.unlink()
        p.symlink_to(self.sample)
        self.assertFalse(self.recover()['success'])


if __name__ == '__main__':
    unittest.main()
