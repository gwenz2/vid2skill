"""
standalone.py - Package a SkillBundle into a standalone, universal agent skill folder.
Compatible with Antigravity, Claude Code, Cursor, Codex, and standard agents.
"""

from __future__ import annotations

import os
from pathlib import Path
import yaml

from ..core.synthesizer import SkillBundle


def _safe_child_path(parent: Path, rel: str) -> Path:
    """Resolve child path and ensure it stays strictly inside parent."""
    resolved = (parent / rel).resolve()
    if not resolved.is_relative_to(parent.resolve()):
        raise ValueError(f"Unsafe path escapes target directory: {rel!r}")
    return resolved


def export_standalone_skill(bundle: SkillBundle, target_dir: str | Path) -> Path:
    """
    Write out the standalone skill directory:
    <target_dir>/<bundle.name>/
      ├── SKILL.md
      ├── tests/
      │   ├── should_trigger.yaml
      │   └── should_not_trigger.yaml
      ├── references/
      │   └── ...
      └── scripts/
          └── ...
    """
    base_dir = Path(target_dir).resolve()
    skill_dir = _safe_child_path(base_dir, bundle.name)
    skill_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write SKILL.md
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(bundle.skill_md, encoding="utf-8")

    # 2. Write tests
    tests_dir = skill_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    pos_file = tests_dir / "should_trigger.yaml"
    neg_file = tests_dir / "should_not_trigger.yaml"

    pos_file.write_text(
        yaml.safe_dump(bundle.should_trigger, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    neg_file.write_text(
        yaml.safe_dump(bundle.should_not_trigger, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # 3. Write references
    if bundle.references:
        for rel_path, content in bundle.references.items():
            ref_file = _safe_child_path(skill_dir, rel_path)
            ref_file.parent.mkdir(parents=True, exist_ok=True)
            ref_file.write_text(content, encoding="utf-8")

    # 4. Write scripts
    if bundle.scripts:
        for rel_path, content in bundle.scripts.items():
            script_file = _safe_child_path(skill_dir, rel_path)
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text(content, encoding="utf-8")

    return skill_dir
