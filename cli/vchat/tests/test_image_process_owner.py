"""Process ownership checks use fake ps results, never real process memory."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from vchat_core import image_keys


class ImageProcessOwnerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(image_keys, "_pid_matches_account"),
                        "image capture must verify the selected process owner")

    def check(self, output="501\n", returncode=0, sudo_uid=None, **kwargs):
        environment = {} if sudo_uid is None else {"SUDO_UID": sudo_uid}
        result = subprocess.CompletedProcess([], returncode, output, "private diagnostic")
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(image_keys.subprocess, "run", return_value=result) as run:
            matched = image_keys._pid_matches_account(12345, 501, **kwargs)
        return matched, run

    def test_matching_process_owner_is_accepted(self):
        matched, run = self.check("  501\n")
        self.assertTrue(matched)
        self.assertEqual(run.call_args.args[0], ["/bin/ps", "-o", "uid=", "-p", "12345"])

    def test_other_process_owner_is_rejected(self):
        self.assertFalse(self.check("502\n")[0])

    def test_matching_sudo_owner_is_accepted(self):
        self.assertTrue(self.check(sudo_uid="501")[0])

    def test_mismatched_or_invalid_sudo_owner_is_rejected_before_ps(self):
        for sudo_uid in ("502", "", "invalid", "-1", "501\n502"):
            with self.subTest(sudo_uid=sudo_uid):
                matched, run = self.check(sudo_uid=sudo_uid)
                self.assertFalse(matched)
                run.assert_not_called()

    def test_ps_failure_and_ambiguous_output_are_rejected(self):
        for output, returncode in (("501\n", 1), ("", 0), ("uid=501", 0),
                                   ("501\n502\n", 0), ("-1", 0)):
            with self.subTest(output=output, returncode=returncode):
                self.assertFalse(self.check(output, returncode)[0])

    def test_ps_timeout_and_error_do_not_escape(self):
        for failure in (subprocess.TimeoutExpired("ps", 1), OSError("unavailable")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.object(image_keys.subprocess, "run", side_effect=failure):
                self.assertFalse(image_keys._pid_matches_account(12345, 501))

    def test_ps_receives_the_remaining_timeout_budget(self):
        matched, run = self.check(timeout_seconds=0.25)
        self.assertTrue(matched)
        self.assertEqual(run.call_args.kwargs["timeout"], 0.25)

    def test_extract_rejects_unverified_owner_before_native_scan_or_config_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            storage = root / "account/db_storage"
            storage.mkdir(parents=True)
            attachments = root / "account/msg/attach"
            attachments.mkdir(parents=True)
            sample = attachments / "synthetic.dat"
            sample.write_bytes(b"\x07\x08V2\x08\x07" + b"\x00" * 25)
            data = root / "data"
            data.mkdir()
            config = data / "config.json"
            original = json.dumps({"other_setting": "preserve"})
            config.write_text(original)
            native = root / "native"
            native.mkdir()
            scanner = native / "find_image_key_macos"
            scanner.write_text("#!/bin/sh\nexit 99\n")
            scanner.chmod(0o700)
            with patch.object(image_keys.decrypt_pipeline, "find_db_storage", return_value=storage), \
                    patch.object(image_keys.decrypt_pipeline, "find_wechat_main_pid", return_value=12345), \
                    patch.object(image_keys, "_pid_matches_account", return_value=False), \
                    patch.object(image_keys.subprocess, "run", side_effect=AssertionError("must not scan")):
                result = image_keys.extract_image_key(data, native, sample=sample)
            self.assertFalse(result["success"])
            self.assertIn("用户", result["reason"])
            self.assertEqual(config.read_text(), original)


if __name__ == "__main__":
    unittest.main()
