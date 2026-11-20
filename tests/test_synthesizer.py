import unittest
from vid2skill.core.synthesizer import (
    slugify_to_kebab,
    extract_key_concepts,
    extract_actionable_steps,
    extract_pitfalls,
    detect_domain,
    synthesize_skill,
)

SAMPLE_LECTURE = """
Building High Performance PostgreSQL Databases.
Rule 1: Always add indexes to foreign keys.
Step 1: Ingest query metrics from pg_stat_statements.
Step 2: Identify slow queries taking over 100ms.
Step 3: Analyze execution plans with EXPLAIN ANALYZE.
Avoid doing sequential table scans on multi-million row tables.
A common mistake is forgetting connection pooling.
"""

class TestSynthesizer(unittest.TestCase):

    def test_slugify_to_kebab(self):
        self.assertEqual(slugify_to_kebab("How to Build Clean Architecture in 2026!"), "how-to-build-clean-architecture-in-2026")
        self.assertEqual(slugify_to_kebab("  Multiple   Spaces__And_Underscores  "), "multiple-spaces-and-underscores")
        self.assertEqual(slugify_to_kebab("123 Numbers First"), "skill-123-numbers-first")

    def test_slugify_truncation_word_boundary(self):
        long_title = "Building Ultra High Speed Telemetry Pipelines Across Multiple Cloud Datacenters"
        slug = slugify_to_kebab(long_title)
        self.assertLessEqual(len(slug), 45)
        self.assertFalse(slug.endswith("-"))
        # Must not be cut off in the middle of a word
        words = slug.split("-")
        for w in words:
            self.assertTrue(len(w) >= 2)

    def test_detect_domain(self):
        self.assertEqual(detect_domain("Shader tricks", "godot gdscript 2d particles"), "Game-Development")
        self.assertEqual(detect_domain("Tailwind CSS", "frontend responsive typography"), "Product-Design")
        self.assertEqual(detect_domain("Enterprise Sales", "cold outreach b2b pricing"), "Business")
        self.assertEqual(detect_domain("Postgres Tuning", "sql database indexing backend"), "Software-Development")

    def test_extract_key_concepts(self):
        concepts = extract_key_concepts(SAMPLE_LECTURE)
        self.assertTrue(len(concepts) > 0)
        self.assertTrue(any("index" in c.lower() for c in concepts))
        # Ensure negative words (avoid/mistake) are excluded from positive concepts
        for c in concepts:
            self.assertNotIn("avoid", c.lower())
            self.assertNotIn("mistake", c.lower())

    def test_extract_actionable_steps(self):
        steps = extract_actionable_steps(SAMPLE_LECTURE)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0][0], "Ingest query metrics from pg_stat_statements")

    def test_extract_pitfalls(self):
        pitfalls = extract_pitfalls(SAMPLE_LECTURE)
        self.assertTrue(len(pitfalls) > 0)

    def test_synthesize_skill_complete_bundle(self):
        bundle = synthesize_skill(
            raw_content=SAMPLE_LECTURE,
            title_hint="PostgreSQL Performance Tuning",
            name_hint="postgres-perf-tuning",
        )
        self.assertEqual(bundle.name, "postgres-perf-tuning")
        self.assertIn("postgres-perf-tuning", bundle.description)
        self.assertIn("Use when", bundle.description)
        self.assertIn("Do not use for", bundle.description)

        # Check SKILL.md body structure
        self.assertIn("---", bundle.skill_md)
        self.assertIn("name: postgres-perf-tuning", bundle.skill_md)
        self.assertIn("## Triggers & Scope Boundaries", bundle.skill_md)
        self.assertIn("### When to Use", bundle.skill_md)
        self.assertIn("### When NOT to Use", bundle.skill_md)
        self.assertIn("## Core Workflow", bundle.skill_md)
        self.assertIn("## Mental Models & Principles", bundle.skill_md)
        self.assertIn("## Anti-Patterns & Common Pitfalls", bundle.skill_md)

        # Check line count budget (< 400 lines)
        lines = bundle.skill_md.splitlines()
        self.assertLess(len(lines), 400)

        # Check paired test triggers generated
        self.assertGreaterEqual(len(bundle.should_trigger), 4)
        self.assertGreaterEqual(len(bundle.should_not_trigger), 4)

        # Check bundled scripts
        self.assertIn("scripts/validate.py", bundle.scripts)
        self.assertIn("scripts/eval_triggers.py", bundle.scripts)

    def test_export_standalone_rejects_path_traversal(self):
        import tempfile
        from vid2skill.exporters.standalone import export_standalone_skill

        bundle = synthesize_skill(
            raw_content=SAMPLE_LECTURE,
            title_hint="PostgreSQL Performance Tuning",
            name_hint="postgres-perf-tuning",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle.name = "../escape"
            with self.assertRaises(ValueError):
                export_standalone_skill(bundle, tmpdir)

            bundle.name = "postgres-perf-tuning"
            bundle.references["../escape.md"] = "bad"
            with self.assertRaises(ValueError):
                export_standalone_skill(bundle, tmpdir)


if __name__ == "__main__":
    unittest.main()
