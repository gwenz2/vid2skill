"""
validator.py - Deterministic pre-flight AST and rule-based linter for agent skills.

Enforces:
1. Strict file naming ('SKILL.md' uppercase).
2. Kebab-case directory and frontmatter 'name' (starts with letter, lowercase).
3. Trigger-rich frontmatter 'description' with negative scope bounds.
4. Progressive disclosure line count budget (< 400 lines).
5. Explicit Scope Lock / 'When NOT to Use' boundary section.
6. Local link integrity, URL unquoting, and path containment (no directory traversal escapes).
7. Paired test suites presence and structure (tests/should_trigger.yaml & should_not_trigger.yaml).
"""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional
import yaml


@dataclass
class ValidationResult:
    skill_dir: Path
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    line_count: int = 0
    test_count_positive: int = 0
    test_count_negative: int = 0

    def summary(self) -> str:
        status = "PASS" if self.is_valid else "FAIL"
        lines = [
            f"Validation Result: [{status}] for {self.skill_dir.name}",
            f" - Line Count: {self.line_count}/400 budget",
            f" - Positive Test Cases: {self.test_count_positive}",
            f" - Negative Test Cases: {self.test_count_negative}",
        ]
        if self.errors:
            lines.append("Errors:")
            for e in self.errors:
                lines.append(f"  [X] {e}")
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        return "\n".join(lines)


def validate_frontmatter(fm_text: str) -> Tuple[Optional[dict], List[str]]:
    errors = []
    try:
        data = yaml.safe_load(fm_text)
        if not isinstance(data, dict):
            errors.append("Frontmatter must be a valid YAML mapping (dictionary).")
            return None, errors
        return data, errors
    except Exception as e:
        errors.append(f"Failed to parse frontmatter YAML: {e}")
        return None, errors


def validate_skill_dir(skill_dir_path: str | Path, strict: bool = False) -> ValidationResult:
    """
    Validate an agent skill folder against production standards.
    """
    skill_dir = Path(skill_dir_path).resolve()
    errors: List[str] = []
    warnings: List[str] = []
    line_count = 0
    pos_count = 0
    neg_count = 0

    if not skill_dir.is_dir():
        errors.append(f"Directory does not exist: {skill_dir}")
        return ValidationResult(skill_dir, False, errors, warnings)

    # 1. Exact SKILL.md naming check (cross-platform, case-sensitive check via os.listdir)
    actual_files = os.listdir(skill_dir)
    if "SKILL.md" not in actual_files:
        case_variants = [f for f in actual_files if f.lower() == "skill.md"]
        if case_variants:
            errors.append(f"Found incorrectly cased skill file '{case_variants[0]}'. Must be exact 'SKILL.md'.")
        else:
            errors.append("Missing required 'SKILL.md' root file.")
        return ValidationResult(skill_dir, False, errors, warnings)

    skill_md = skill_dir / "SKILL.md"

    content = skill_md.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    line_count = len(lines)

    # 2. Line count budget (< 400 lines per spec)
    if line_count > 400:
        msg = f"SKILL.md exceeds 400-line budget ({line_count} lines). Move large tables or detailed checklists to references/."
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    # 3. Frontmatter parse & check
    if not content.startswith("---"):
        errors.append("SKILL.md must begin with '---' YAML frontmatter delimiter.")
        return ValidationResult(skill_dir, False, errors, warnings, line_count)

    parts = content.split("---", 2)
    if len(parts) < 3:
        errors.append("Unclosed or malformed YAML frontmatter. Expected opening and closing '---'.")
        return ValidationResult(skill_dir, False, errors, warnings, line_count)

    fm_data, fm_errors = validate_frontmatter(parts[1])
    errors.extend(fm_errors)

    if fm_data is not None:
        name = fm_data.get("name")
        if not name:
            errors.append("Frontmatter missing required 'name' field.")
        else:
            name_str = str(name).strip()
            if not re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name_str):
                errors.append(f"Skill name '{name_str}' must be strict lowercase kebab-case starting with a letter (e.g. 'code-reviewer').")
            # Directory name check
            if skill_dir.name != name_str:
                warnings.append(f"Folder name '{skill_dir.name}' does not match skill name '{name_str}'.")

        desc = fm_data.get("description")
        if not desc:
            errors.append("Frontmatter missing required 'description' field.")
        else:
            desc_str = str(desc).strip()
            if len(desc_str) < 30:
                warnings.append("Description is very brief. Should detail specific trigger keywords and boundaries.")
            if "use when" not in desc_str.lower() and "trigger" not in desc_str.lower():
                warnings.append("Description should start with or include 'Use when...' to enable agent trigger detection.")
            if "do not use" not in desc_str.lower() and "not for" not in desc_str.lower():
                warnings.append("Description should specify negative trigger boundaries ('Do not use for...').")

    # 4. Scope Lock / Negative Boundary Section Check
    body_text = parts[2]
    has_scope_lock = any(header in body_text for header in [
        "When NOT to Use",
        "Scope Lock",
        "Out of Scope",
        "Scope Boundaries",
        "Exclusions",
    ])
    if not has_scope_lock:
        errors.append("Missing explicit Scope Lock section (e.g. '### When NOT to Use' or '## Scope Lock').")

    # 5. Link Integrity & Path Containment Check
    link_pattern = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")
    for m in link_pattern.finditer(body_text):
        href = m.group(2).strip()
        # Skip external protocols & anchors
        if href.startswith(("http://", "https://", "mailto:", "#", "file:", "vscode:")):
            continue

        target_file_part = href.split("#")[0].split("?")[0]
        if not target_file_part:
            continue

        # Decode URL percent-encoding (e.g. %20 -> space)
        target_file_clean = urllib.parse.unquote(target_file_part)
        resolved_target = (skill_dir / target_file_clean).resolve()

        # Check containment
        try:
            resolved_target.relative_to(skill_dir)
        except ValueError:
            errors.append(f"Path traversal detected: link target '{href}' escapes skill directory.")
            continue

        # Check existence
        if not resolved_target.exists():
            errors.append(f"Broken internal relative link: '{href}' not found at {resolved_target}.")

    # 6. Paired Test Suite Verification
    tests_dir = skill_dir / "tests"
    pos_file = tests_dir / "should_trigger.yaml"
    neg_file = tests_dir / "should_not_trigger.yaml"

    if not pos_file.is_file():
        warnings.append("Missing 'tests/should_trigger.yaml' positive eval suite.")
    else:
        try:
            pos_data = yaml.safe_load(pos_file.read_text(encoding="utf-8"))
            if isinstance(pos_data, list):
                pos_count = len(pos_data)
                if pos_count == 0:
                    warnings.append("'tests/should_trigger.yaml' is empty.")
            else:
                errors.append("'tests/should_trigger.yaml' must be a YAML list of prompt strings.")
        except Exception as e:
            errors.append(f"Failed to parse 'tests/should_trigger.yaml': {e}")

    if not neg_file.is_file():
        warnings.append("Missing 'tests/should_not_trigger.yaml' negative eval suite.")
    else:
        try:
            neg_data = yaml.safe_load(neg_file.read_text(encoding="utf-8"))
            if isinstance(neg_data, list):
                neg_count = len(neg_data)
                if neg_count == 0:
                    warnings.append("'tests/should_not_trigger.yaml' is empty.")
            else:
                errors.append("'tests/should_not_trigger.yaml' must be a YAML list of prompt strings.")
        except Exception as e:
            errors.append(f"Failed to parse 'tests/should_not_trigger.yaml': {e}")

    is_valid = len(errors) == 0
    return ValidationResult(
        skill_dir=skill_dir,
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        line_count=line_count,
        test_count_positive=pos_count,
        test_count_negative=neg_count,
    )
