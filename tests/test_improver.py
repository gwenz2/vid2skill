import json
import unittest
from pathlib import Path
import tempfile
import yaml

from vid2skill.core.improver import improve_skill
from vid2skill.core.synthesizer import synthesize_skill
from vid2skill.exporters.standalone import export_standalone_skill


class TestImprover(unittest.TestCase):

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)

        bundle = synthesize_skill(
            raw_content="Step 1: Parse schema. Step 2: Generate migrations.",
            title_hint="Database Migration Automation",
            name_hint="db-migrations",
        )
        self.skill_dir = export_standalone_skill(bundle, self.tmpdir)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_improve_missed_trigger(self):
        feedback = "Agent failed to trigger when user said 'migrate postgres tables automatically'"
        res = improve_skill(self.skill_dir, feedback, feedback_type="missed_trigger")

        self.assertTrue(res.added_to_positive_tests)
        self.assertTrue(res.added_to_skill_md)

        # Verify should_trigger.yaml
        pos_file = self.skill_dir / "tests" / "should_trigger.yaml"
        pos_data = yaml.safe_load(pos_file.read_text(encoding="utf-8"))
        self.assertIn("migrate postgres tables automatically", pos_data)

        # Verify SKILL.md
        skill_md = (self.skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("migrate postgres tables automatically", skill_md)

        # Verify history log
        log_file = self.skill_dir / "history" / "feedback_log.json"
        self.assertTrue(log_file.is_file())
        log_data = json.loads(log_file.read_text(encoding="utf-8"))
        self.assertEqual(len(log_data), 1)
        self.assertEqual(log_data[0]["type"], "missed_trigger")

    def test_improve_false_trigger(self):
        feedback = "Agent incorrectly triggered on 'explain history of ancient Rome'"
        res = improve_skill(self.skill_dir, feedback, feedback_type="false_trigger")

        self.assertTrue(res.added_to_negative_tests)
        neg_file = self.skill_dir / "tests" / "should_not_trigger.yaml"
        neg_data = yaml.safe_load(neg_file.read_text(encoding="utf-8"))
        self.assertIn("explain history of ancient Rome", neg_data)

    def test_improve_rule_correction(self):
        feedback = "Always run rollback dry-run before applying migrations"
        res = improve_skill(self.skill_dir, feedback, feedback_type="rule_correction")

        self.assertTrue(res.added_to_skill_md)
        skill_md = (self.skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Always run rollback dry-run before applying migrations", skill_md)


if __name__ == "__main__":
    unittest.main()
