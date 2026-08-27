from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CHECKER = SKILL_DIR / "scripts" / "health_report_check.py"
TEMPLATE = SKILL_DIR / "assets" / "SYSTEM-HEALTH-REPORT.template.md"


class HealthReportCheckTest(unittest.TestCase):
    def run_check(self, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            report.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECKER), str(report)],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_template_has_required_contract(self) -> None:
        result = self.run_check(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_fake_score_and_missing_lane(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        text = text.replace("| 能否续接 | 灰 |  |  |\n", "")
        text += "\n综合得分：82\n"
        result = self.run_check(text)
        self.assertEqual(result.returncode, 1)
        self.assertIn("缺少健康维度：能否续接", result.stdout)
        self.assertIn("精确健康分数", result.stdout)


if __name__ == "__main__":
    unittest.main()
