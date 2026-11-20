"""
evaluator.py - Local trigger eval runner for agent skills.

Evaluates tests/should_trigger.yaml and tests/should_not_trigger.yaml against
a skill's metadata, triggers, and negative boundaries.

Calculates:
- True Positives (TP), False Positives (FP)
- True Negatives (TN), False Negatives (FN)
- Accuracy, Precision, Recall, F1 Score
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import yaml


STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "for", "with",
    "on", "at", "by", "from", "up", "about", "into", "over", "after", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "to", "of", "in", "it", "my", "this", "that", "me", "you",
    "can", "help", "how", "what", "please"
}


@dataclass
class PromptEvalResult:
    prompt: str
    expected_trigger: bool
    actual_trigger: bool
    score: float
    passed: bool
    matched_clues: List[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    skill_name: str
    total_tests: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    results: List[PromptEvalResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.false_positives == 0 and self.false_negatives == 0

    def summary(self) -> str:
        lines = [
            f"=== Trigger Evaluation Report: {self.skill_name} ===",
            f"Total Tests: {self.total_tests}",
            f"TP: {self.true_positives} | TN: {self.true_negatives} | FP: {self.false_positives} | FN: {self.false_negatives}",
            f"Accuracy:  {self.accuracy * 100:.1f}%",
            f"Precision: {self.precision * 100:.1f}%",
            f"Recall:    {self.recall * 100:.1f}%",
            f"F1 Score:  {self.f1_score * 100:.1f}%",
            f"Status:    {'PASSED (100% Match)' if self.passed else 'FAILED (Mismatches detected)'}",
        ]
        if not self.passed:
            lines.append("\nFailures:")
            for r in self.results:
                if not r.passed:
                    kind = "False Positive" if r.actual_trigger else "False Negative"
                    lines.append(f"  [{kind}] Score: {r.score:.2f} | Prompt: \"{r.prompt}\"")
        return "\n".join(lines)


def stem(word: str) -> str:
    """Lightweight suffix normalizer for trigger token matching."""
    w = word.lower()
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


def tokenize(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
    tokens = [t.strip() for t in cleaned.split() if t.strip() and t.strip() not in STOP_WORDS]
    return tokens


def extract_skill_trigger_data(skill_dir: Path) -> Tuple[str, str, List[str], List[str]]:
    """Extract skill name, description, positive triggers, and negative boundaries."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"Missing SKILL.md in {skill_dir}")

    content = skill_md.read_text(encoding="utf-8", errors="ignore")
    parts = content.split("---", 2)
    name = skill_dir.name
    description = ""

    if len(parts) >= 3:
        try:
            fm = yaml.safe_load(parts[1]) or {}
            name = fm.get("name", name)
            description = fm.get("description", "")
        except Exception:
            pass

    body = parts[2] if len(parts) >= 3 else content

    # Extract bullet points from When to Use
    pos_triggers: List[str] = []
    when_to_use_m = re.search(r"### When to Use\s*\n(.*?)(?=\n###|\n##|\Z)", body, re.DOTALL | re.IGNORECASE)
    if when_to_use_m:
        bullets = re.findall(r"^\s*[-*]\s*(.+)$", when_to_use_m.group(1), re.MULTILINE)
        pos_triggers.extend([b.strip().strip('"\'') for b in bullets if b.strip()])

    # Also extract explicit trigger phrases from description (e.g. quoted phrases)
    if description:
        quoted = re.findall(r'["\']([^"\']+)["\']', description)
        pos_triggers.extend([q.strip() for q in quoted if q.strip()])

    # Extract bullet points from When NOT to Use / Scope Lock
    neg_boundaries: List[str] = []
    when_not_m = re.search(r"### When NOT to Use\s*\n(.*?)(?=\n###|\n##|\Z)", body, re.DOTALL | re.IGNORECASE)
    if not when_not_m:
        when_not_m = re.search(r"## (?:Scope Lock|Out of Scope|Scope Boundaries)\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL | re.IGNORECASE)
    if when_not_m:
        bullets = re.findall(r"^\s*[-*]\s*(.+)$", when_not_m.group(1), re.MULTILINE)
        neg_boundaries.extend([b.strip().strip('"\'') for b in bullets if b.strip()])

    return str(name), str(description), pos_triggers, neg_boundaries


def score_prompt(
    prompt: str,
    skill_name: str,
    description: str,
    pos_triggers: List[str],
    neg_boundaries: List[str],
    threshold: float = 0.35,
) -> Tuple[bool, float, List[str]]:
    """
    Score whether a user prompt should trigger the skill.
    Returns (should_trigger, confidence_score, matched_clues).
    Ensures negative boundaries and explicit negation suppress false triggers.
    """
    prompt_lower = prompt.lower().strip()
    prompt_tokens = set(tokenize(prompt_lower))
    prompt_stems = {stem(t) for t in prompt_tokens}
    matched_clues: List[str] = []

    # 1. Evaluate negative boundaries (suppressors) FIRST
    negative_score = 0.0
    for nb in neg_boundaries:
        nb_clean = nb.lower().strip()
        if not nb_clean:
            continue
        # Exact substring match on meaningful negative boundary
        if len(nb_clean) > 8 and nb_clean in prompt_lower:
            negative_score += 0.85
            matched_clues.append(f"negative boundary exact match: '{nb_clean}'")
            break

        nb_tokens = set(tokenize(nb_clean))
        nb_stems = {stem(t) for t in nb_tokens}
        if nb_tokens and len(prompt_tokens & nb_tokens) >= max(2, int(len(nb_tokens) * 0.7)):
            negative_score += 0.65
            matched_clues.append(f"negative boundary token overlap: '{nb_clean}'")
        elif nb_stems and len(prompt_stems & nb_stems) >= max(2, int(len(nb_stems) * 0.7)):
            negative_score += 0.55
            matched_clues.append(f"negative boundary stem overlap: '{nb_clean}'")

    # Detect explicit negation phrases directed at the skill or action
    negation_regex = re.compile(
        r"\b(?:don't|do\s+not|never|avoid|without|stop|disable|skip|exclude)\s+(?:use|using|run|running|apply|applying|trigger|triggering)?\b",
        re.IGNORECASE,
    )
    if negation_regex.search(prompt_lower):
        negative_score += 0.5
        matched_clues.append("explicit negation phrase detected")

    # If strongly matched against negative boundaries, immediately reject
    if negative_score >= 0.75:
        return False, 0.05, matched_clues

    # 2. Check skill name match using whole-word boundary
    name_clean = skill_name.lower().replace("-", " ")
    name_pattern = rf"\b{re.escape(skill_name.lower())}\b"
    clean_name_pattern = rf"\b{re.escape(name_clean)}\b"

    name_matched = bool(re.search(name_pattern, prompt_lower) or re.search(clean_name_pattern, prompt_lower))
    if name_matched:
        matched_clues.append(f"skill name '{skill_name}' match")
        effective_name_score = max(0.95 - negative_score, 0.0)
        if effective_name_score >= threshold and negative_score < 0.5:
            return True, effective_name_score, matched_clues

    # 3. Check positive triggers
    best_pos_score = 0.0
    for pt in pos_triggers:
        pt_clean = pt.lower().strip()
        # Exact substring match
        if pt_clean in prompt_lower:
            best_pos_score = max(best_pos_score, 0.90)
            matched_clues.append(f"exact trigger match: '{pt}'")
            continue

        pt_tokens = set(tokenize(pt_clean))
        if not pt_tokens:
            continue

        pt_stems = {stem(t) for t in pt_tokens}

        # Subphrase / token subset containment
        if pt_tokens.issubset(prompt_tokens) or (len(pt_stems) >= 2 and pt_stems.issubset(prompt_stems)):
            best_pos_score = max(best_pos_score, 0.85)
            matched_clues.append(f"trigger token containment: '{pt}'")
            continue

        overlap = len(prompt_tokens & pt_tokens)
        stem_overlap = len(prompt_stems & pt_stems)
        effective_overlap = max(float(overlap), stem_overlap * 0.9)

        jaccard = effective_overlap / float(len(prompt_tokens | pt_tokens))
        containment = effective_overlap / float(len(pt_tokens))

        combined_sim = (jaccard * 0.4) + (containment * 0.6)
        if combined_sim > best_pos_score:
            best_pos_score = combined_sim

    # 4. Description token & stem overlap
    desc_tokens = set(tokenize(description))
    if desc_tokens:
        desc_stems = {stem(t) for t in desc_tokens}
        desc_overlap = len(prompt_tokens & desc_tokens)
        desc_stem_overlap = len(prompt_stems & desc_stems)
        eff_desc_overlap = max(float(desc_overlap), desc_stem_overlap * 0.9)
        desc_containment = eff_desc_overlap / float(len(prompt_tokens)) if prompt_tokens else 0.0
        if desc_containment > 0.35:
            best_pos_score = max(best_pos_score, desc_containment * 0.75)

    # 5. Apply negative suppression penalty
    final_score = max(0.0, best_pos_score - negative_score)
    triggered = final_score >= threshold
    return triggered, final_score, matched_clues


def evaluate_triggers(
    skill_dir_path: str | Path,
    threshold: float = 0.35,
) -> EvaluationReport:
    """Run full eval against should_trigger.yaml and should_not_trigger.yaml."""
    skill_dir = Path(skill_dir_path).resolve()
    name, description, pos_triggers, neg_boundaries = extract_skill_trigger_data(skill_dir)

    tests_dir = skill_dir / "tests"
    pos_file = tests_dir / "should_trigger.yaml"
    neg_file = tests_dir / "should_not_trigger.yaml"

    pos_prompts: List[str] = []
    neg_prompts: List[str] = []

    if pos_file.is_file():
        data = yaml.safe_load(pos_file.read_text(encoding="utf-8")) or []
        if isinstance(data, list):
            pos_prompts = [str(x) for x in data]

    if neg_file.is_file():
        data = yaml.safe_load(neg_file.read_text(encoding="utf-8")) or []
        if isinstance(data, list):
            neg_prompts = [str(x) for x in data]

    results: List[PromptEvalResult] = []
    tp = 0
    tn = 0
    fp = 0
    fn = 0

    # Evaluate positive suite
    for p in pos_prompts:
        triggered, score, clues = score_prompt(
            p, name, description, pos_triggers, neg_boundaries, threshold=threshold
        )
        passed = triggered is True
        if passed:
            tp += 1
        else:
            fn += 1
        results.append(
            PromptEvalResult(
                prompt=p,
                expected_trigger=True,
                actual_trigger=triggered,
                score=score,
                passed=passed,
                matched_clues=clues,
            )
        )

    # Evaluate negative suite
    for p in neg_prompts:
        triggered, score, clues = score_prompt(
            p, name, description, pos_triggers, neg_boundaries, threshold=threshold
        )
        passed = triggered is False
        if passed:
            tn += 1
        else:
            fp += 1
        results.append(
            PromptEvalResult(
                prompt=p,
                expected_trigger=False,
                actual_trigger=triggered,
                score=score,
                passed=passed,
                matched_clues=clues,
            )
        )

    total = len(results)
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return EvaluationReport(
        skill_name=name,
        total_tests=total,
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1_score=f1,
        results=results,
    )
