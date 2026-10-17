from __future__ import annotations
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
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



    def test_youtube_cookie_file_requires_private_netscape_youtube_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie = Path(tmp) / "cookies.txt"
            cookie.write_text(
                "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture\n",
                encoding="utf-8",
            )
            cookie.chmod(0o600)
            with patch.dict("os.environ", {"GAON_YOUTUBE_COOKIES_FILE": str(cookie)}, clear=False):
                self.assertEqual(tools._youtube_cookie_file(), str(cookie.resolve()))
            cookie.chmod(0o644)
            with patch.dict("os.environ", {"GAON_YOUTUBE_COOKIES_FILE": str(cookie)}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "0600"):
                    tools._youtube_cookie_file()

    def test_youtube_cookie_file_rejects_non_youtube_cookie_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie = Path(tmp) / "cookies.txt"
            cookie.write_text(
                "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture\n",
                encoding="utf-8",
            )
            cookie.chmod(0o600)
            with patch.dict("os.environ", {"GAON_YOUTUBE_COOKIES_FILE": str(cookie)}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "youtube.com"):
                    tools._youtube_cookie_file()

    def test_youtube_po_token_provider_is_added_only_when_built(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "server"
            (home / "build").mkdir(parents=True)
            (home / "build" / "main.js").write_text("// fixture", encoding="utf-8")
            with patch.object(tools, "DEFAULT_YOUTUBE_POT_SERVER_HOME", home), patch.dict(
                "os.environ", {"GAON_YOUTUBE_POT_SERVER_HOME": ""}, clear=False
            ):
                args = tools._youtube_extractor_args()
            self.assertIn("mweb", args["youtube"]["player_client"][0])
            self.assertEqual(args["youtubepot-bgutilscript"]["server_home"], [str(home.resolve())])

    def test_youtube_runtime_auth_state_reports_missing_cookie_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-cookie.txt"
            pot = Path(tmp) / "server"
            (pot / "build").mkdir(parents=True)
            (pot / "build" / "main.js").write_text("// fixture", encoding="utf-8")
            with patch.object(tools, "DEFAULT_YOUTUBE_COOKIE_FILE", missing), patch.object(
                tools, "DEFAULT_YOUTUBE_POT_SERVER_HOME", pot
            ), patch.dict("os.environ", {"GAON_YOUTUBE_COOKIES_FILE": "", "GAON_YOUTUBE_POT_SERVER_HOME": ""}, clear=False):
                state = tools._youtube_runtime_auth_state()
            self.assertTrue(state["po_token_provider_configured"])
            self.assertEqual(state["cookie_auth_state"], "not_configured")
            self.assertIsNone(state["cookie_error"])

    def test_video_info_uses_oembed_when_youtube_challenges_server_ip(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tools, "_youtube_info", side_effect=RuntimeError("YouTube challenged this server IP; configure GAON_YOUTUBE_COOKIES_FILE with an authorized Netscape-format cookie file")), patch.object(
            tools, "_youtube_oembed", return_value={"title": "Fixture video", "author_name": "Fixture author", "thumbnail_url": "https://i.ytimg.com/vi/abc/hqdefault.jpg"}
        ), patch.object(tools, "DEFAULT_YOUTUBE_COOKIE_FILE", Path(tmp) / "missing-cookie.txt"), patch.dict("os.environ", {"GAON_YOUTUBE_COOKIES_FILE": ""}, clear=False):
            result = tools.video_info({"url": "https://youtu.be/abc"})
        self.assertEqual(result["metadata_source"], "youtube-oembed")
        self.assertEqual(result["title"], "Fixture video")
        self.assertFalse(result["transcript_text_available"])
        self.assertFalse(result["frame_analysis_available"])
        self.assertIn("cookie", result["access_limitation"])
        self.assertEqual(result["cookie_auth_state"], "not_configured")

    def test_youtube_host_gate(self):
        self.assertEqual(tools._youtube_url("https://youtu.be/abc"),"https://youtu.be/abc")
        with self.assertRaises(ValueError): tools._youtube_url("https://example.com/video")

if __name__ == "__main__": unittest.main()
