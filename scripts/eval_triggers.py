#!/usr/bin/env python3
"""
scripts/eval_triggers.py - Standalone trigger eval runner for agent skills.
Can be executed directly in any environment with or without vid2skill installed.
Usage:
    python scripts/eval_triggers.py <path_to_skill_folder> [--threshold 0.35]
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
    from vid2skill.core.evaluator import evaluate_triggers
except ImportError:
    import yaml
    STOP_WORDS = {"a", "an", "the", "and", "or", "but", "if", "then", "so", "for", "with",
                  "on", "at", "by", "from", "up", "about", "into", "over", "after", "is",
                  "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
                  "does", "did", "to", "of", "in", "it", "my", "this", "that", "me", "you",
                  "can", "help", "how", "what", "please"}

    def tokenize(text):
        cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
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

        if re.search(r"\b(?:don't|do\s+not|never|avoid|without|stop|disable|skip)\b", prompt_lower):
            neg_score += 0.5

        if neg_score >= 0.75:
            return False, 0.05

        # Check skill name
        name_clean = skill_name.lower().replace("-", " ")
        if re.search(rf"\b{re.escape(skill_name.lower())}\b", prompt_lower) or re.search(rf"\b{re.escape(name_clean)}\b", prompt_lower):
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

    target = Path(args.path).resolve()
    try:
        report = evaluate_triggers(target, threshold=args.threshold)
    except Exception as e:
        print(f"Error executing evaluation: {e}", file=sys.stderr)
        sys.exit(1)

    print(report.summary())
    sys.exit(0 if report.passed else 1)

if __name__ == "__main__":
    main()
