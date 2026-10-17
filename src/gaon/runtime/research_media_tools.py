"""Bounded read-only external research, document, vision, and video tools.

External text/images/video are untrusted evidence only. These helpers never
mutate strategy state, never place orders, and never promote candidates.
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterable
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup
from docx import Document
from PIL import Image
from pypdf import PdfReader
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from gaon.knowledge.content_acquisition import ContentAcquisitionPolicy, SameHostRedirectHandler, validate_content_url

RESEARCH_INPUT_ROOT = Path(os.environ.get("GAON_RESEARCH_INPUT_ROOT", "/var/lib/strategylab/research_inputs")).resolve()
MAX_FETCH_BYTES = 5_000_000
MAX_TEXT_CHARS = 40_000
MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 16_000_000
MAX_VIDEO_DURATION_SECONDS = 4 * 60 * 60
DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_SAFE_DOC_SUFFIXES = frozenset({".pdf", ".docx", ".txt", ".md", ".csv", ".json"})
_SAFE_RESEARCH_PATH_PREFIXES = (RESEARCH_INPUT_ROOT,)


class BoundedResearchToolError(RuntimeError):
    pass


def _bounded_text(value: object, *, limit: int = MAX_TEXT_CHARS) -> str:
    text = str(value or "")
    return text[:limit]


def _public_https_url(url: str) -> tuple[str, str]:
    value = str(url).strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("only public HTTPS URLs are allowed")
    host = parsed.hostname.lower()
    policy = ContentAcquisitionPolicy(network_enabled=True, allowed_hosts=(host,), max_content_bytes=MAX_FETCH_BYTES)
    return validate_content_url(value, policy=policy), host


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SameHostRedirectHandler(max_redirects=3))


def _read_bounded_response(response, *, limit: int) -> bytes:
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("source exceeds byte limit")
    return raw


def _decode_text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _html_text(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def _xml_text(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "xml")
    return soup.get_text(" ", strip=True)


def _pdf_text(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    chunks: list[str] = []
    total = 0
    for page in reader.pages[:30]:
        part = page.extract_text() or ""
        if part:
            chunks.append(part)
            total += len(part)
        if total >= MAX_TEXT_CHARS:
            break
    return "\n".join(chunks)


def _document_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    try:
        p.relative_to(RESEARCH_INPUT_ROOT)
    except ValueError as exc:
        raise PermissionError("document path is outside the authorized research input directory") from exc
    if not p.is_file():
        raise FileNotFoundError(p)
    if p.stat().st_size > MAX_FETCH_BYTES:
        raise ValueError("document exceeds byte limit")
    return p


def web_search(args: dict[str, object]) -> dict[str, object]:
    """Bounded real web search through DuckDuckGo's HTML endpoint."""
    query = str(args.get("query", "")).strip()
    if len(query) < 2:
        raise ValueError("query must be at least 2 characters")
    query = query[:240]
    try:
        max_results = int(args.get("max_results", 5))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_results must be an integer") from exc
    max_results = max(1, min(max_results, 8))
    body = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(
        DDG_ENDPOINT,
        data=body,
        headers={"User-Agent": "Mozilla/5.0 StrategyLab-Gaon/1.0", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        raw = _read_bounded_response(response, limit=700_000)
    soup = BeautifulSoup(raw, "html.parser")
    results: list[dict[str, object]] = []
    for item in soup.select(".result"):
        anchor = item.select_one("a.result__a")
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("//"):
            href = "https:" + href
        parsed = urllib.parse.urlsplit(href)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
            target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                href = urllib.parse.unquote(target)
        title = anchor.get_text(" ", strip=True)
        snippet_el = item.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        if href.startswith("https://"):
            results.append({"title": title[:500], "url": href[:2000], "snippet": snippet[:1200]})
        if len(results) >= max_results:
            break
    return {
        "provider": "duckduckgo-html",
        "query": query,
        "results": results,
        "result_count": len(results),
        "live": True,
        "untrusted_evidence": True,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
    }


def url_read(args: dict[str, object]) -> dict[str, object]:
    url, host = _public_https_url(str(args.get("url", "")))
    req = urllib.request.Request(url, headers={"User-Agent": "StrategyLab-Gaon/1.0", "Accept": "text/html,text/plain,application/json,application/pdf,text/xml,application/xml;q=0.9,*/*;q=0.1"})
    with _opener().open(req, timeout=15) as response:
        raw = _read_bounded_response(response, limit=MAX_FETCH_BYTES)
        mime = (response.headers.get_content_type() or "").lower()
        final_url = response.geturl()
    if mime == "application/pdf":
        text = _pdf_text(raw)
    elif mime == "text/html":
        text = _html_text(raw)
    elif mime in {"text/xml", "application/xml"}:
        text = _xml_text(raw)
    elif mime in {"text/plain", "application/json", "text/csv", "application/csv"}:
        text = _decode_text(raw)
    else:
        raise ValueError(f"unsupported MIME type: {mime or 'missing'}")
    return {
        "source": url,
        "final_url": final_url,
        "host": host,
        "mime": mime,
        "bytes": len(raw),
        "text": _bounded_text(text),
        "truncated": len(text) > MAX_TEXT_CHARS,
        "untrusted_evidence": True,
        "external_text_is_instruction": False,
    }


def paper_search(args: dict[str, object]) -> dict[str, object]:
    query = str(args.get("query", "")).strip()[:240]
    if len(query) < 2:
        raise ValueError("query required")
    try:
        rows = max(1, min(int(args.get("max_results", 5)), 10))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_results must be an integer") from exc
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"rows": rows, "query": query})
    req = urllib.request.Request(url, headers={"User-Agent": "GaonResearch/1.0 (research-only)"})
    with urllib.request.urlopen(req, timeout=12) as response:
        raw = _read_bounded_response(response, limit=1_000_000)
    data = json.loads(raw)
    items = []
    for item in data.get("message", {}).get("items", [])[:rows]:
        date_parts = (item.get("published") or item.get("published-print") or item.get("created") or {}).get("date-parts") or [[None]]
        items.append({
            "title": ((item.get("title") or [""])[0])[:1000],
            "doi": item.get("DOI"),
            "url": item.get("URL"),
            "year": date_parts[0][0] if date_parts and date_parts[0] else None,
            "publisher": item.get("publisher"),
            "type": item.get("type"),
        })
    return {"provider": "crossref", "query": query, "results": items, "result_count": len(items), "untrusted_evidence": True}


def document_read(args: dict[str, object]) -> dict[str, object]:
    p = _document_path(str(args.get("path", "")))
    ext = p.suffix.lower()
    if ext not in _SAFE_DOC_SUFFIXES:
        raise ValueError("unsupported document format")
    data = p.read_bytes()
    if ext == ".pdf":
        text = _pdf_text(data)
    elif ext == ".docx":
        doc = Document(io.BytesIO(data))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    else:
        text = _decode_text(data)
    return {
        "source": str(p),
        "format": ext.lstrip("."),
        "bytes": len(data),
        "text": _bounded_text(text),
        "truncated": len(text) > MAX_TEXT_CHARS,
        "untrusted_evidence": True,
    }


def _load_image_bytes(args: dict[str, object]) -> tuple[bytes, str]:
    path = str(args.get("path", "") or "").strip()
    url = str(args.get("url", "") or "").strip()
    if bool(path) == bool(url):
        raise ValueError("provide exactly one of path or url")
    if path:
        p = _document_path(path)
        raw = p.read_bytes()
        source = str(p)
    else:
        safe_url, _host = _public_https_url(url)
        req = urllib.request.Request(safe_url, headers={"User-Agent": "StrategyLab-Gaon/1.0", "Accept": "image/*"})
        with _opener().open(req, timeout=15) as response:
            mime = (response.headers.get_content_type() or "").lower()
            if not mime.startswith("image/"):
                raise ValueError("URL did not return an image")
            raw = _read_bounded_response(response, limit=MAX_IMAGE_BYTES)
        source = safe_url
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds byte limit")
    return raw, source


def _prepare_image(raw: bytes) -> tuple[bytes, dict[str, object]]:
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("image dimensions exceed pixel limit")
        meta = {"width": image.width, "height": image.height, "format": image.format, "mode": image.mode}
        converted = image.convert("RGB")
        converted.thumbnail((1600, 1600))
        out = io.BytesIO()
        converted.save(out, format="JPEG", quality=88, optimize=True)
        return out.getvalue(), meta


def image_inspect(args: dict[str, object]) -> dict[str, object]:
    raw, source = _load_image_bytes(args)
    _jpeg, meta = _prepare_image(raw)
    return {"source": source, **meta, "semantic_analysis": False, "untrusted_evidence": True}


def _ollama_base_url() -> str:
    raw = os.environ.get("GAON_VISION_BASE_URL") or os.environ.get("GAON_ASSISTANT_BASE_URL") or "http://127.0.0.1:11434/v1"
    value = raw.rstrip("/")
    if value.endswith("/v1"):
        value = value[:-3]
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid configured vision base URL")
    return value


def _vision_bytes(raw: bytes, prompt: str, *, source: str) -> dict[str, object]:
    jpeg, meta = _prepare_image(raw)
    model = os.environ.get("GAON_VISION_MODEL", "qwen3-vl:4b").strip()
    if not model:
        raise RuntimeError("vision model is not configured")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt[:2500], "images": [base64.b64encode(jpeg).decode("ascii")]}],
        "stream": False,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        _ollama_base_url() + "/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = json.loads(_read_bounded_response(response, limit=2_000_000))
    content = str((payload.get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("vision provider returned no analysis")
    return {
        "source": source,
        **meta,
        "model": model,
        "analysis": content[:12000],
        "semantic_analysis": True,
        "untrusted_evidence": True,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
    }


def image_vision(args: dict[str, object]) -> dict[str, object]:
    raw, source = _load_image_bytes(args)
    prompt = str(args.get("prompt") or "이미지의 내용을 사실 위주로 분석하세요. 차트라면 추세, 변동성, 거래량, 지지/저항, 캔들 패턴을 관찰하되 보이지 않는 수치를 추측하지 마세요.")
    return _vision_bytes(raw, prompt, source=source)


def _youtube_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url).strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in YOUTUBE_HOSTS:
        raise ValueError("only HTTPS YouTube URLs are supported")
    return str(url).strip()


def _youtube_cookie_file() -> str | None:
    raw = os.environ.get("GAON_YOUTUBE_COOKIES_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError("configured YouTube cookie file does not exist")
    return str(path)


def _youtube_info(url: str, *, fmt: str | None = None) -> dict[str, object]:
    opts: dict[str, object] = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "socket_timeout": 15,
        "retries": 1,
        "extractor_retries": 1,
        "noplaylist": True,
    }
    cookiefile = _youtube_cookie_file()
    if cookiefile:
        opts["cookiefile"] = cookiefile
    if fmt:
        opts["format"] = fmt
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        message = str(exc)
        if "not a bot" in message.casefold() or "sign in" in message.casefold():
            raise RuntimeError(
                "YouTube challenged this server IP; configure GAON_YOUTUBE_COOKIES_FILE with an authorized Netscape-format cookie file"
            ) from exc
        raise
    if not isinstance(info, dict):
        raise RuntimeError("video metadata unavailable")
    duration = int(info.get("duration") or 0)
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise ValueError("video exceeds duration limit")
    return info


def _youtube_oembed(url: str) -> dict[str, object]:
    endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": url, "format": "json"})
    req = urllib.request.Request(endpoint, headers={"User-Agent": "StrategyLab-Gaon/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.loads(_read_bounded_response(response, limit=256_000))
    if not isinstance(payload, dict):
        raise RuntimeError("YouTube oEmbed metadata unavailable")
    return payload


def video_info(args: dict[str, object]) -> dict[str, object]:
    url = _youtube_url(str(args.get("url", "")))
    try:
        info = _youtube_info(url)
    except RuntimeError as exc:
        if "YouTube challenged this server IP" not in str(exc):
            raise
        meta = _youtube_oembed(url)
        return {
            "source": url,
            "id": None,
            "title": meta.get("title"),
            "duration": None,
            "uploader": meta.get("author_name"),
            "upload_date": None,
            "thumbnail_url": meta.get("thumbnail_url"),
            "subtitles_languages": [],
            "automatic_captions_languages": [],
            "transcript_text_available": False,
            "frame_analysis_available": False,
            "metadata_source": "youtube-oembed",
            "access_limitation": "youtube_bot_challenge_requires_authorized_cookie_file",
            "untrusted_evidence": True,
        }
    return {
        "source": url,
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "subtitles_languages": sorted((info.get("subtitles") or {}).keys()),
        "automatic_captions_languages": sorted((info.get("automatic_captions") or {}).keys()),
        "transcript_text_available": bool(info.get("subtitles") or info.get("automatic_captions")),
        "frame_analysis_available": bool(os.environ.get("GAON_VISION_MODEL")) and bool(_ffmpeg_path()),
        "metadata_source": "yt-dlp",
        "untrusted_evidence": True,
    }


def _pick_caption(info: dict[str, object], requested: str | None) -> tuple[str, str] | None:
    groups = [info.get("subtitles") or {}, info.get("automatic_captions") or {}]
    preferred = [requested] if requested else []
    preferred += ["ko", "en", "en-US", "en-GB"]
    for group in groups:
        if not isinstance(group, dict):
            continue
        languages = preferred + [str(k) for k in group if str(k) not in preferred]
        for lang in languages:
            rows = group.get(lang)
            if not isinstance(rows, list):
                continue
            choices = sorted(rows, key=lambda x: 0 if str(x.get("ext")) == "vtt" else 1)
            for row in choices:
                u = str(row.get("url") or "")
                if u.startswith("https://"):
                    return lang, u
    return None


def _vtt_to_text(raw: bytes) -> str:
    text = _decode_text(raw)
    lines: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith(("WEBVTT", "Kind:", "Language:")) or "-->" in value or re.fullmatch(r"\d+", value):
            continue
        value = re.sub(r"<[^>]+>", "", html.unescape(value))
        value = re.sub(r"\s+", " ", value).strip()
        if value and value not in seen:
            seen.add(value)
            lines.append(value)
    return "\n".join(lines)


def video_transcript(args: dict[str, object]) -> dict[str, object]:
    url = _youtube_url(str(args.get("url", "")))
    language = str(args.get("language", "") or "").strip() or None
    info = _youtube_info(url)
    picked = _pick_caption(info, language)
    if picked is None:
        raise RuntimeError("no subtitles or automatic captions are available")
    lang, caption_url = picked
    req = urllib.request.Request(caption_url, headers={"User-Agent": "StrategyLab-Gaon/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = _read_bounded_response(response, limit=2_000_000)
    text = _vtt_to_text(raw)
    return {
        "source": url,
        "title": info.get("title"),
        "language": lang,
        "text": _bounded_text(text),
        "truncated": len(text) > MAX_TEXT_CHARS,
        "automatic_caption_possible": True,
        "untrusted_evidence": True,
    }


def _ffmpeg_path() -> str | None:
    from shutil import which
    return which("ffmpeg")


def _select_frame_times(duration: int, timestamps: str | None) -> list[float]:
    if timestamps:
        values: list[float] = []
        for raw in timestamps.split(",")[:5]:
            try:
                value = float(raw.strip())
            except ValueError:
                continue
            if 0 <= value <= max(duration, 1):
                values.append(value)
        if values:
            return values
    if duration <= 0:
        return [0.0]
    return [duration * 0.2, duration * 0.5, duration * 0.8]


def video_frame_analysis(args: dict[str, object]) -> dict[str, object]:
    url = _youtube_url(str(args.get("url", "")))
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not configured")
    info = _youtube_info(url)
    formats = info.get("formats") if isinstance(info.get("formats"), list) else []
    candidates = []
    for item in formats:
        if not isinstance(item, dict):
            continue
        stream = str(item.get("url") or "")
        vcodec = str(item.get("vcodec") or "none")
        height = int(item.get("height") or 0)
        if not stream.startswith("https://") or vcodec == "none":
            continue
        if height and height <= 480:
            candidates.append((0 if height >= 240 else 1, abs(height - 360), item))
    if not candidates:
        candidates = [(2, 0, item) for item in formats if isinstance(item, dict) and str(item.get("url") or "").startswith("https://") and str(item.get("vcodec") or "none") != "none"]
    if not candidates:
        raise RuntimeError("bounded video stream URL unavailable")
    candidates.sort(key=lambda row: (row[0], row[1], int(row[2].get("filesize") or row[2].get("filesize_approx") or 0)))
    stream_url = str(candidates[0][2].get("url") or "")
    duration = int(info.get("duration") or 0)
    times = _select_frame_times(duration, str(args.get("timestamps", "") or ""))
    prompt = str(args.get("prompt") or "이 영상 프레임에서 보이는 내용을 사실 위주로 분석하세요. 차트라면 추세·캔들·거래량·표시된 수치를 관찰하되 보이지 않는 내용을 추측하지 마세요.")
    frames: list[dict[str, object]] = []
    for second in times:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{second:.3f}", "-i", stream_url, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            frames.append({"timestamp": round(second, 3), "status": "frame_unavailable", "error": proc.stderr.decode("utf-8", "replace")[:500]})
            continue
        try:
            analysis = _vision_bytes(proc.stdout, prompt, source=f"{url}#t={second:.3f}")
            frames.append({"timestamp": round(second, 3), "status": "analyzed", "analysis": analysis["analysis"], "model": analysis["model"]})
        except Exception as exc:  # noqa: BLE001 - per-frame failure stays isolated.
            frames.append({"timestamp": round(second, 3), "status": "analysis_failed", "error_type": exc.__class__.__name__, "message": str(exc)[:500]})
    return {
        "source": url,
        "title": info.get("title"),
        "duration": duration,
        "frames": frames,
        "analyzed_frame_count": sum(1 for frame in frames if frame.get("status") == "analyzed"),
        "untrusted_evidence": True,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
    }
