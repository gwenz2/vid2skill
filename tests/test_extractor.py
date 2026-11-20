import unittest
from pathlib import Path
import tempfile

from vid2skill.core.extractor import (
    clean_vtt_or_srt,
    strip_filler,
    clean_transcript,
    extract_content,
    is_youtube_url,
    normalize_source_url,
    extract_youtube_video_id,
)

SAMPLE_VTT = """WEBVTT
Kind: captions
Language: en

1
00:00:00.500 --> 00:00:02.000
<c.color>Welcome to this tutorial on system design.</c.color>

2
00:00:02.000 --> 00:00:04.500
<c.color>Welcome to this tutorial on system design.</c.color>
Today we're exploring caching layers.

3
00:00:04.500 --> 00:00:07.000
Please like and subscribe to my channel.
Hit that bell icon for notifications.
"""

PROGRESSIVE_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
In this video

00:00:01.000 --> 00:00:02.000
In this video we are going

00:00:02.000 --> 00:00:03.000
In this video we are going to build agent skills
"""

ROLLING_WORD_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.500
we are learning to optimize

00:00:01.500 --> 00:00:03.000
to optimize production database queries
"""


class TestExtractor(unittest.TestCase):

    def test_clean_vtt_or_srt(self):
        cleaned = clean_vtt_or_srt(SAMPLE_VTT)
        self.assertNotIn("WEBVTT", cleaned)
        self.assertNotIn("-->", cleaned)
        self.assertNotIn("<c.color>", cleaned)
        self.assertIn("Welcome to this tutorial on system design.", cleaned)
        self.assertIn("Today we're exploring caching layers.", cleaned)
        # Check de-duplication
        count = cleaned.count("Welcome to this tutorial on system design.")
        self.assertEqual(count, 1)

    def test_clean_vtt_progressive_accumulation(self):
        cleaned = clean_vtt_or_srt(PROGRESSIVE_VTT)
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "In this video we are going to build agent skills")

    def test_clean_vtt_rolling_word_overlap(self):
        cleaned = clean_vtt_or_srt(ROLLING_WORD_VTT)
        self.assertIn("we are learning to optimize production database queries", cleaned)
        self.assertEqual(cleaned.count("to optimize"), 1)

    def test_strip_filler(self):
        raw = "We use Redis for caching. [Music] Please like and subscribe! ♪ Also smash that like button."
        filtered = strip_filler(raw)
        self.assertIn("We use Redis for caching.", filtered)
        self.assertNotIn("like and subscribe", filtered.lower())
        self.assertNotIn("smash that like button", filtered.lower())
        self.assertNotIn("[music]", filtered.lower())
        self.assertNotIn("♪", filtered)

    def test_clean_transcript_combined(self):
        result = clean_transcript(SAMPLE_VTT)
        self.assertIn("Welcome to this tutorial on system design.", result)
        self.assertIn("Today we're exploring caching layers.", result)
        self.assertNotIn("like and subscribe", result.lower())
        self.assertNotIn("bell icon", result.lower())

    def test_is_youtube_url(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(is_youtube_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(is_youtube_url("http://m.youtube.com/watch?v=abc"))
        self.assertTrue(is_youtube_url("youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(is_youtube_url("www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertFalse(is_youtube_url("https://example.com/video.mp4"))
        self.assertFalse(is_youtube_url("C:/files/video.mp4"))

    def test_extract_youtube_video_id(self):
        self.assertEqual(extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_normalize_source_url(self):
        self.assertEqual(normalize_source_url("youtu.be/abc"), "https://youtu.be/abc")
        self.assertEqual(normalize_source_url("www.youtube.com/watch?v=abc"), "https://www.youtube.com/watch?v=abc")
        self.assertEqual(normalize_source_url("https://example.com"), "https://example.com")

    def test_extract_content_text_file(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write("This is a guide to building robust microservices.")
            tmp_path = tmp.name

        try:
            content = extract_content(tmp_path)
            self.assertEqual(content.source_type, "text_file")
            self.assertIn("robust microservices", content.text)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_extract_content_raw_prompt(self):
        prompt = "Create a skill for profiling database queries."
        content = extract_content(prompt)
        self.assertEqual(content.source_type, "raw_text")
        self.assertEqual(content.text, prompt)


if __name__ == "__main__":
    unittest.main()
