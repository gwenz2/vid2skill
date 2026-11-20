import unittest
from pathlib import Path
import tempfile

from vid2skill.core.evaluator import evaluate_triggers, score_prompt
from vid2skill.core.synthesizer import synthesize_skill
from vid2skill.exporters.standalone import export_standalone_skill


class TestEvaluator(unittest.TestCase):

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_score_prompt_exact_and_negative(self):
        skill_name = "godot-shader-tricks"
        description = "Use when writing Godot 4 shaders. Triggers on 'godot shaders', 'visual shaders'. Do not use for physics."
        pos_triggers = ["godot shaders", "visual shaders", "screen reading shaders"]
        neg_boundaries = ["2D physics collisions", "character rigidbodies", "unrelated math"]

        # Exact positive
        triggered, score, clues = score_prompt(
            "Help me write godot shaders for water reflections",
            skill_name, description, pos_triggers, neg_boundaries
        )
        self.assertTrue(triggered)
        self.assertGreater(score, 0.7)

        # Name mention
        triggered, score, clues = score_prompt(
            "Can we run godot-shader-tricks on this material?",
            skill_name, description, pos_triggers, neg_boundaries
        )
        self.assertTrue(triggered)
        self.assertGreater(score, 0.9)

        # Negative boundary suppression
        triggered, score, clues = score_prompt(
            "Configure 2D physics collisions and character rigidbodies",
            skill_name, description, pos_triggers, neg_boundaries
        )
        self.assertFalse(triggered)
        self.assertLess(score, 0.35)

    def test_negative_prompt_mentioning_skill_name_suppressed(self):
        skill_name = "git-precommit-guard"
        description = "Use when running git precommit guard. Do not use for general editing."
        pos_triggers = ["run precommit checks", "git-precommit-guard workflow"]
        neg_boundaries = ["Do not run git-precommit-guard", "disable precommit hooks", "unrelated git rebase"]

        # User specifically asks NOT to run the skill
        triggered, score, clues = score_prompt(
            "Do not run git-precommit-guard on this release branch",
            skill_name, description, pos_triggers, neg_boundaries
        )
        self.assertFalse(triggered, "Negative prompt mentioning skill name should be suppressed")

    def test_word_boundary_avoids_substring_false_positive(self):
        skill_name = "format"
        description = "Use when formatting source code files."
        pos_triggers = ["format code", "reformat python file"]
        neg_boundaries = ["unrelated tasks"]

        # "information" contains substring "format"
        triggered, score, clues = score_prompt(
            "Please provide information about this repository architecture",
            skill_name, description, pos_triggers, neg_boundaries
        )
        self.assertFalse(triggered, "Word boundary should prevent 'information' triggering on 'format'")

    def test_full_evaluation_pipeline(self):
        bundle = synthesize_skill(
            raw_content="Step 1: Inspect. Step 2: Fix. Step 3: Verify.",
            title_hint="Audio Normalizer Pipeline",
            name_hint="audio-normalizer",
        )
        skill_dir = export_standalone_skill(bundle, self.tmpdir)

        report = evaluate_triggers(skill_dir)
        self.assertEqual(report.skill_name, "audio-normalizer")
        self.assertGreater(report.total_tests, 0)
        self.assertGreaterEqual(report.accuracy, 0.8)
        self.assertGreaterEqual(report.precision, 0.8)
        self.assertGreaterEqual(report.recall, 0.8)


if __name__ == "__main__":
    unittest.main()
