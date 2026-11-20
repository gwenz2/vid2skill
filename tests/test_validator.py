import unittest
from pathlib import Path
import tempfile
import yaml

from vid2skill.core.validator import validate_skill_dir
from vid2skill.core.synthesizer import synthesize_skill
from vid2skill.exporters.standalone import export_standalone_skill


class TestValidator(unittest.TestCase):

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_obj.name)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_valid_synthesized_skill_passes(self):
        bundle = synthesize_skill(
            raw_content="Step 1: Build. Step 2: Test. Step 3: Deploy. Always verify tests.",
            title_hint="Automated Deployment Workflow",
            name_hint="auto-deploy",
        )
        skill_dir = export_standalone_skill(bundle, self.tmpdir)
        res = validate_skill_dir(skill_dir)
        self.assertTrue(res.is_valid, f"Validation failed with errors: {res.errors}")
        self.assertLessEqual(res.line_count, 400)
        self.assertGreater(res.test_count_positive, 0)
        self.assertGreater(res.test_count_negative, 0)

    def test_missing_skill_md(self):
        empty_dir = self.tmpdir / "empty-skill"
        empty_dir.mkdir()
        res = validate_skill_dir(empty_dir)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Missing required 'SKILL.md'" in e for e in res.errors))

    def test_wrong_casing_skill_md(self):
        bad_dir = self.tmpdir / "bad-case"
        bad_dir.mkdir()
        (bad_dir / "skill.md").write_text("# title", encoding="utf-8")
        res = validate_skill_dir(bad_dir)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("incorrectly cased" in e for e in res.errors))

    def test_invalid_kebab_case_name(self):
        bad_dir = self.tmpdir / "CamelCaseSkill"
        bad_dir.mkdir()
        content = "---\nname: CamelCaseSkill\ndescription: Use when deploying apps. Do not use for testing.\n---\n# Title\n### When NOT to Use\n- Nothing"
        (bad_dir / "SKILL.md").write_text(content, encoding="utf-8")
        res = validate_skill_dir(bad_dir)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("strict lowercase kebab-case" in e for e in res.errors))

    def test_missing_scope_lock(self):
        bad_dir = self.tmpdir / "no-scope-lock"
        bad_dir.mkdir()
        content = "---\nname: no-scope-lock\ndescription: Use when doing things. Do not use for other.\n---\n# Title\n## Workflow\n1. Do it."
        (bad_dir / "SKILL.md").write_text(content, encoding="utf-8")
        res = validate_skill_dir(bad_dir)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Missing explicit Scope Lock" in e for e in res.errors))

    def test_broken_link_and_traversal(self):
        bad_dir = self.tmpdir / "broken-links"
        bad_dir.mkdir()
        content = (
            "---\nname: broken-links\ndescription: Use when testing links. Do not use for prod.\n---\n"
            "# Title\n### When NOT to Use\n- Nothing\n"
            "See [docs](docs/nonexistent.md) and [escape](../../outside.txt)"
        )
        (bad_dir / "SKILL.md").write_text(content, encoding="utf-8")
        res = validate_skill_dir(bad_dir)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Path traversal detected" in e for e in res.errors))
        self.assertTrue(any("Broken internal relative link" in e for e in res.errors))

    def test_line_count_budget_strict(self):
        bad_dir = self.tmpdir / "bloated-skill"
        bad_dir.mkdir()
        long_body = "\n".join([f"Line {i}" for i in range(450)])
        content = (
            f"---\nname: bloated-skill\ndescription: Use when bloated. Do not use for lean.\n---\n"
            f"# Title\n### When NOT to Use\n- Nothing\n{long_body}"
        )
        (bad_dir / "SKILL.md").write_text(content, encoding="utf-8")
        res_lax = validate_skill_dir(bad_dir, strict=False)
        self.assertTrue(res_lax.is_valid)
        self.assertTrue(any("exceeds 400-line budget" in w for w in res_lax.warnings))

        res_strict = validate_skill_dir(bad_dir, strict=True)
        self.assertFalse(res_strict.is_valid)
        self.assertTrue(any("exceeds 400-line budget" in e for e in res_strict.errors))


if __name__ == "__main__":
    unittest.main()
