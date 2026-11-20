#!/usr/bin/env python3
"""
scripts/validate.py - Standalone pre-flight AST & rule validator for agent skills.
Can be executed directly in any environment with or without vid2skill installed.
Usage:
    python scripts/validate.py <path_to_skill_folder> [--strict]
"""

import os
import re
import sys
from pathlib import Path

# Add repo root to sys.path if running within repo
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from vid2skill.core.validator import validate_skill_dir
except ImportError:
    import yaml

    def validate_skill_dir(skill_dir_path, strict=False):
        skill_dir = Path(skill_dir_path).resolve()
        errors, warnings = [], []
        line_count = pos_count = neg_count = 0

        if not skill_dir.is_dir():
            errors.append(f"Directory not found: {skill_dir}")
            return _res(skill_dir, False, errors, warnings, 0, 0, 0)

        actual_files = os.listdir(skill_dir)
        if "SKILL.md" not in actual_files:
            cased = [f for f in actual_files if f.lower() == "skill.md"]
            if cased:
                errors.append(f"Found incorrectly cased skill file '{cased[0]}'. Must be exact 'SKILL.md'.")
            else:
                errors.append("Missing required 'SKILL.md' root file.")
            return _res(skill_dir, False, errors, warnings, 0, 0, 0)

        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        line_count = len(lines)

        if line_count > 400:
            msg = f"SKILL.md exceeds 400-line budget ({line_count} lines)."
            (errors if strict else warnings).append(msg)

        if not content.startswith("---"):
            errors.append("SKILL.md must begin with '---' YAML frontmatter delimiter.")
            return _res(skill_dir, False, errors, warnings, line_count, 0, 0)

        parts = content.split("---", 2)
        if len(parts) < 3:
            errors.append("Unclosed or malformed YAML frontmatter.")
            return _res(skill_dir, False, errors, warnings, line_count, 0, 0)

        try:
            fm_data = yaml.safe_load(parts[1]) or {}
        except Exception as e:
            errors.append(f"Failed to parse frontmatter: {e}")
            fm_data = {}

        name_str = str(fm_data.get("name", "")).strip()
        if not re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name_str):
            errors.append(f"Skill name '{name_str}' must be strict lowercase kebab-case starting with letter.")

        desc_str = str(fm_data.get("description", "")).strip()
        if not desc_str:
            errors.append("Frontmatter missing required 'description' field.")
        elif "use when" not in desc_str.lower() and "trigger" not in desc_str.lower():
            warnings.append("Description should include 'Use when...' to enable agent trigger detection.")

        body = parts[2]
        if not any(h in body for h in ["When NOT to Use", "Scope Lock", "Out of Scope", "Scope Boundaries"]):
            errors.append("Missing explicit Scope Lock section (e.g. '### When NOT to Use' or '## Scope Lock').")

        # Links
        for m in re.finditer(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)", body):
            href = m.group(2).strip()
            if href.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_part = href.split("#")[0].split("?")[0]
            if not target_part:
                continue
            res_target = (skill_dir / target_part).resolve()
            try:
                res_target.relative_to(skill_dir)
            except ValueError:
                errors.append(f"Path traversal detected: '{href}' escapes skill directory.")
                continue
            if not res_target.exists():
                errors.append(f"Broken internal relative link: '{href}' not found.")

        # Tests
        t_dir = skill_dir / "tests"
        pos_f, neg_f = t_dir / "should_trigger.yaml", t_dir / "should_not_trigger.yaml"
        if pos_f.is_file():
            try:
                pos_d = yaml.safe_load(pos_f.read_text(encoding="utf-8"))
                pos_count = len(pos_d) if isinstance(pos_d, list) else 0
            except Exception:
                pass
        if neg_f.is_file():
            try:
                neg_d = yaml.safe_load(neg_f.read_text(encoding="utf-8"))
                neg_count = len(neg_d) if isinstance(neg_d, list) else 0
            except Exception:
                pass

        return _res(skill_dir, len(errors) == 0, errors, warnings, line_count, pos_count, neg_count)

    class _res:
        def __init__(self, s_dir, ok, errs, warns, lc, pc, nc):
            self.skill_dir = s_dir
            self.is_valid = ok
            self.errors = errs
            self.warnings = warns
            self.line_count = lc
            self.test_count_positive = pc
            self.test_count_negative = nc
        def summary(self):
            status = "PASS" if self.is_valid else "FAIL"
            out = [f"Validation Result: [{status}] for {self.skill_dir.name}",
                   f" - Line Count: {self.line_count}/400 budget",
                   f" - Positive Test Cases: {self.test_count_positive}",
                   f" - Negative Test Cases: {self.test_count_negative}"]
            for e in self.errors: out.append(f"  [X] {e}")
            for w in self.warnings: out.append(f"  [!] {w}")
            return "\n".join(out)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Deterministic pre-flight AST & rule validator for agent skills.")
    parser.add_argument("path", nargs="?", default=".", help="Path to the skill directory (default: current dir)")
    parser.add_argument("--strict", action="store_true", help="Treat line count budget warnings (>400 lines) as hard errors.")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    res = validate_skill_dir(target, strict=args.strict)
    print(res.summary())
    sys.exit(0 if res.is_valid else 1)

if __name__ == "__main__":
    main()
