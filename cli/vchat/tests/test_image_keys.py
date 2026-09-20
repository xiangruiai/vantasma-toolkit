import contextlib
import importlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from test_image_codec import encrypted_image


class ImageKeyCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.storage = self.root / "accounts/current/db_storage"
        self.storage.mkdir(parents=True)
        self.data = self.root / "vchat-data"
        self.data.mkdir()
        self.native = self.root / "native"
        self.native.mkdir()
        self.key = bytes(range(16))
        self.sample = self.make_sample(self.storage.parent, "current.dat", self.key)
        self.config = self.data / "config.json"
        self.config.write_text(json.dumps({"other_setting": {"preserved": True}}))
        self.scanner = self.native / "find_image_key_macos"
        self.fake_scanner({"image_aes_key": self.key.hex(), "image_xor_key": 136})

    def make_sample(self, account, name, key):
        path = account / "msg/attach/synthetic-chat/2026-09/Img" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encrypted_image(key)[0])
        return path

    def fake_scanner(self, output, returncode=0):
        self.scanner.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            f"print({json.dumps(output)!r})\n"
            "print('private scanner diagnostic', file=sys.stderr)\n"
            f"sys.exit({returncode})\n"
        )
        self.scanner.chmod(0o700)

    def api(self):
        spec = importlib.util.find_spec("vchat_core.image_keys")
        self.assertIsNotNone(spec, "missing independently retryable image-key helper")
        return importlib.import_module("vchat_core.image_keys")

    def capture(self, **kwargs):
        module = self.api()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("vchat_core.decrypt_pipeline.find_db_storage", return_value=self.storage), \
             patch("vchat_core.decrypt_pipeline.find_wechat_main_pid", return_value=12345), \
             patch("vchat_core.image_keys._pid_matches_account", return_value=True, create=True), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = module.extract_image_key(self.data, self.native, **kwargs)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(self.key.hex(), json.dumps(result))
        self.assertNotIn("image_aes_key", result)
        return result

    def test_success_preserves_settings_and_publishes_correct_private_config(self):
        result = self.capture()
        self.assertTrue(result["success"], result)
        cfg = json.loads(self.config.read_text())
        self.assertEqual(cfg["other_setting"], {"preserved": True})
        self.assertEqual(cfg["image_aes_key"], self.key.hex())
        self.assertEqual(cfg["db_dir"], str(self.storage))
        self.assertEqual(cfg["_image_key_sample"], str(self.sample))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertEqual(result["config_path"], str(self.config))

    def test_automatic_selection_is_limited_to_current_account(self):
        other = self.make_sample(self.root / "accounts/other", "other.dat", b"different-key-16")
        os.utime(other, (2_000_000_000, 2_000_000_000))
        result = self.capture()
        self.assertTrue(result["success"], result)
        self.assertEqual(json.loads(self.config.read_text())["_image_key_sample"], str(self.sample))

    def test_explicit_sample_from_other_account_is_rejected(self):
        other = self.make_sample(self.root / "accounts/other", "other.dat", self.key)
        before = self.config.read_bytes()
        result = self.capture(sample=other)
        self.assertFalse(result["success"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_explicit_symlink_cannot_escape_current_account(self):
        other = self.make_sample(self.root / "accounts/other", "other.dat", self.key)
        link = self.sample.with_name("escape.dat")
        link.symlink_to(other)
        self.assertFalse(self.capture(sample=link)["success"])

    def test_existing_config_cannot_silently_switch_accounts(self):
        module = self.api()
        old_storage = self.root / "accounts/previous/db_storage"
        old_storage.mkdir(parents=True)
        self.config.write_text(json.dumps({"db_dir": str(old_storage), "other_setting": "keep"}))
        before = self.config.read_bytes()
        with patch.object(module.subprocess, "run", side_effect=AssertionError("must reject before scan")):
            result = self.capture()
        self.assertFalse(result["success"])
        self.assertIn("账号", result["reason"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_legacy_wrong_database_path_is_not_guessed_or_repaired(self):
        module = self.api()
        wrong_storage = self.storage.parent / "msg/db_storage"
        wrong_storage.mkdir(parents=True)
        self.config.write_text(json.dumps({"db_dir": str(wrong_storage)}))
        before = self.config.read_bytes()
        with patch.object(module.subprocess, "run", side_effect=AssertionError("must reject before scan")):
            result = self.capture()
        self.assertFalse(result["success"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_same_account_config_path_is_accepted(self):
        self.config.write_text(json.dumps({"db_dir": str(self.storage)}))
        self.assertTrue(self.capture()["success"])

    def test_missing_data_directory_is_not_created(self):
        self.config.unlink()
        self.data.rmdir()
        result = self.capture()
        self.assertFalse(result["success"])
        self.assertFalse(self.data.exists())

    def test_non_directory_data_path_is_rejected(self):
        self.config.unlink()
        self.data.rmdir()
        self.data.write_text("preserve this file")
        self.assertFalse(self.capture()["success"])
        self.assertEqual(self.data.read_text(), "preserve this file")

    def test_invalid_config_is_preserved(self):
        for contents in ("{broken", "[]", '"text"'):
            with self.subTest(contents=contents):
                self.config.write_text(contents)
                result = self.capture()
                self.assertFalse(result["success"])
                self.assertEqual(self.config.read_text(), contents)

    def test_wrong_sample_key_does_not_replace_config(self):
        self.fake_scanner({"image_aes_key": "00" * 16, "image_xor_key": 136})
        before = self.config.read_bytes()
        self.assertFalse(self.capture()["success"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_jpeg_magic_with_impossible_segment_length_is_not_a_valid_key(self):
        # Reproduce the native scanner's weak-magic false positive without
        # using any account data or captured secret.
        prefix = b"\xff\xd8\xff\xe0\xff\xfe" + b"synthetic fake JPEG header"
        pad = 16 - len(prefix) % 16
        encryptor = Cipher(algorithms.AES(self.key), modes.ECB()).encryptor()
        ciphertext = encryptor.update(prefix + bytes([pad]) * pad) + encryptor.finalize()
        import struct
        self.sample.write_bytes(b"\x07\x08V2\x08\x07" + struct.pack("<LL", len(prefix), 0) + b"\x00" + ciphertext)
        before = self.config.read_bytes()
        result = self.capture()
        self.assertFalse(result["success"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_verified_jpeg_tail_corrects_native_hardcoded_xor_value(self):
        prefix = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        payload, _ = encrypted_image(self.key, prefix=prefix,
                                     tail=b"synthetic JPEG entropy\xff\xd9", xor_key=0x53)
        self.sample.write_bytes(payload)
        self.assertTrue(self.capture()["success"])
        self.assertEqual(json.loads(self.config.read_text())["image_xor_key"], 0x53)

    def test_verified_png_footer_corrects_native_hardcoded_xor_value(self):
        footer = b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
        payload, _ = encrypted_image(self.key, tail=footer, xor_key=0x27)
        self.sample.write_bytes(payload)
        self.assertTrue(self.capture()["success"])
        self.assertEqual(json.loads(self.config.read_text())["image_xor_key"], 0x27)

    def test_unverified_native_xor_does_not_overwrite_existing_value(self):
        self.config.write_text(json.dumps({"image_xor_key": 0x73}))
        result = self.capture()
        self.assertTrue(result["success"])
        self.assertEqual(json.loads(self.config.read_text())["image_xor_key"], 0x73)
        self.assertIn("尾部密钥未验证", result["reason"])

    def test_unverified_native_xor_is_not_added_to_new_config(self):
        result = self.capture()
        self.assertTrue(result["success"])
        self.assertNotIn("image_xor_key", json.loads(self.config.read_text()))
        self.assertIn("尾部密钥未验证", result["reason"])

    def test_image_without_xor_tail_cannot_validate_an_xor_key(self):
        self.sample.write_bytes(encrypted_image(self.key, tail=b"")[0])
        result = self.capture()
        self.assertTrue(result["success"])
        self.assertNotIn("image_xor_key", json.loads(self.config.read_text()))
        self.assertIn("尾部密钥未验证", result["reason"])

    def test_scanner_failure_does_not_forward_sensitive_output(self):
        self.fake_scanner({"image_aes_key": self.key.hex()}, returncode=6)
        self.assertFalse(self.capture()["success"])

    def test_native_candidate_does_not_inherit_old_full_decode_verification(self):
        self.config.write_text(json.dumps({
            'image_aes_key': 'aa' * 16,
            '_image_key_verification': {'method': 'local-cache', 'full_decode': True},
            'preserved': True,
        }))
        self.assertTrue(self.capture()['success'])
        cfg = json.loads(self.config.read_text())
        self.assertEqual(cfg['image_aes_key'], self.key.hex())
        self.assertFalse(cfg.get('_image_key_verification', {}).get('full_decode', False))
        self.assertTrue(cfg['preserved'])

    def test_native_failures_have_distinct_safe_diagnostics(self):
        cases = [(3, "样本"), (4, "未运行"), (5, "内存访问"),
                 (6, "未找到通过校验"), (42, "异常退出")]
        before = self.config.read_bytes()
        for code, explanation in cases:
            with self.subTest(code=code):
                self.fake_scanner({"image_aes_key": self.key.hex()}, returncode=code)
                result = self.capture()
                self.assertFalse(result["success"])
                self.assertIn(explanation, result["reason"])
                self.assertIn(f"原生退出码 {code}", result["reason"])
                self.assertEqual(self.config.read_bytes(), before)

    def test_timeout_does_not_forward_captured_output_or_change_config(self):
        module = self.api()
        before = self.config.read_bytes()
        failure = subprocess.TimeoutExpired("scanner", 1, output=self.key.hex(), stderr=self.key.hex())
        with patch.object(module.subprocess, "run", side_effect=failure):
            result = self.capture(timeout_seconds=1)
        self.assertFalse(result["success"])
        self.assertIn("超时", result["reason"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_invalid_scanner_payload_is_not_persisted(self):
        for payload in ([], {"image_aes_key": "g" * 32},
                        {"image_aes_key": self.key.hex(), "image_xor_key": 256}):
            with self.subTest(payload_type=type(payload).__name__):
                before = self.config.read_bytes()
                self.fake_scanner(payload)
                self.assertFalse(self.capture()["success"])
                self.assertEqual(self.config.read_bytes(), before)

    def test_timeout_must_be_a_bounded_integer(self):
        for seconds in (0, -1, 601, True, 1.5):
            with self.subTest(seconds=seconds):
                self.assertFalse(self.capture(timeout_seconds=seconds)["success"])

    def test_failed_atomic_replace_preserves_old_config(self):
        module = self.api()
        before = self.config.read_bytes()
        with patch.object(module.os, "replace", side_effect=OSError("synthetic failure")):
            self.assertFalse(self.capture()["success"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), ["config.json"])


if __name__ == "__main__":
    unittest.main()
