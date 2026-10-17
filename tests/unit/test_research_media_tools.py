from __future__ import annotations
import tempfile
from pathlib import Path
import unittest
from PIL import Image
import gaon.runtime.research_media_tools as tools

class ResearchMediaToolTests(unittest.TestCase):
    def test_vtt_normalization_is_bounded_text(self):
        raw=b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello <c>world</c>\n\n00:00:01.000 --> 00:00:02.000\nHello world\nNext line\n"
        self.assertEqual(tools._vtt_to_text(raw), "Hello world\nNext line")

    def test_frame_times_are_bounded(self):
        self.assertEqual(tools._select_frame_times(100, "10,50,999"), [10.0, 50.0])
        self.assertEqual(tools._select_frame_times(100, None), [20.0, 50.0, 80.0])

    def test_document_and_image_stay_inside_authorized_root(self):
        old=tools.RESEARCH_INPUT_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            tools.RESEARCH_INPUT_ROOT=Path(tmp).resolve()
            try:
                text=Path(tmp)/"a.txt"; text.write_text("research evidence",encoding="utf-8")
                self.assertIn("research evidence",tools.document_read({"path":str(text)})["text"])
                image=Path(tmp)/"x.png"; Image.new("RGB",(12,8),"white").save(image)
                meta=tools.image_inspect({"path":str(image)})
                self.assertEqual((meta["width"],meta["height"]),(12,8))
                with self.assertRaises(PermissionError): tools.document_read({"path":"/etc/passwd"})
            finally:
                tools.RESEARCH_INPUT_ROOT=old

    def test_youtube_host_gate(self):
        self.assertEqual(tools._youtube_url("https://youtu.be/abc"),"https://youtu.be/abc")
        with self.assertRaises(ValueError): tools._youtube_url("https://example.com/video")

if __name__ == "__main__": unittest.main()
