from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - dependency may be absent before install.
    PlaywrightError = Exception
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None


MAX_FETCHED_TEXT_CHARS = 120_000
PLAYWRIGHT_TIMEOUT_MS = 20_000
PLAYWRIGHT_WORKER_TIMEOUT_SECONDS = 35
BLOCK_TAGS = {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3"}
IGNORED_TAGS = {"script", "style", "noscript", "svg", "canvas"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class UrlFetchResult:
    url: str
    status: str
    title: str = ""
    text: str = ""
    message: str = ""


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag_name = tag.lower()
        if tag_name in IGNORED_TAGS:
            self._ignored_depth += 1
        elif tag_name == "title":
            self._in_title = True
        elif tag_name in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag_name == "title":
            self._in_title = False
        elif tag_name in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title:
            self.title_parts.append(stripped)
        self.text_parts.append(stripped)

    @property
    def title(self) -> str:
        return _normalize_text(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self.text_parts))


def fetch_url_text(url: str, *, timeout: float = 10.0) -> UrlFetchResult:
    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        return UrlFetchResult(
            url=normalized_url,
            status="failed",
            message="只支援 http/https 網址",
        )

    if _should_render_with_playwright(parsed):
        return _fetch_url_text_with_playwright_in_thread(normalized_url, timeout=timeout)

    req = request.Request(
        normalized_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(2_000_000)
    except HTTPError as exc:
        return UrlFetchResult(
            url=normalized_url,
            status="failed",
            message=f"HTTP {exc.code}",
        )
    except (OSError, URLError) as exc:
        return UrlFetchResult(
            url=normalized_url,
            status="failed",
            message=str(exc.reason if isinstance(exc, URLError) else exc),
        )

    charset = _charset_from_content_type(content_type)
    decoded = body.decode(charset or "utf-8", errors="ignore")
    if "html" in content_type.lower() or "<html" in decoded[:500].lower():
        parser = _ReadableHTMLParser()
        parser.feed(decoded)
        text = parser.text
        title = parser.title
    else:
        text = _normalize_text(decoded)
        title = ""

    if not text:
        return UrlFetchResult(
            url=normalized_url,
            status="failed",
            message="未取得可解析文字",
        )

    return UrlFetchResult(
        url=normalized_url,
        status="completed",
        title=title,
        text=text[:MAX_FETCHED_TEXT_CHARS],
    )


def _fetch_url_text_with_playwright_in_thread(url: str, *, timeout: float) -> UrlFetchResult:
    # Playwright sync API cannot run in a thread that already owns an asyncio event loop.
    executor = ThreadPoolExecutor(max_workers=1)
    should_wait_for_worker = True
    try:
        future = executor.submit(_fetch_url_text_with_playwright, url, timeout=timeout)
        try:
            return future.result(timeout=PLAYWRIGHT_WORKER_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            should_wait_for_worker = False
            executor.shutdown(wait=False, cancel_futures=True)
            return UrlFetchResult(
                url=url,
                status="failed",
                message="Playwright 抓取逾時",
            )
    finally:
        if should_wait_for_worker:
            executor.shutdown(wait=True)


def _fetch_url_text_with_playwright(url: str, *, timeout: float) -> UrlFetchResult:
    if sync_playwright is None:
        return UrlFetchResult(
            url=url,
            status="failed",
            message="缺少 playwright，請先安裝依賴並執行 playwright install chromium",
        )

    timeout_ms = max(PLAYWRIGHT_TIMEOUT_MS, int(timeout * 1000))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent=USER_AGENT,
                    viewport={"width": 1440, "height": 1200},
                )
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5_000)
                except PlaywrightTimeoutError:
                    pass

                title = _normalize_text(page.title())
                text = _normalize_text(page.locator("body").inner_text(timeout=5_000))
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        return UrlFetchResult(
            url=url,
            status="failed",
            message=f"Playwright 抓取逾時：{exc}",
        )
    except PlaywrightError as exc:
        return UrlFetchResult(
            url=url,
            status="failed",
            message=f"Playwright 抓取失敗：{exc}",
        )
    except Exception as exc:
        return UrlFetchResult(
            url=url,
            status="failed",
            message=f"Playwright 抓取失敗：{exc}",
        )

    if not text:
        return UrlFetchResult(
            url=url,
            status="failed",
            message="Playwright 未取得可解析文字",
        )

    return UrlFetchResult(
        url=url,
        status="completed",
        title=title,
        text=text[:MAX_FETCHED_TEXT_CHARS],
    )


def render_fetched_url_evidence(result: UrlFetchResult) -> str:
    lines = [
        f"Source URL: {result.url}",
        f"Fetch Status: {result.status}",
    ]
    if result.title:
        lines.append(f"Page Title: {result.title}")
    if result.message:
        lines.append(f"Fetch Message: {result.message}")
    lines.extend(
        [
            "",
            "Fetched Content:",
            result.text or "[未取得頁面內容，僅保留網址作為來源線索]",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _charset_from_content_type(content_type: str) -> str | None:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def _normalize_text(value: str) -> str:
    collapsed = re.sub(r"[ \t\r\f\v]+", " ", value)
    collapsed = re.sub(r"\n\s*\n+", "\n\n", collapsed)
    return "\n".join(line.strip() for line in collapsed.splitlines() if line.strip())


def _should_render_with_playwright(parsed) -> bool:
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "cake.me" in host or "cakeresume.com" in host:
        return True
    if "linkedin.com" in host or "linkdin.com" in host:
        return "/in/" in path
    if "yourator.co" in host:
        return True
    return "104.com.tw" in host and "/profile/" in path
