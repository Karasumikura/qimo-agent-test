from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .jlu_connector import JLU_COURSE_LIBRARY_URL
from .storage import ROOT_DIR, now_iso


MEDIA_EXT_PATTERN = (".mp4", ".m3u8", ".webm", ".mov", ".mkv", ".flv", ".m4a", ".mp3", ".vtt", ".srt")
MEDIA_WORDS = ("video", "media", "stream", "vod", "m3u8", "mp4", "play", "courseware", "resource", "download")
TRANSCRIPT_SELECTOR = (
    "textarea,[contenteditable=true],.transcript,.subtitle,.caption,.captions,"
    "[class*=transcript],[class*=subtitle],[class*=caption],"
    "[id*=transcript],[id*=subtitle],[id*=caption]"
)
TRANSCRIPT_HINTS = (
    "字幕",
    "转写",
    "转文字",
    "文字稿",
    "课程实录",
    "识别结果",
    "老师",
    "重点",
    "考试",
    "transcript",
    "subtitle",
    "caption",
)


@dataclass
class BrowserAgentState:
    running: bool = False
    logged_in_hint: bool = False
    state: str = "idle"
    page_title: str = ""
    page_url: str = ""
    captured_count: int = 0
    submitted_count: int = 0
    transcript_count: int = 0
    last_error: str = ""
    last_seen: str | None = None
    profile_dir: str = ""
    queued_urls: list[str] = field(default_factory=list)


class ControlledBrowserAgent:
    def __init__(self) -> None:
        self.profile_dir = ROOT_DIR / "data" / "browser-profile"
        self.download_dir = ROOT_DIR / "data" / "browser-downloads"
        self._state = BrowserAgentState(profile_dir=str(self.profile_dir))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._candidates: dict[str, dict[str, Any]] = {}
        self._submitted_keys: set[str] = set()
        self._lock = threading.Lock()
        self.import_callback: Any = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = self._state.__dict__.copy()
            data["queued_urls"] = list(data["queued_urls"][-8:])
            return data

    def configure_import_callback(self, callback: Any) -> None:
        self.import_callback = callback

    def start(self, url: str = JLU_COURSE_LIBRARY_URL) -> dict[str, Any]:
        if self._loop and self._loop.is_running():
            self._run_coroutine(self._open_url(url))
            return self.snapshot()

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run_loop, args=(url,), daemon=True)
        self._thread.start()
        self._set_state(running=True, state="starting", last_error="")
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        if self._loop and self._loop.is_running():
            self._run_coroutine(self._stop_async())
        return self.snapshot()

    def scan_now(self) -> dict[str, Any]:
        if self._loop and self._loop.is_running():
            self._run_coroutine(self._scan_current_page())
        return self.snapshot()

    def open_url(self, url: str) -> dict[str, Any]:
        if not self._loop or not self._loop.is_running():
            return self.start(url)
        self._run_coroutine(self._open_url(url))
        return self.snapshot()

    def _run_loop(self, url: str) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async(url))
            loop.run_forever()
        finally:
            with suppress(Exception):
                loop.run_until_complete(self._stop_async())
            loop.close()

    def _run_coroutine(self, coro: Any) -> None:
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _start_async(self, url: str) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self._set_state(
                running=False,
                state="error",
                last_error="未安装 Playwright：请运行 python -m pip install playwright",
            )
            return

        try:
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                accept_downloads=True,
                downloads_path=str(self.download_dir),
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context.on("page", self._attach_page)
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            self._attach_page(self._page)
            await self._open_url(url)
            self._set_state(running=True, state="waiting_login", last_error="")
        except Exception as exc:  # noqa: BLE001
            self._set_state(
                running=False,
                state="error",
                last_error=f"无法启动专用浏览器：{exc}",
            )
            with suppress(Exception):
                if self._playwright:
                    await self._playwright.stop()

    async def _stop_async(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        finally:
            self._context = None
            self._page = None
            self._playwright = None
            self._set_state(running=False, state="stopped")
            if self._loop:
                self._loop.call_soon_threadsafe(self._loop.stop)

    async def _open_url(self, url: str) -> None:
        if not self._page:
            return
        await self._page.goto(url)
        await self._update_page_state(self._page, state="watching")
        await self._scan_current_page()

    def _attach_page(self, page: Any) -> None:
        self._page = page
        page.on("response", lambda response: asyncio.create_task(self._handle_response(response)))
        page.on("domcontentloaded", lambda: asyncio.create_task(self._scan_current_page()))
        page.on("load", lambda: asyncio.create_task(self._scan_current_page()))

    async def _handle_response(self, response: Any) -> None:
        try:
            url = response.url
            content_type = (response.headers or {}).get("content-type", "")
            if not self._looks_like_media(url, content_type):
                return
            candidate = {
                "url": url,
                "content_type": content_type,
                "status": response.status,
                "page_url": response.request.frame.url if response.request and response.request.frame else "",
            }
            self._candidates[url] = candidate
            await self._update_page_state(self._page, state="capturing")
            await self._submit_current_candidates()
        except Exception as exc:  # noqa: BLE001
            self._set_state(state="error", last_error=str(exc))

    async def _scan_current_page(self) -> None:
        if not self._page:
            return
        try:
            await self._update_page_state(self._page, state="watching")
            transcript = await self._extract_transcript(self._page)
            if transcript:
                await self._submit_transcript(transcript)
            await self._submit_current_candidates()
        except Exception as exc:  # noqa: BLE001
            self._set_state(state="error", last_error=str(exc))

    async def _submit_current_candidates(self) -> None:
        if not self.import_callback or not self._page:
            return
        candidates = list(self._candidates.values())[-60:]
        if not candidates:
            return
        page_url = self._page.url
        title = await self._page.title()
        urls = [item["url"] for item in candidates]
        key = "|".join(urls[-8:])
        if key in self._submitted_keys:
            return
        self._submitted_keys.add(key)
        transcript = await self._extract_transcript(self._page)
        request_headers = await self._download_headers(self._page)
        await asyncio.to_thread(
            self.import_callback,
            {
                "course": course_from_title(title),
                "title": title or "学在吉大视频",
                "url": urls[0],
                "page_url": page_url,
                "kind": "lecture_video",
                "detected_urls": urls,
                "transcript_text": transcript[:200000],
                "transcript_title": f"{safe_title(title)}-page-transcript.txt",
                "request_headers": request_headers,
                "auto_analyze": True,
            },
        )
        self._set_state(
            state="submitted",
            submitted_count=self._state.submitted_count + 1,
            captured_count=len(self._candidates),
            queued_urls=urls[-8:],
            last_error="",
        )

    async def _submit_transcript(self, transcript: str) -> None:
        if not self.import_callback or not self._page:
            return
        page_url = self._page.url
        title = await self._page.title()
        key = f"transcript:{page_url}:{hash(transcript[:500])}"
        if key in self._submitted_keys:
            return
        self._submitted_keys.add(key)
        await asyncio.to_thread(
            self.import_callback,
            {
                "course": course_from_title(title),
                "title": f"{title or '学在吉大页面'} 文字稿",
                "page_url": page_url,
                "kind": "transcript",
                "transcript_text": transcript[:200000],
                "transcript_title": f"{safe_title(title)}-page-transcript.txt",
                "auto_analyze": True,
            },
        )
        self._set_state(
            state="submitted",
            transcript_count=self._state.transcript_count + 1,
            last_error="",
        )

    async def _extract_transcript(self, page: Any) -> str:
        return await page.evaluate(
            """
            ({ selector, hints }) => {
              const textNodes = [];
              const selection = String(window.getSelection ? window.getSelection() : "").trim();
              if (selection.length > 80) textNodes.push(selection);
              document.querySelectorAll(selector).forEach((node) => {
                const text = (node.value || node.innerText || node.textContent || "").trim();
                if (text.length > 80) textNodes.push(text);
              });
              document.querySelectorAll("section,article,main,div").forEach((node) => {
                const text = (node.innerText || "").trim();
                if (text.length > 180 && text.length < 30000 && hints.some((hint) => text.includes(hint))) {
                  textNodes.push(text);
                }
              });
              return [...new Set(textNodes)].sort((a, b) => b.length - a.length)[0] || "";
            }
            """,
            {"selector": TRANSCRIPT_SELECTOR, "hints": list(TRANSCRIPT_HINTS)},
        )

    async def _download_headers(self, page: Any) -> dict[str, str]:
        if not self._context:
            return {}
        cookies = await self._context.cookies()
        cookie_header = "; ".join(
            f"{item['name']}={item['value']}"
            for item in cookies
            if item.get("name") and item.get("value") is not None
        )
        user_agent = await page.evaluate("() => navigator.userAgent")
        headers = {
            "User-Agent": user_agent,
            "Referer": page.url,
        }
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    async def _update_page_state(self, page: Any, state: str) -> None:
        if not page:
            return
        title = await page.title()
        url = page.url
        host = urlparse(url).hostname or ""
        logged_in_hint = bool(host and "ilearntec.jlu.edu.cn" in host and "login" not in url.lower())
        self._set_state(
            running=True,
            logged_in_hint=logged_in_hint,
            state=state,
            page_title=title,
            page_url=url,
            captured_count=len(self._candidates),
            last_seen=now_iso(),
        )

    def _looks_like_media(self, url: str, content_type: str = "") -> bool:
        lowered = url.lower()
        ctype = content_type.lower()
        if "127.0.0.1" in lowered or "localhost" in lowered:
            return False
        if any(lowered.split("?", 1)[0].endswith(ext) for ext in MEDIA_EXT_PATTERN):
            return True
        if "video/" in ctype or "audio/" in ctype or "mpegurl" in ctype or "text/vtt" in ctype:
            return True
        return any(word in lowered for word in MEDIA_WORDS)

    def _set_state(self, **updates: Any) -> None:
        with self._lock:
            for key, value in updates.items():
                setattr(self._state, key, value)
            self._state.profile_dir = str(self.profile_dir)
            if "last_seen" not in updates and self._state.running:
                self._state.last_seen = now_iso()


def course_from_title(title: str) -> str:
    value = (title or "").strip()
    for splitter in ("-", "_", "|", "｜"):
        if splitter in value:
            value = value.split(splitter, 1)[0].strip()
    return value or "未命名课程"


def safe_title(title: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in (title or "page"))[:80]


browser_agent = ControlledBrowserAgent()
