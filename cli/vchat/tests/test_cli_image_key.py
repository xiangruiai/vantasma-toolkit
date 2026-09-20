import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("vchat_image_cli_tests", str(ROOT / "vchat"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class ImageKeyCommandTests(unittest.TestCase):
    def invoke(self, argv, result, *, uid=0, local=False):
        helper = types.ModuleType("vchat_core.image_keys")
        helper.extract_image_key = Mock(return_value=result)
        local_helper = types.ModuleType("vchat_core.local_image_keys")
        local_helper.recover_local_image_key = Mock(return_value=result)
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with patch.dict(sys.modules, {"vchat_core.image_keys": helper,
                                          "vchat_core.local_image_keys": local_helper}), \
                    patch.object(sys, "argv", ["vchat", *argv]), \
                    patch.object(cli, "DATA_DIR", data_dir), \
                    patch.object(cli, "get_decrypted_dir", return_value=data_dir / "decrypted"), \
                    patch.object(cli.os, "geteuid", return_value=uid), \
                    patch("platform.system", return_value="Darwin"), \
                    patch.object(cli, "cmd_setup", side_effect=AssertionError("must not rerun setup")), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = 0
                try:
                    cli.main()
                except SystemExit as exc:
                    rc = exc.code
            called = local_helper.recover_local_image_key if local else helper.extract_image_key
            if local:
                helper.extract_image_key.assert_not_called()
            return rc, out.getvalue(), err.getvalue(), called, data_dir

    def test_dedicated_command_only_calls_image_scanner(self):
        rc, out, err, scanner, data_dir = self.invoke(
            ["image-key", "--timeout", "45", "--sample", "/tmp/example.dat"],
            {"success": True, "reason": "validated", "config_path": "/tmp/config.json"},
        )
        self.assertEqual(rc, 0, err)
        scanner.assert_called_once_with(data_dir, ROOT / "vchat_native",
                                        timeout_seconds=45, sample=Path("/tmp/example.dat"))
        self.assertIn("/tmp/config.json", out)

    def test_failed_capture_has_nonzero_exit_and_explanation(self):
        rc, out, err, scanner, _ = self.invoke(
            ["image-key"], {"success": False, "reason": "sample key not resident"}
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("sample key not resident", out + err)
        scanner.assert_called_once()

    def test_candidate_success_does_not_claim_complete_image_validation(self):
        explanation = "候选已通过首段检查；完整图片仍需验证"
        rc, out, err, _, _ = self.invoke(
            ["image-key"], {"success": True, "reason": explanation,
                            "config_path": "/tmp/config.json"}
        )
        self.assertEqual(rc, 0)
        self.assertIn(explanation, out)
        self.assertNotIn("图片密钥已验证", out + err)

    def test_non_root_request_does_not_start_scan(self):
        rc, out, err, scanner, _ = self.invoke(["image-key"], {}, uid=501)
        self.assertNotEqual(rc, 0)
        self.assertIn("sudo", out + err)
        scanner.assert_not_called()

    def test_local_recovery_works_without_sudo_or_native_scan(self):
        rc, out, err, recover, data_dir = self.invoke(
            ["image-key", "--local", "--sample", "/tmp/example.dat"],
            {"success": True, "reason": "完整图片解码验证通过", "config_path": "/tmp/config.json"},
            uid=501, local=True,
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("完整图片解码验证通过", out)
        recover.assert_called_once_with(data_dir, timeout_seconds=300, sample=Path('/tmp/example.dat'))

    def test_invalid_timeout_does_not_start_scan(self):
        rc, out, err, scanner, _ = self.invoke(["image-key", "--timeout", "0"], {})
        self.assertEqual(rc, 2)
        self.assertIn("timeout", out + err)
        scanner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
