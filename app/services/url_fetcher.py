from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse


MAX_FETCHED_TEXT_CHARS = 120_000
BLOCK_TAGS = {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3"}
IGNORED_TAGS = {"script", "style", "noscript", "svg", "canvas"}


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

    req = request.Request(
        normalized_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
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


def render_fetched_url_evidence(result: UrlFetchResult) -> str:
    lines = [
        f"Source URL: {result.url}",
        f"Fetch Status: {result.status}",
    ]
    if result.title:
        lines.append(f"Page Title: {result.title}")
    if result.message:
        lines.append(f"Fetch Message: {result.message}")
    lines.extend(["", "Fetched Content:", result.text or "[未取得頁面內容，僅保留網址作為來源線索]"])
    return "\n".join(lines).strip() + "\n"


def _charset_from_content_type(content_type: str) -> str | None:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def _normalize_text(value: str) -> str:
    collapsed = re.sub(r"[ \t\r\f\v]+", " ", value)
    collapsed = re.sub(r"\n\s*\n+", "\n\n", collapsed)
    return "\n".join(line.strip() for line in collapsed.splitlines() if line.strip())
