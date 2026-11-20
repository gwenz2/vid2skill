#!/usr/bin/env python3
"""
scripts/extract_transcript.py - Standalone extract_transcript.py script.
Can be executed directly in any environment.
Usage:
    python scripts/extract_transcript.py <url_or_file> [-o <out_file>] [--lang en]
"""

import sys
import os
from pathlib import Path

# Ensure UTF-8 output on Windows consoles to prevent cp1252 charmap encoding errors
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add parent directory to sys.path to allow importing vid2skill
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from vid2skill.core.extractor import extract_content, ExtractorError

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract clean text transcript from YouTube URL or media file.")
    parser.add_argument("source", help="YouTube URL, local video/audio, or text file")
    parser.add_argument("--out", "-o", help="Optional output text file path")
    parser.add_argument("--lang", default="en", help="Subtitle language for YouTube videos (default: en)")
    args = parser.parse_args()

    try:
        res = extract_content(args.source, lang=args.lang)
    except ExtractorError as e:
        print(f"Extraction error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        out_p = Path(args.out).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(res.text, encoding="utf-8")
        print(f"Extracted transcript saved to: {out_p}")
    else:
        print(res.text)

if __name__ == "__main__":
    main()
