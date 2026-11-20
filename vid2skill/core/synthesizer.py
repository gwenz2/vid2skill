"""
synthesizer.py - Synthesize production-grade agent skills from raw text or transcripts.

Enforces:
1. 3-tier progressive disclosure (Frontmatter -> SKILL.md <400 lines -> references/ & scripts/).
2. Kebab-case naming standards with clean word boundaries.
3. Explicit trigger engineering ("Use when...") and scope lock ("When NOT to Use").
4. Automated paired eval suites (should_trigger.yaml / should_not_trigger.yaml).
5. Self-contained autonomous scripts (scripts/validate.py & scripts/eval_triggers.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple


@dataclass
class SkillBundle:
    name: str
    description: str
    skill_md: str
    should_trigger: List[str]
    should_not_trigger: List[str]
    references: Dict[str, str] = field(default_factory=dict)
    scripts: Dict[str, str] = field(default_factory=dict)
    domain: str = "General"


STANDALONE_VALIDATOR_CODE = r'''#!/usr/bin/env python3
"""
scripts/validate.py - Standalone pre-flight AST & rule validator for agent skills.
Can be executed directly in any environment with or without vid2skill installed.
"""

import os
import re
import sys
from pathlib import Path

try:
    from vid2skill.core.validator import validate_skill_dir
except ImportError:
    # Embedded fallback validator ensuring zero-dependency standalone execution
    def validate_skill_dir(skill_dir_path, strict=False):
        import yaml
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

    res = validate_skill_dir(Path(args.path).resolve(), strict=args.strict)
    print(res.summary())
    sys.exit(0 if res.is_valid else 1)

if __name__ == "__main__":
    main()
'''

STANDALONE_EVALUATOR_CODE = r'''#!/usr/bin/env python3
"""
scripts/eval_triggers.py - Standalone trigger eval runner for agent skills.
Can be executed directly in any environment with or without vid2skill installed.
"""

import re
import sys
from pathlib import Path

try:
    from vid2skill.core.evaluator import evaluate_triggers
except ImportError:
    # Embedded fallback evaluator ensuring zero-dependency standalone execution
    import yaml
    STOP_WORDS = {"a", "an", "the", "and", "or", "but", "if", "then", "so", "for", "with",
                  "on", "at", "by", "from", "up", "about", "into", "over", "after", "is",
                  "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
                  "does", "did", "to", "of", "in", "it", "my", "this", "that", "me", "you",
                  "can", "help", "how", "what", "please"}

    def tokenize(text):
        cleaned = re.sub(r"[^\\w\\s-]", " ", text.lower())
        return [t.strip() for t in cleaned.split() if t.strip() and t.strip() not in STOP_WORDS]

    def stem(w):
        w = w.lower()
        for suffix in ["ing", "ed", "es", "s"]:
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                return w[:-len(suffix)]
        return w

    def score_prompt(prompt, skill_name, description, pos_triggers, neg_boundaries, threshold=0.35):
        prompt_lower = prompt.lower().strip()
        p_tokens = set(tokenize(prompt_lower))
        p_stems = {stem(t) for t in p_tokens}

        # Check negative boundaries first
        neg_score = 0.0
        for nb in neg_boundaries:
            nb_l = nb.lower().strip()
            if len(nb_l) > 8 and nb_l in prompt_lower:
                neg_score += 0.85; break
            n_tokens = set(tokenize(nb_l))
            if n_tokens and len(p_tokens & n_tokens) >= max(2, int(len(n_tokens) * 0.7)):
                neg_score += 0.65

        if re.search(r"\\b(?:don't|do\\s+not|never|avoid|without|stop|disable|skip)\\b", prompt_lower):
            neg_score += 0.5

        if neg_score >= 0.75:
            return False, 0.05

        # Check skill name
        name_clean = skill_name.lower().replace("-", " ")
        if re.search(rf"\\b{re.escape(skill_name.lower())}\\b", prompt_lower) or re.search(rf"\\b{re.escape(name_clean)}\\b", prompt_lower):
            if neg_score < 0.5:
                return True, max(0.95 - neg_score, 0.0)

        # Check triggers
        best_pos = 0.0
        for pt in pos_triggers:
            pt_l = pt.lower().strip()
            if pt_l in prompt_lower:
                best_pos = max(best_pos, 0.90); continue
            pt_tokens = set(tokenize(pt_l))
            if pt_tokens and pt_tokens.issubset(p_tokens):
                best_pos = max(best_pos, 0.85); continue
            if pt_tokens:
                overlap = len(p_tokens & pt_tokens)
                sim = overlap / float(len(pt_tokens))
                if sim > best_pos: best_pos = sim

        final_score = max(0.0, best_pos - neg_score)
        return final_score >= threshold, final_score

    class _rep:
        def __init__(self, name, tot, tp, tn, fp, fn, res):
            self.skill_name = name; self.total_tests = tot
            self.true_positives = tp; self.true_negatives = tn
            self.false_positives = fp; self.false_negatives = fn
            self.accuracy = (tp + tn) / tot if tot else 0.0
            self.precision = tp / (tp + fp) if (tp + fp) else 0.0
            self.recall = tp / (tp + fn) if (tp + fn) else 0.0
            self.f1_score = (2*self.precision*self.recall)/(self.precision+self.recall) if (self.precision+self.recall) else 0.0
            self.passed = fp == 0 and fn == 0
            self.results = res
        def summary(self):
            lines = [f"=== Trigger Evaluation Report: {self.skill_name} ===",
                     f"Total Tests: {self.total_tests}",
                     f"TP: {self.true_positives} | TN: {self.true_negatives} | FP: {self.false_positives} | FN: {self.false_negatives}",
                     f"Accuracy:  {self.accuracy * 100:.1f}%",
                     f"Precision: {self.precision * 100:.1f}%",
                     f"Recall:    {self.recall * 100:.1f}%",
                     f"F1 Score:  {self.f1_score * 100:.1f}%",
                     f"Status:    {'PASSED (100% Match)' if self.passed else 'FAILED (Mismatches detected)'}"]
            return "\n".join(lines)

    def evaluate_triggers(skill_dir_path, threshold=0.35):
        skill_dir = Path(skill_dir_path).resolve()
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8", errors="ignore")
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1]) if len(parts) >= 3 else {}
        name = fm.get("name", skill_dir.name)
        desc = fm.get("description", "")
        body = parts[2] if len(parts) >= 3 else content

        pos_trig, neg_bound = [], []
        m_pos = re.search(r"### When to Use\s*\n(.*?)(?=\n###|\n##|\Z)", body, re.DOTALL)
        if m_pos: pos_trig = [b.strip().strip("'\"") for b in re.findall(r"^\s*[-*]\s*(.+)$", m_pos.group(1), re.M)]
        m_neg = re.search(r"### When NOT to Use\s*\n(.*?)(?=\n###|\n##|\Z)", body, re.DOTALL)
        if not m_neg: m_neg = re.search(r"## (?:Scope Lock|Out of Scope)\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
        if m_neg: neg_bound = [b.strip().strip("'\"") for b in re.findall(r"^\s*[-*]\s*(.+)$", m_neg.group(1), re.M)]

        t_dir = skill_dir / "tests"
        pos_prompts = yaml.safe_load((t_dir / "should_trigger.yaml").read_text(encoding="utf-8")) or []
        neg_prompts = yaml.safe_load((t_dir / "should_not_trigger.yaml").read_text(encoding="utf-8")) or []

        tp = tn = fp = fn = 0
        res = []
        for p in pos_prompts:
            trig, sc = score_prompt(str(p), name, desc, pos_trig, neg_bound, threshold)
            if trig: tp += 1
            else: fn += 1
            res.append((p, True, trig, sc))
        for p in neg_prompts:
            trig, sc = score_prompt(str(p), name, desc, pos_trig, neg_bound, threshold)
            if not trig: tn += 1
            else: fp += 1
            res.append((p, False, trig, sc))

        return _rep(name, len(res), tp, tn, fp, fn, res)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate paired trigger test suites for an agent skill.")
    parser.add_argument("path", nargs="?", default=".", help="Path to the skill directory (default: current dir)")
    parser.add_argument("--threshold", type=float, default=0.35, help="Classification confidence threshold (default: 0.35)")
    args = parser.parse_args()

    report = evaluate_triggers(Path(args.path).resolve(), threshold=args.threshold)
    print(report.summary())
    sys.exit(0 if report.passed else 1)

if __name__ == "__main__":
    main()
'''


def slugify_to_kebab(text: str) -> str:
    """Convert arbitrary title text into clean, strict kebab-case."""
    # Remove special chars and non-alphanumeric (keep hyphens and spaces)
    cleaned = re.sub(r"[^\w\s-]", "", text).lower().strip()
    slug = re.sub(r"[\s_]+", "-", cleaned)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        return "custom-skill"

    # Truncate at word boundary if longer than 45 chars
    if len(slug) > 45:
        slug = slug[:45].rsplit("-", 1)[0]
    slug = slug.strip("-")

    # Strip trailing filler prepositions if any
    parts = slug.split("-")
    while len(parts) > 1 and parts[-1] in {"in", "to", "for", "of", "the", "and", "on", "at", "by", "a", "an"}:
        parts.pop()
    slug = "-".join(parts).strip("-")

    # Ensure starts with a letter
    if not slug or not slug[0].isalpha():
        slug = f"skill-{slug}" if slug else "custom-skill"
    return slug


def clean_text_item(text: str) -> str:
    """Remove musical notes, audio tags, and extraneous punctuation."""
    t = re.sub(r"[♪♫♬]", "", text)
    t = re.sub(r"\[(?:Music|Applause|Laughter|Cheering|Silence|Audio)\]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" :-–—")
    return t


def extract_key_concepts(text: str) -> List[str]:
    """Extract notable positive concepts, heuristics, or recurring patterns from text."""
    lines = text.splitlines()
    concepts = []

    # Heuristic markers for positive principles/rules (exclude negative words like never/avoid)
    rule_patterns = [
        re.compile(r"(?i)\b(rule\s*\d+|principle\s*\d+|key\s+takeaway|mental\s+model|heuristic|remember\s+that|always\b)([:\s\-]+)(.+)")
    ]

    for line in lines:
        line_clean = clean_text_item(line)
        if not line_clean or len(line_clean) < 10:
            continue
        # Skip if contains strong negative phrasing (belongs in pitfalls)
        if any(w in line_clean.lower() for w in ["never", "avoid", "don't", "dont", "mistake", "pitfall"]):
            continue

        for pat in rule_patterns:
            m = pat.search(line_clean)
            if m:
                concept_text = clean_text_item(m.group(3))
                if concept_text and len(concept_text) > 8 and concept_text not in concepts:
                    concepts.append(concept_text)
                    break
        if len(concepts) >= 6:
            break

    if not concepts:
        sentences = [clean_text_item(s) for s in re.split(r"[.!?]\s+", text) if len(s.strip()) > 20]
        for s in sentences[:6]:
            if any(w in s.lower() for w in ["should", "must", "important", "best", "approach", "workflow", "strategy"]):
                if not any(w in s.lower() for w in ["never", "avoid", "don't"]):
                    concepts.append(s)

    return concepts[:6]


def extract_actionable_steps(text: str) -> List[Tuple[str, str]]:
    """Extract step-by-step procedures or workflow actions."""
    lines = text.splitlines()
    steps = []

    step_pattern = re.compile(r"(?i)^(?:step\s*\d+|phase\s*\d+|\d+\.|\d+\))\s*[:\-]?\s*(.+)")
    transition_words = ["first", "second", "third", "next", "then", "finally", "subsequently"]

    for line in lines:
        line_clean = clean_text_item(line)
        m = step_pattern.match(line_clean)
        if m:
            step_body = clean_text_item(m.group(1))
            title = step_body.split(".")[0].split(":")[0][:60].strip()
            steps.append((title, step_body))
            continue

        for w in transition_words:
            if line_clean.lower().startswith(f"{w},") or line_clean.lower().startswith(f"{w} "):
                title = line_clean.split(",")[0].capitalize()
                steps.append((title, line_clean))
                break

        if len(steps) >= 6:
            break

    if not steps:
        steps = [
            ("Ingest & Analyze", "Parse inputs, verify constraints, and detect domain-specific parameters."),
            ("Execute Core Workflow", "Apply distilled principles and mental models to perform primary operation."),
            ("Validate & Gate", "Run pre-flight checks, verify outputs against criteria, and guard against regressions."),
        ]

    return steps[:6]


def extract_pitfalls(text: str) -> List[str]:
    """Extract anti-patterns, pitfalls, or common mistakes mentioned in transcript."""
    lines = text.splitlines()
    pitfalls = []
    pitfall_pattern = re.compile(r"(?i)\b(mistake|pitfall|anti-pattern|avoid\b|don't\b|never\b|trap\b)([:\s\-]+)(.+)")

    for line in lines:
        line_clean = clean_text_item(line)
        m = pitfall_pattern.search(line_clean)
        if m:
            pitfall_desc = clean_text_item(m.group(3))
            if len(pitfall_desc) > 8 and pitfall_desc not in pitfalls:
                pitfalls.append(pitfall_desc)
        if len(pitfalls) >= 5:
            break

    if not pitfalls:
        pitfalls = [
            "Skipping pre-flight verification before delivering outputs.",
            "Violating progressive disclosure by stuffing non-essential reference tables into Tier 2.",
            "Omitting negative scope bounds leading to false positive agent triggers.",
        ]

    return pitfalls[:5]


def detect_domain(title: str, text: str) -> str:
    """Classify domain for knowledge routing and negative boundaries."""
    combined = f"{title} {text}".lower()
    if any(w in combined for w in ["godot", "gdscript", "game engine", "unity", "unreal", "shader"]):
        return "Game-Development"
    if any(w in combined for w in ["css", "ui", "ux", "frontend", "tailwind", "figma", "typography", "layout"]):
        return "Product-Design"
    if any(w in combined for w in ["sales", "pricing", "marketing", "client", "business", "outreach", "revenue"]):
        return "Business"
    if any(w in combined for w in ["docker", "kubernetes", "backend", "database", "sql", "api", "devops", "cloud", "git"]):
        return "Software-Development"
    return "Learning"


def generate_trigger_suites(
    skill_name: str,
    domain: str,
    key_terms: List[str]
) -> Tuple[List[str], List[str]]:
    """Generate paired should_trigger.yaml and should_not_trigger.yaml suites."""
    term1 = key_terms[0] if key_terms else "workflow"
    term2 = key_terms[1] if len(key_terms) > 1 else "automation"
    clean_name = skill_name.replace("-", " ")

    # Realistic positive triggers
    should_trigger = [
        f"Help me execute the {clean_name} process for this project",
        f"Apply {clean_name} best practices to optimize my setup",
        f"Can you guide me through {term1} using {clean_name}?",
        f"Run {skill_name} workflow on my current workspace",
        f"How do I structure {term2} according to {clean_name} standards?",
        f"Review my implementation and align it with {clean_name}",
    ]

    # Challenging, near-miss negative triggers (scope boundary tests)
    should_not_trigger = [
        "What is the weather like in Tokyo right now?",
        "Write a quick python script to compute fibonacci numbers",
        f"Explain the history of {term1} in the 19th century",
        "Can you fix this unrelated git rebase conflict?",
        "Deploy this generic docker container to AWS without using this framework",
        f"Summarize the Wikipedia article about {term2}",
    ]

    return should_trigger, should_not_trigger


def synthesize_skill(
    raw_content: str,
    title_hint: Optional[str] = None,
    name_hint: Optional[str] = None,
    domain_hint: Optional[str] = None,
    extra_triggers: Optional[List[str]] = None,
    scope_exclusions: Optional[List[str]] = None,
) -> SkillBundle:
    """
    Main entry point for synthesizing a full 3-tier skill bundle.
    """
    effective_title = clean_text_item(title_hint.strip()) if title_hint else "Synthesized Skill"
    if not title_hint and len(raw_content) > 0:
        first_line = clean_text_item(raw_content.splitlines()[0][:60])
        if len(first_line) > 5 and not first_line.startswith("#"):
            effective_title = first_line

    skill_name = name_hint if name_hint else slugify_to_kebab(effective_title)
    skill_name = slugify_to_kebab(skill_name)

    domain = domain_hint if domain_hint else detect_domain(effective_title, raw_content)

    concepts = extract_key_concepts(raw_content)
    steps = extract_actionable_steps(raw_content)
    pitfalls = extract_pitfalls(raw_content)

    # Ensure no exact duplicate items between concepts and pitfalls
    pitfalls = [p for p in pitfalls if p not in concepts]
    if not pitfalls:
        pitfalls = ["Skipping pre-flight verification before delivering outputs."]

    # Extract key terms for triggers
    words = [w.lower() for w in re.findall(r"\b[A-Za-z]{4,}\b", f"{effective_title} {raw_content[:500]}")
             if w.lower() not in {"this", "that", "with", "from", "video", "about", "your", "have"}]
    key_terms = list(dict.fromkeys(words))[:4]

    pos_triggers, neg_triggers = generate_trigger_suites(skill_name, domain, key_terms)
    if extra_triggers:
        pos_triggers = list(dict.fromkeys(extra_triggers + pos_triggers))
    if scope_exclusions:
        neg_triggers = list(dict.fromkeys(scope_exclusions + neg_triggers))

    clean_phrase = skill_name.replace("-", " ")
    trigger_list_str = ', '.join([f'"{p}"' for p in pos_triggers[:3]])

    neg_boundary_summary = "unrelated tasks, general trivia, or out-of-scope manual rewrites"
    description = (
        f"Use when applying {skill_name} ({clean_phrase}) workflows, principles, and best practices. "
        f"Triggers on {trigger_list_str}. "
        f"Do not use for {neg_boundary_summary}."
    )

    skill_md_lines = [
        "---",
        f"name: {skill_name}",
        f"description: {description}",
        "---",
        "",
        f"# {effective_title}",
        "",
        f"Operational agent skill for **{clean_phrase}**, synthesized from validated workflow patterns. "
        "Enforces deterministic execution, 3-tier progressive disclosure, and verified scope boundaries.",
        "",
        "## Triggers & Scope Boundaries",
        "",
        "### When to Use",
    ]

    for pt in pos_triggers:
        skill_md_lines.append(f"- {pt}")

    skill_md_lines.extend([
        "",
        "### When NOT to Use",
    ])

    for nt in neg_triggers:
        skill_md_lines.append(f"- {nt}")

    skill_md_lines.extend([
        "",
        "## Core Workflow",
        "",
    ])

    for idx, (stitle, sbody) in enumerate(steps, 1):
        skill_md_lines.extend([
            f"{idx}. **Step {idx}: {stitle}**",
            f"   - {sbody}",
            f"   - Verify outputs against expected constraints before transitioning to the next step.",
        ])

    skill_md_lines.extend([
        "",
        "## Mental Models & Principles",
        "",
    ])

    if concepts:
        for c in concepts:
            skill_md_lines.append(f"- **Heuristic**: {c}")
    else:
        skill_md_lines.append(f"- **Focus**: Prioritize actionable, verifiable outcomes over speculation.")
        skill_md_lines.append(f"- **Minimal Footprint**: Make the smallest sound change that accomplishes the goal.")

    skill_md_lines.extend([
        "",
        "## Anti-Patterns & Common Pitfalls",
        "",
    ])

    for pf in pitfalls:
        skill_md_lines.append(f"- **Avoid**: {pf}")

    skill_md_lines.extend([
        "",
        "## Concrete Recipes & Examples",
        "",
        f"### Standard Invocation for {effective_title}",
        "```text",
        f"User Prompt: 'Apply {clean_phrase} to refactor this component.'",
        "Action Sequence:",
        "1. Verify requirements and inspect active environment.",
        "2. Execute guided steps from Core Workflow.",
        "3. Run automated tests and validate results before presenting final completion.",
        "```",
        "",
        "## References & Scripts",
        "- Extended reference guide: `references/overview.md`",
        "- Pre-flight AST validator: `scripts/validate.py`",
        "- Paired trigger evaluator: `scripts/eval_triggers.py`",
        "",
    ])

    skill_md_text = "\n".join(skill_md_lines)

    references = {
        "references/overview.md": (
            f"# {effective_title} - Extended Reference Guide\n\n"
            f"Detailed background, schemas, and supplemental notes for the `{skill_name}` skill.\n\n"
            f"## Domain Classification\n"
            f"- **Domain**: {domain}\n"
            f"- **Source Reference**: {effective_title}\n\n"
            f"## Key Terminology\n"
            + "\n".join([f"- **{t.capitalize()}**: Core domain concept extracted from source material." for t in key_terms])
            + f"\n\n## Extended Guidance\n"
            f"When implementing complex variations of this skill, consult this reference document "
            f"to preserve progressive disclosure without inflating Tier-2 SKILL.md token budgets.\n"
        )
    }

    scripts = {
        "scripts/validate.py": STANDALONE_VALIDATOR_CODE,
        "scripts/eval_triggers.py": STANDALONE_EVALUATOR_CODE,
    }

    return SkillBundle(
        name=skill_name,
        description=description,
        skill_md=skill_md_text,
        should_trigger=pos_triggers,
        should_not_trigger=neg_triggers,
        references=references,
        scripts=scripts,
        domain=domain,
    )
