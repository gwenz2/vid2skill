"""
cli.py - Main CLI entrypoint for vid2skill.

Commands:
- vid2skill create: Synthesize a 3-tier skill from video, audio, text, or URL
- vid2skill validate: Pre-flight AST & rule-based linter for skill directory
- vid2skill eval: Run paired trigger test evaluation (should_trigger & should_not_trigger)
- vid2skill extract: Fast transcript extractor via yt-dlp/youtube-transcript-api/ffmpeg
- vid2skill improve: Record telemetry/corrections and auto-evolve skill & test suites
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows consoles to prevent cp1252 charmap encoding errors
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

from .core.extractor import extract_content, ExtractorError
from .core.synthesizer import synthesize_skill
from .core.validator import validate_skill_dir
from .core.evaluator import evaluate_triggers
from .core.improver import improve_skill
from .exporters.standalone import export_standalone_skill


def print_msg(msg: str, style: str = ""):
    if HAS_RICH and console:
        console.print(msg, style=style)
    else:
        print(msg)


def print_error(msg: str):
    if HAS_RICH and console:
        console.print(f"[bold red]ERROR:[/bold red] {msg}")
    else:
        print(f"ERROR: {msg}", file=sys.stderr)


def print_success(msg: str):
    if HAS_RICH and console:
        console.print(f"[bold green]SUCCESS:[/bold green] {msg}")
    else:
        print(f"SUCCESS: {msg}")


@click.group()
@click.version_option(version="1.0.0", prog_name="vid2skill")
def main():
    """Universal agent skill synthesizer and validation toolkit."""
    pass


@main.command(name="create")
@click.option("--input", "-i", "source", required=True, help="YouTube URL, local video/audio, text file, web URL, or text prompt.")
@click.option("--out", "-o", default="./skills", help="Output directory to scaffold the skill package.")
@click.option("--name", "-n", default=None, help="Explicit kebab-case skill name.")
@click.option("--title", "-t", default=None, help="Human-readable skill title.")
@click.option("--domain", "-d", default=None, help="Domain classification (Business, Product-Design, etc.).")
@click.option("--lang", default="en", help="Subtitle language for YouTube extraction (default: en).")
@click.option("--no-validate", is_flag=True, help="Skip automated pre-flight validation.")
@click.option("--no-eval", is_flag=True, help="Skip automated paired trigger evaluation.")
def create_cmd(source, out, name, title, domain, lang, no_validate, no_eval):
    """Synthesize a complete agent skill package from media or text."""
    print_msg(f"[*] Ingesting content from: {source}...")
    try:
        content = extract_content(source, lang=lang)
    except ExtractorError as e:
        print_error(f"Extraction failed: {e}")
        sys.exit(1)

    print_msg(f"[*] Content extracted: {len(content.text)} characters from '{content.title}' ({content.source_type}).")
    print_msg("[*] Synthesizing 3-tier skill package and paired evals...")

    effective_title = title or content.title
    bundle = synthesize_skill(
        raw_content=content.text,
        title_hint=effective_title,
        name_hint=name,
        domain_hint=domain,
    )

    out_path = Path(out).resolve()
    skill_dir = export_standalone_skill(bundle, out_path)
    print_success(f"Skill package created at: {skill_dir}")

    # Run automated validation
    if not no_validate:
        print_msg("[*] Running pre-flight AST validation...")
        val_res = validate_skill_dir(skill_dir)
        if not val_res.is_valid:
            print_error("Skill validation failed:")
            for err in val_res.errors:
                print_msg(f"  - {err}", style="red")
            sys.exit(1)
        else:
            print_success(f"Validation passed ({val_res.line_count}/400 lines budget).")

    # Run automated trigger eval
    if not no_eval:
        print_msg("[*] Running paired trigger evaluation (should_trigger & should_not_trigger)...")
        eval_res = evaluate_triggers(skill_dir)
        if HAS_RICH and console:
            table = Table(title=f"Trigger Evaluation: {bundle.name}")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="magenta")
            table.add_row("Total Tests", str(eval_res.total_tests))
            table.add_row("Accuracy", f"{eval_res.accuracy * 100:.1f}%")
            table.add_row("Precision", f"{eval_res.precision * 100:.1f}%")
            table.add_row("Recall", f"{eval_res.recall * 100:.1f}%")
            table.add_row("F1 Score", f"{eval_res.f1_score * 100:.1f}%")
            console.print(table)
        else:
            print_msg(eval_res.summary())

        if not eval_res.passed:
            print_msg("[!] Warning: Some trigger tests did not achieve 100% match.", style="yellow")


@main.command(name="validate")
@click.argument("path", default=".")
@click.option("--strict", is_flag=True, help="Treat line count budget warnings (>400 lines) as hard errors.")
def validate_cmd(path, strict):
    """Run strict pre-flight validation on an agent skill directory."""
    target = Path(path).resolve()
    res = validate_skill_dir(target, strict=strict)

    if HAS_RICH and console:
        panel_color = "green" if res.is_valid else "red"
        status_text = "PASSED" if res.is_valid else "FAILED"
        content = (
            f"[bold]Status:[/bold] {status_text}\n"
            f"[bold]Path:[/bold] {target}\n"
            f"[bold]Line Count:[/bold] {res.line_count}/400 lines\n"
            f"[bold]Positive Tests:[/bold] {res.test_count_positive}\n"
            f"[bold]Negative Tests:[/bold] {res.test_count_negative}"
        )
        console.print(Panel(content, title="vid2skill Linter", border_style=panel_color))
    else:
        print(res.summary())

    if res.warnings:
        print_msg("\nWarnings:", style="yellow")
        for w in res.warnings:
            print_msg(f"  [!] {w}", style="yellow")

    if res.errors:
        print_msg("\nErrors:", style="red")
        for e in res.errors:
            print_msg(f"  [X] {e}", style="red")
        sys.exit(1)
    else:
        print_success("Skill passed all validation gates.")


@main.command(name="eval")
@click.argument("path", default=".")
@click.option("--threshold", default=0.35, type=float, help="Trigger classification confidence threshold.")
def eval_cmd(path, threshold):
    """Evaluate paired trigger suites against skill description and boundaries."""
    target = Path(path).resolve()
    try:
        report = evaluate_triggers(target, threshold=threshold)
    except Exception as e:
        print_error(f"Failed to run evaluation: {e}")
        sys.exit(1)

    if HAS_RICH and console:
        table = Table(title=f"Trigger Evaluation: {report.skill_name}")
        table.add_column("Prompt", style="white", max_width=50)
        table.add_column("Expected", style="cyan")
        table.add_column("Actual", style="magenta")
        table.add_column("Score", style="yellow")
        table.add_column("Result", style="bold")

        for r in report.results:
            exp = "TRIGGER" if r.expected_trigger else "SKIP"
            act = "TRIGGER" if r.actual_trigger else "SKIP"
            res_str = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
            table.add_row(r.prompt, exp, act, f"{r.score:.2f}", res_str)

        console.print(table)
        print_msg(f"\nAccuracy: {report.accuracy*100:.1f}% | Precision: {report.precision*100:.1f}% | Recall: {report.recall*100:.1f}% | F1: {report.f1_score*100:.1f}%")
    else:
        print(report.summary())

    if not report.passed:
        sys.exit(1)
    else:
        print_success("All trigger evaluation test cases passed.")


@main.command(name="extract")
@click.argument("source")
@click.option("--out", "-o", default=None, help="Output file path for clean text.")
@click.option("--lang", default="en", help="Subtitle language for YouTube videos (default: en).")
def extract_cmd(source, out, lang):
    """Fast subtitle and transcript extractor for YouTube or local files."""
    try:
        res = extract_content(source, lang=lang)
    except ExtractorError as e:
        print_error(f"Extraction failed: {e}")
        sys.exit(1)

    if out:
        out_p = Path(out).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(res.text, encoding="utf-8")
        print_success(f"Extracted {len(res.text)} characters to {out_p}")
    else:
        print_msg(res.text)


@main.command(name="improve")
@click.argument("path", default=".")
@click.option("--feedback", "-f", required=True, help="User correction, missed trigger, or learned constraint.")
@click.option("--type", "fb_type", default="auto", type=click.Choice(["auto", "missed_trigger", "false_trigger", "rule_correction"]), help="Feedback category.")
def improve_cmd(path, feedback, fb_type):
    """Feed real-world corrections back into skill & test suites."""
    target = Path(path).resolve()
    print_msg(f"[*] Applying continuous improvement feedback to: {target.name}...")

    try:
        result = improve_skill(target, feedback=feedback, feedback_type=fb_type)
    except Exception as e:
        print_error(f"Failed to improve skill: {e}")
        sys.exit(1)

    print_success(f"Improvement applied: {result.action_taken}")
    print_msg(f" - Added to positive tests: {result.added_to_positive_tests}")
    print_msg(f" - Added to negative tests: {result.added_to_negative_tests}")
    print_msg(f" - Updated SKILL.md: {result.added_to_skill_md}")

    if not result.validation.is_valid:
        print_msg("[!] Warning: Validation issues detected after update:", style="yellow")
        for err in result.validation.errors:
            print_msg(f"  - {err}", style="red")
    else:
        print_success(f"Validation verified ({result.validation.line_count}/400 lines).")

    print_msg(f"Trigger Eval Accuracy: {result.evaluation.accuracy*100:.1f}%")


if __name__ == "__main__":
    main()
