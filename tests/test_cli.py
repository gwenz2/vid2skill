import unittest
from pathlib import Path
import tempfile
from click.testing import CliRunner

from vid2skill.cli import main

class TestCLI(unittest.TestCase):

    def setUp(self):
        self.runner = CliRunner()
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_cli_create_and_validate_and_eval(self):
        out_skills_dir = self.tmpdir / "skills"
        # 1. Run create command
        res_create = self.runner.invoke(main, [
            "create",
            "--input", "Step 1: Ingest telemetry. Step 2: Calculate p99 latency. Step 3: Alert on spikes.",
            "--name", "latency-monitor",
            "--title", "Latency Monitoring Pipeline",
            "--out", str(out_skills_dir),
            "--domain", "Software-Development",
        ])
        self.assertEqual(res_create.exit_code, 0, f"CLI create failed: {res_create.output}")
        created_dir = out_skills_dir / "latency-monitor"
        self.assertTrue((created_dir / "SKILL.md").is_file())
        self.assertTrue((created_dir / "tests" / "should_trigger.yaml").is_file())
        self.assertTrue((created_dir / "tests" / "should_not_trigger.yaml").is_file())

        # 2. Run validate command
        res_val = self.runner.invoke(main, ["validate", str(created_dir)])
        self.assertEqual(res_val.exit_code, 0, f"CLI validate failed: {res_val.output}")
        self.assertIn("PASS", res_val.output)

        # 3. Run eval command
        res_eval = self.runner.invoke(main, ["eval", str(created_dir)])
        self.assertEqual(res_eval.exit_code, 0, f"CLI eval failed: {res_eval.output}")

        # 4. Run improve command
        res_imp = self.runner.invoke(main, [
            "improve",
            str(created_dir),
            "--feedback", "Agent failed to trigger on 'check p99 latency distribution'",
            "--type", "missed_trigger"
        ])
        self.assertEqual(res_imp.exit_code, 0, f"CLI improve failed: {res_imp.output}")

    def test_cli_extract_text(self):
        sample_file = self.tmpdir / "input.txt"
        sample_file.write_text("Clean architecture and domain driven design principles.", encoding="utf-8")
        out_file = self.tmpdir / "extracted.txt"

        res = self.runner.invoke(main, [
            "extract",
            str(sample_file),
            "--out", str(out_file)
        ])
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(out_file.is_file())
        self.assertIn("Clean architecture", out_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
