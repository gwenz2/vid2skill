"""
improver.py - Passive observation, user correction capture, and continuous self-improvement.

Enables agent skills to evolve from real-world telemetry, user corrections,
and edge-case discoveries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
import yaml

from .evaluator import evaluate_triggers, EvaluationReport
from .validator import validate_skill_dir, ValidationResult


@dataclass
class ImprovementResult:
    skill_dir: Path
    action_taken: str
    added_to_positive_tests: bool
    added_to_negative_tests: bool
    added_to_skill_md: bool
    validation: ValidationResult
    evaluation: EvaluationReport


def record_feedback_entry(
    skill_dir: Path,
    feedback_text: str,
    feedback_type: str,  # "missed_trigger", "false_trigger", "rule_correction"
) -> None:
    """Log feedback history to history/feedback_log.json."""
    history_dir = skill_dir / "history"
    history_dir.mkdir(exist_ok=True, parents=True)
    log_file = history_dir / "feedback_log.json"

    entries = []
    if log_file.is_file():
        try:
            entries = json.loads(log_file.read_text(encoding="utf-8"))
        except Exception:
            entries = []

    entries.append({
        "timestamp": datetime.now().isoformat(),
        "type": feedback_type,
        "content": feedback_text,
    })

    log_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def append_to_yaml_list(file_path: Path, new_item: str) -> bool:
    items: List[str] = []
    if file_path.is_file():
        try:
            loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                items = [str(x) for x in loaded]
        except Exception:
            pass

    if new_item in items:
        return False  # Already present

    items.append(new_item)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(yaml.safe_dump(items, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return True


def patch_skill_markdown(
    skill_md_path: Path,
    addition: str,
    target_section: str,
) -> bool:
    """Insert bullet item cleanly into the specified section of SKILL.md."""
    if not skill_md_path.is_file():
        return False

    content = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    if addition in content:
        return False

    # Regex search for target section header (supports common header variations)
    section_aliases = {
        "When to Use": r"When\s+to\s+Use|Triggers",
        "When NOT to Use": r"When\s+NOT\s+to\s+Use|Scope\s+Lock|Scope\s+Boundaries|Out\s+of\s+Scope",
        "Mental Models & Principles": r"Mental\s+Models\s*(?:&|and)?\s*Principles|Mental\s+Models|Principles",
    }
    pattern_label = section_aliases.get(target_section, re.escape(target_section))
    pattern = rf"(###?\s*(?:{pattern_label})\s*\n)"
    m = re.search(pattern, content, re.IGNORECASE)
    if not m:
        return False

    insert_pos = m.end()
    bullet_line = f"- {addition}\n"
    new_content = content[:insert_pos] + bullet_line + content[insert_pos:]
    skill_md_path.write_text(new_content, encoding="utf-8")
    return True


def extract_feedback_target(clean_fb: str) -> Tuple[str, str]:
    """
    Parse conversational user feedback into (clean_target_text, feedback_type).
    Handles quoted prompts like: Wrongly triggered on "how to bake bread".
    """
    fb_lower = clean_fb.lower()

    # 1. Determine type
    if any(w in fb_lower for w in ["didn't trigger", "failed to trigger", "should trigger", "missed trigger"]):
        fb_type = "missed_trigger"
    elif any(w in fb_lower for w in ["wrongly triggered", "false trigger", "should not trigger", "unrelated", "wrongly activated"]):
        fb_type = "false_trigger"
    else:
        fb_type = "rule_correction"

    # 2. Check if a quoted prompt is present (e.g. 'how to make coffee')
    quoted_m = re.search(r"['\"]([^'\"]{3,})['\"]", clean_fb)
    if quoted_m:
        return quoted_m.group(1).strip(), fb_type

    # 3. Strip conversational prefixes
    cleaned_target = re.sub(
        r"(?i)^(?:user\s+said\s*:?\s*|agent\s+)?(?:it\s+)?(?:failed\s+to\s+trigger|incorrectly\s+triggered|wrongly\s+triggered|should\s+not\s+trigger|should\s+trigger|user\s+correction|feedback)\s*(?:on|when\s+user\s+said|:)?\s*",
        "",
        clean_fb,
    ).strip().strip('"\'')

    return cleaned_target, fb_type


def improve_skill(
    skill_dir_path: str | Path,
    feedback: str,
    feedback_type: str = "auto",  # "auto", "missed_trigger", "false_trigger", "rule_correction"
) -> ImprovementResult:
    """
    Apply feedback or user correction to automatically improve the skill and its tests.
    """
    skill_dir = Path(skill_dir_path).resolve()
    skill_md = skill_dir / "SKILL.md"
    tests_dir = skill_dir / "tests"
    pos_file = tests_dir / "should_trigger.yaml"
    neg_file = tests_dir / "should_not_trigger.yaml"

    clean_fb = feedback.strip()
    extracted_target, auto_type = extract_feedback_target(clean_fb)

    effective_type = feedback_type if feedback_type != "auto" else auto_type
    cleaned_target = extracted_target

    added_pos = False
    added_neg = False
    added_md = False
    action_desc = ""

    if effective_type == "missed_trigger":
        added_pos = append_to_yaml_list(pos_file, cleaned_target)
        added_md = patch_skill_markdown(skill_md, cleaned_target, "When to Use")
        action_desc = f"Added '{cleaned_target}' to positive triggers and should_trigger.yaml"
    elif effective_type == "false_trigger":
        added_neg = append_to_yaml_list(neg_file, cleaned_target)
        added_md = patch_skill_markdown(skill_md, cleaned_target, "When NOT to Use")
        action_desc = f"Added '{cleaned_target}' to negative scope boundaries and should_not_trigger.yaml"
    else:  # rule_correction
        rule_text = f"**Learned Constraint**: {cleaned_target}"
        added_md = patch_skill_markdown(skill_md, rule_text, "Mental Models & Principles")
        action_desc = f"Recorded learned constraint into Mental Models: '{cleaned_target}'"

    record_feedback_entry(skill_dir, clean_fb, effective_type)

    # Re-validate and re-evaluate
    val_res = validate_skill_dir(skill_dir)
    eval_res = evaluate_triggers(skill_dir)

    return ImprovementResult(
        skill_dir=skill_dir,
        action_taken=action_desc,
        added_to_positive_tests=added_pos,
        added_to_negative_tests=added_neg,
        added_to_skill_md=added_md,
        validation=val_res,
        evaluation=eval_res,
    )
