"""
extractor.py - High-speed transcript & text extractor for vid2skill.

Supports:
- YouTube URLs via dual-engine extraction:
  1. Ultra-fast direct API via youtube-transcript-api (< 1s, zero download)
  2. Resilient CLI fallback via yt-dlp (--skip-download --sub-format vtt/srt/best)
  3. Instant title resolution via YouTube oEmbed API
- Local video & audio files (.mp4, .mkv, .mov, .webm, .avi, .mp3, .wav, .m4a, .aac, .flac, .ogg):
  - Automatic detection of companion subtitle/transcript files (.vtt, .srt, .txt)
  - Embedded subtitle extraction via ffmpeg
- Plain text / markdown files (.txt, .md)
- Web URLs (HTML article text)
- Subtitle cleaning:
  - Rolling subtitle deduplication (prefix accumulation and word overlap removal)
  - VTT/SRT timestamps and cue tag stripping
  - Audio/music cue removal ([Music], [Applause], ♪)
  - Sponsor & call-to-action filler stripping
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List


class ExtractorError(Exception):
    """Raised when extraction fails."""
    pass


FILLER_PATTERNS = [
    r"(?i)\b(please\s+)?(don't\s+forget\s+to\s+)?like\s+and\s+subscribe\b",
    r"(?i)\bhit\s+(that|the)\s+(bell|notification\s+bell|like\s+button)\b",
    r"(?i)\bleave\s+a\s+comment\s+down\s+below\b",
    r"(?i)\bthis\s+video\s+is\s+sponsored\s+by\b[^\.\n]*",
    r"(?i)\bsmash\s+that\s+like\s+button\b",
    r"(?i)\blink\s+in\s+the\s+description\b",
    r"(?i)\bwelcome\s+back\s+to\s+my\s+channel\b",
    r"\[(?:Music|Applause|Laughter|Cheering|Silence|Audio|Applause|Music\s+Playing)\]",
    r"\((?:Music|Applause|Laughter|Cheering)\)",
    r"[♪♫♬]+",
    r"^\s*\[[A-Za-z\s]+\]\s*$",
]


@dataclass
class ExtractedContent:
    source: str
    source_type: str  # "youtube", "local_media", "text_file", "web_url", "raw_text"
    title: str
    text: str
    language: str = "en"


def clean_vtt_or_srt(raw_text: str) -> str:
    """
    Clean WebVTT or SRT markup, timestamps, cue tags, and rolling duplicate lines.
    Handles progressive subtitle display and word-level rolling overlaps.
    """
    lines = raw_text.splitlines()
    cleaned: list[str] = []
    seen: set[str] = set()
    header_done = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if not header_done:
            if line == "WEBVTT" or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if line.startswith("NOTE"):
                continue
            header_done = True

        # Skip timestamp lines (e.g. 00:00:01.000 --> 00:00:03.000 or 00:01.000 --> 00:03.000)
        if "-->" in line:
            continue

        # Skip numeric cue identifiers
        if line.isdigit():
            continue

        # Strip inline HTML / VTT tags (e.g. <c.color>, <00:00:01.000>, <b>)
        line = re.sub(r"<[^>]+>", "", line).strip()

        # Decode common HTML entities
        line = (
            line.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )

        # Strip musical notes
        line = re.sub(r"[♪♫♬]", "", line).strip()

        if not line:
            continue

        if cleaned:
            # 1. Exact identical line
            if cleaned[-1] == line:
                continue

            # 2. Progressive prefix accumulation (current line starts with previous line)
            if line.startswith(cleaned[-1]):
                cleaned[-1] = line
                continue

            # 3. Previous line already contains current line as prefix
            if cleaned[-1].startswith(line):
                continue

            # 4. Word-level sliding overlap (e.g., auto-generated captions rolling words)
            prev_words = cleaned[-1].split()
            curr_words = line.split()
            max_k = min(len(prev_words), len(curr_words), 8)
            overlap_k = 0
            for k in range(max_k, 1, -1):
                if [w.lower() for w in prev_words[-k:]] == [w.lower() for w in curr_words[:k]]:
                    overlap_k = k
                    break

            if overlap_k > 0:
                # Merge current line by appending non-overlapping words
                remainder = curr_words[overlap_k:]
                if remainder:
                    cleaned[-1] = " ".join(prev_words + remainder)
                continue

            # 5. Short rolling buffer duplicate check
            if line in seen and line in cleaned[-3:]:
                continue

        cleaned.append(line)
        seen.add(line)
        if len(seen) > 100:
            seen.clear()

    return "\n".join(cleaned)


def strip_filler(text: str) -> str:
    """Strip common YouTube filler, music cues, sponsor intros, and call-to-actions."""
    for pattern in FILLER_PATTERNS:
        text = re.sub(pattern, "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_transcript(text: str) -> str:
    """Run full cleaning pipeline on raw transcript text."""
    vtt_cleaned = clean_vtt_or_srt(text)
    filtered = strip_filler(vtt_cleaned)
    return filtered


def normalize_source_url(source: str) -> str:
    """Ensure URLs have a proper scheme."""
    s = source.strip()
    if re.match(r"^(?:www\.)?(?:youtube\.com|youtu\.be)/", s, re.IGNORECASE):
        return f"https://{s}"
    if s.startswith("www."):
        return f"https://{s}"
    return s


def is_youtube_url(url: str) -> bool:
    """Check if URL points to YouTube."""
    norm = normalize_source_url(url)
    parsed = urllib.parse.urlparse(norm)
    netloc = parsed.netloc.lower()
    return "youtube.com" in netloc or "youtu.be" in netloc or "m.youtube.com" in netloc


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube 11-character video ID from varied URL formats."""
    norm = normalize_source_url(url)
    parsed = urllib.parse.urlparse(norm)
    netloc = parsed.netloc.lower()

    if "youtu.be" in netloc:
        path = parsed.path.strip("/")
        return path.split("/")[0].split("?")[0] if path else None

    if "youtube.com" in netloc:
        if "/watch" in parsed.path:
            qs = urllib.parse.parse_qs(parsed.query)
            v_list = qs.get("v")
            if v_list:
                return v_list[0]
        for prefix in ["/shorts/", "/embed/", "/live/", "/v/"]:
            if prefix in parsed.path:
                part = parsed.path.split(prefix)[1]
                return part.split("/")[0].split("?")[0]

    return None


def fetch_youtube_title_oembed(url: str) -> Optional[str]:
    """Fetch official video title instantly (< 200ms) via YouTube oEmbed API."""
    try:
        norm = normalize_source_url(url)
        oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(norm)}&format=json"
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) vid2skill/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            title = data.get("title")
            return title.strip() if title else None
    except Exception:
        return None


def extract_youtube_api(video_id: str, lang: str = "en") -> Optional[str]:
    """Direct fast transcript extraction via youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        yt = YouTubeTranscriptApi()
        try:
            transcript = yt.fetch(video_id, languages=(lang, "en"))
        except Exception:
            try:
                transcript_list = yt.list(video_id)
                transcript = transcript_list.find_transcript([lang, "en", "en-US", "en-GB"])
                transcript = transcript.fetch()
            except Exception:
                return None

        raw_data = transcript.to_raw_data()
        lines = [snippet.get("text", "") for snippet in raw_data if snippet.get("text")]
        return "\n".join(lines)
    except Exception:
        return None


def extract_youtube_ytdlp(url: str, lang: str = "en") -> tuple[str, str]:
    """Extract YouTube transcript and title via yt-dlp CLI without downloading video stream."""
    if not shutil.which("yt-dlp"):
        raise ExtractorError("yt-dlp is not installed or not in PATH.")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "vid_sub")
        cmd = [
            "yt-dlp",
            "--write-sub",
            "--write-auto-sub",
            "--sub-lang", lang,
            "--sub-format", "vtt/srt/best",
            "--skip-download",
            "--print", "title",
            "-o", out_template,
            "--",
            url,
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
                timeout=60,
            )
        except Exception as e:
            raise ExtractorError(f"Failed to invoke yt-dlp: {e}") from e

        video_title = "Untitled Video"
        if res.stdout:
            stdout_lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            if stdout_lines:
                video_title = stdout_lines[0]

        sub_files = list(Path(tmpdir).glob("vid_sub*.*"))
        # If preferred language sub not found, retry without strict sub-lang constraint
        if not sub_files:
            cmd_fallback = [
                "yt-dlp",
                "--write-sub",
                "--write-auto-sub",
                "--skip-download",
                "-o", out_template,
                "--",
                url,
            ]
            try:
                subprocess.run(
                    cmd_fallback,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                    timeout=60,
                )
            except Exception as e:
                raise ExtractorError(f"Failed to invoke yt-dlp fallback: {e}") from e
            sub_files = list(Path(tmpdir).glob("vid_sub*.*"))

        if not sub_files:
            err_msg = res.stderr or "No subtitles or captions found for this video."
            raise ExtractorError(f"Subtitle extraction failed: {err_msg.strip()}")

        # Pick the best subtitle file (prefer .vtt or .srt)
        chosen = sub_files[0]
        for f in sub_files:
            if f.suffix in [".vtt", ".srt"]:
                chosen = f
                break

        raw_sub = chosen.read_text(encoding="utf-8", errors="ignore")
        return raw_sub, video_title


def extract_youtube(url: str, lang: str = "en") -> ExtractedContent:
    """
    Extract subtitles from YouTube via dual-engine pipeline:
    1. youtube-transcript-api + oEmbed (< 1.5s, direct API)
    2. yt-dlp CLI fallback (< 3.5s, no video download)
    """
    norm_url = normalize_source_url(url)
    video_id = extract_youtube_video_id(norm_url)
    title: Optional[str] = None

    # Step 1: Try ultra-fast direct API if video_id is resolved
    if video_id:
        title = fetch_youtube_title_oembed(norm_url)
        api_text = extract_youtube_api(video_id, lang=lang)
        if api_text:
            cleaned = clean_transcript(api_text)
            if len(cleaned.strip()) > 30:
                return ExtractedContent(
                    source=norm_url,
                    source_type="youtube",
                    title=title or f"YouTube Video ({video_id})",
                    text=cleaned,
                    language=lang,
                )

    # Step 2: Fall back to yt-dlp CLI
    try:
        raw_sub, ytdlp_title = extract_youtube_ytdlp(norm_url, lang=lang)
        clean_text = clean_transcript(raw_sub)
        return ExtractedContent(
            source=norm_url,
            source_type="youtube",
            title=title or ytdlp_title,
            text=clean_text,
            language=lang,
        )
    except Exception as e:
        if video_id:
            raise ExtractorError(
                f"Failed to extract YouTube transcript for video '{video_id}': {e}. "
                "Ensure the video has subtitles/closed-captions enabled, or provide a text transcript file."
            ) from e
        raise ExtractorError(f"Failed to process YouTube URL: {e}") from e


def extract_local_media(path_str: str) -> ExtractedContent:
    """
    Extract transcript from local video or audio files.
    Checks:
    1. Companion subtitle files (.vtt, .srt, .txt) with matching base name
    2. Embedded subtitle tracks via ffmpeg
    """
    path = Path(path_str)
    if not path.is_file():
        raise ExtractorError(f"Media file not found: {path_str}")

    # 1. Check for companion subtitle file
    for ext in [".vtt", ".srt", ".txt"]:
        companion = path.with_suffix(ext)
        if companion.is_file() and companion.stat().st_size > 0:
            raw = companion.read_text(encoding="utf-8", errors="ignore")
            cleaned = clean_transcript(raw)
            return ExtractedContent(
                source=str(path),
                source_type="local_media",
                title=path.stem,
                text=cleaned,
            )

    # 2. Try embedded subtitle stream via ffmpeg
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        with tempfile.TemporaryDirectory() as tmpdir:
            srt_path = os.path.join(tmpdir, "extracted.srt")
            cmd = [ffmpeg_bin, "-i", str(path.resolve()), "-map", "0:s:0?", "-c:s", "srt", srt_path, "-y"]
            try:
                subprocess.run(cmd, capture_output=True, check=False, timeout=60)
            except subprocess.TimeoutExpired as e:
                raise ExtractorError(f"ffmpeg timed out extracting subtitles from '{path.name}'.") from e

            if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
                raw = Path(srt_path).read_text(encoding="utf-8", errors="ignore")
                cleaned = clean_transcript(raw)
                return ExtractedContent(
                    source=str(path),
                    source_type="local_media",
                    title=path.stem,
                    text=cleaned,
                )

    raise ExtractorError(
        f"No subtitle or transcript found for media file '{path.name}'. "
        f"Place a companion subtitle file '{path.stem}.vtt' or '{path.stem}.srt' in the same folder, "
        f"or supply a text transcript directly."
    )


def extract_web_article(url: str) -> ExtractedContent:
    """Extract plain text from an HTML web article."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) vid2skill/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        raise ExtractorError(f"Failed to fetch URL {url}: {e}") from e

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_m.group(1).strip() if title_m else "Web Document"

    # Remove script, style, nav, footer tags
    html = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    return ExtractedContent(
        source=url,
        source_type="web_url",
        title=title,
        text=text,
    )


def extract_content(source: str, lang: str = "en") -> ExtractedContent:
    """
    Universal dispatcher for extracting transcript or text content.
    Accepts:
    - YouTube URLs (http://, https://, or bare domain youtube.com / youtu.be)
    - Local file path (.txt, .md, .vtt, .srt, .mp4, .mkv, .mov, .mp3, .wav, etc.)
    - Web URLs (HTML)
    - Raw text string directly
    """
    source_clean = source.strip()
    norm_source = normalize_source_url(source_clean)

    # YouTube check (handles https://, http://, or bare youtu.be / www.youtube.com)
    if is_youtube_url(norm_source):
        return extract_youtube(norm_source, lang=lang)

    # General Web URL check
    if norm_source.startswith(("http://", "https://")):
        return extract_web_article(norm_source)

    # Local file check
    p = Path(source_clean)
    if p.is_file():
        suffix = p.suffix.lower()
        if suffix in [".vtt", ".srt"]:
            raw = p.read_text(encoding="utf-8", errors="ignore")
            return ExtractedContent(
                source=str(p),
                source_type="text_file",
                title=p.stem,
                text=clean_transcript(raw),
            )
        elif suffix in [".txt", ".md"]:
            raw = p.read_text(encoding="utf-8", errors="ignore")
            return ExtractedContent(
                source=str(p),
                source_type="text_file",
                title=p.stem,
                text=strip_filler(raw),
            )
        elif suffix in [".mp4", ".mkv", ".mov", ".webm", ".avi", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"]:
            return extract_local_media(str(p))

    # Fallback to interpreting as raw text or prompt
    return ExtractedContent(
        source="raw_input",
        source_type="raw_text",
        title="Custom Skill Input",
        text=strip_filler(source_clean),
    )
