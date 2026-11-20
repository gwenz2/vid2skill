<div align="center">

<img src="assets/logo.svg" alt="vid2skill logo" width="96" height="96" />

# vid2skill

**Convert YouTube videos, audio, and text into validated `SKILL.md` agent packages.**

Built for Claude Code, Antigravity, Cursor, and Codex with `<400`-line progressive disclosure, paired YAML trigger tests, and a local AST validator.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Agent: Universal](https://img.shields.io/badge/agents-Antigravity%20%7C%20Claude%20%7C%20Cursor%20%7C%20Codex-success.svg)](#)

</div>

---

## Why vid2skill?

`vid2skill` combines media ingestion, strict validation, and automated trigger testing into a single universal CLI:

| Capability | Manual Guides | Prompt-Only Creators | Single-File Skills | **vid2skill** |
| :--- | :---: | :---: | :---: | :---: |
| **Media & Video Ingestion** | Manual writing | Prompt input | Chat text only | **<3s subtitles/transcript via `yt-dlp` & `ffmpeg`** |
| **Progressive Disclosure** | 3-Tier concepts | Line count check | Single flat file | **<400-line `SKILL.md`, auto-split `references/`** |
| **Trigger Verification** | Guide only | Paired YAML tests | No automated tests | **Auto-generated YAML suites + local evaluator** |
| **Linter / Pre-flight AST** | None | Basic syntax check | None | **AST validator (casing, links, scope lock)** |
| **Continuous Learning** | None | None | Passive observation | **`vid2skill improve` CLI updates tests & rules** |
| **Universal Portability** | Claude Code | Claude Code | Single platform | **Claude, Antigravity, Cursor, Codex** |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/gwenz2/vid2skill.git
cd vid2skill

# Install editable package
pip install -e .

# Verify installation
vid2skill --help
```

### Prerequisites
- Python 3.10+
- `yt-dlp` (for YouTube subtitle extraction without downloading video files)
- `ffmpeg` (optional, for extracting embedded subtitles from local MP4/MKV files)

---

## CLI Quickstart

### 1. Synthesize a Skill from YouTube or Video
Ingest a YouTube video in < 3 seconds without downloading video bytes:
```bash
vid2skill create --input "https://www.youtube.com/watch?v=VIDEO_ID" --out ./skills
```

Or synthesize from a local transcript, text file, or prompt:
```bash
vid2skill create \
  --input "Step 1: Parse telemetry. Step 2: Compute p99. Step 3: Trigger pager." \
  --name "latency-monitor" \
  --title "Latency Monitoring Workflow" \
  --out ./skills \
  --domain "Software-Development"
```

---

### 2. Validate Pre-Flight AST & Scope Lock
Run strict validation checks on any agent skill folder:
```bash
vid2skill validate ./skills/latency-monitor
```

**Checks Enforced:**
1. **File Casing**: Strict uppercase `SKILL.md` (cross-platform filesystem check).
2. **Kebab-Case Naming**: Regex `^[a-z0-9]+(-[a-z0-9]+)*$` on directory and frontmatter `name`.
3. **Trigger-Rich Frontmatter**: Verifies `name`, `description` with `Use when...`, trigger phrases, and negative boundaries.
4. **Line Count Budget**: Verifies `SKILL.md` stays within the progressive disclosure limit (< 400 lines).
5. **Scope Lock**: Demands an explicit `### When NOT to Use` or `## Scope Lock` section.
6. **Link Integrity & Containment**: Verifies all internal markdown links exist and do not escape directory boundaries (`..` traversal).
7. **Paired Test Suites**: Verifies existence and formatting of `tests/should_trigger.yaml` and `tests/should_not_trigger.yaml`.

---

### 3. Run Paired Trigger Evaluations
Test whether an agent accurately activates or skips the skill:
```bash
vid2skill eval ./skills/latency-monitor
```

**Metrics Calculated:**
- True Positives (TP) & True Negatives (TN)
- False Positives (FP) & False Negatives (FN)
- Accuracy, Precision, Recall, and F1 Score

---

### 4. Continuous Self-Improvement & Telemetry
When an agent misses a trigger or wrongly activates, feed the correction directly:
```bash
# Auto-patch positive trigger suite and SKILL.md
vid2skill improve ./skills/latency-monitor \
  --feedback "Agent failed to trigger on 'investigate latency regressions'" \
  --type missed_trigger

# Auto-patch negative boundary suite and SKILL.md
vid2skill improve ./skills/latency-monitor \
  --feedback "Agent incorrectly triggered on 'explain history of fiber optics'" \
  --type false_trigger

# Record learned operational constraint
vid2skill improve ./skills/latency-monitor \
  --feedback "Always check Redis cluster health before restarting services" \
  --type rule_correction
```

---

### 5. Fast Subtitle & Transcript Extractor
```bash
vid2skill extract "https://youtu.be/EXAMPLE" -o transcript.txt
```

---

## Output Folder Structure

Every generated skill package is standalone and ready for installation into Claude Code, Antigravity, Cursor, or Codex:

```text
skills/my-awesome-skill/
├── SKILL.md                     # Tier 2: Core instructions (<400 lines) with frontmatter & scope lock
├── tests/
│   ├── should_trigger.yaml      # Paired eval: realistic positive activation prompts
│   └── should_not_trigger.yaml  # Paired eval: negative test prompts
├── references/                  # Tier 3: Deep documentation, schemas, and cheat sheets
│   └── overview.md
├── scripts/                     # Tier 3: Standalone validator & trigger evaluator
│   ├── validate.py
│   └── eval_triggers.py
└── history/                     # Created by `vid2skill improve`
    └── feedback_log.json
```

---

## Python API Usage

```python
from vid2skill import extract_content, synthesize_skill, validate_skill_dir, evaluate_triggers
from vid2skill.exporters import export_standalone_skill

# 1. Extract content from video URL or text
content = extract_content("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# 2. Synthesize 3-tier skill bundle
bundle = synthesize_skill(
    raw_content=content.text,
    title_hint=content.title,
    name_hint="video-insights",
)

# 3. Export standalone package
skill_dir = export_standalone_skill(bundle, target_dir="./skills")

# 4. Validate and test
validation = validate_skill_dir(skill_dir)
assert validation.is_valid

report = evaluate_triggers(skill_dir)
print(f"Trigger Accuracy: {report.accuracy * 100:.1f}%")
```

---

## Running Tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## FAQ

**How does `vid2skill` extract YouTube content without downloading video?**
It uses `yt-dlp` to fetch subtitles and transcripts directly, skipping video byte downloads.

**Which AI coding agents support `vid2skill` output?**
Generated skill folders follow the standard `SKILL.md` layout and work in Claude Code, Antigravity, Cursor, and Codex.

**Why enforce a 400-line limit on `SKILL.md`?**
Keeping `SKILL.md` under 400 lines preserves agent context window budget by moving deep docs into `references/` and `scripts/`.

---

## License

MIT © 2026 vid2skill contributors.
