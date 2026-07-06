from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.schemas.job import TrackedJob
from app.schemas.resume import NormalizedResume


class ResumePdfExporter(Protocol):
    def export(
        self,
        *,
        markdown: str,
        output_path: Path,
        job: TrackedJob,
        resume: NormalizedResume,
    ) -> None:
        pass


class PlaywrightResumePdfExporter:
    def __init__(self, *, template_dir: Path | str = "app/templates") -> None:
        self.environment = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def export(
        self,
        *,
        markdown: str,
        output_path: Path,
        job: TrackedJob,
        resume: NormalizedResume,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        template = self.environment.get_template("pdf/tailored_resume.html")
        html_content = template.render(
            resume=resume,
            job=job,
            content_html=_render_markdown_subset(markdown),
        )
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    page.set_content(html_content, wait_until="load")
                    page.pdf(
                        path=str(output_path),
                        format="A4",
                        print_background=True,
                        margin={
                            "top": "16mm",
                            "right": "14mm",
                            "bottom": "16mm",
                            "left": "14mm",
                        },
                    )
                finally:
                    browser.close()
        except PlaywrightError as exc:
            raise RuntimeError(f"無法產生 PDF：{exc}") from exc


def _render_markdown_subset(markdown: str) -> str:
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    pending_experience_title: str | None = None
    in_experience_section = False
    in_contact_section = False

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines if line.strip())
            if text:
                blocks.append(f"<p>{_render_inline(text)}</p>")
            paragraph_lines.clear()

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{_render_inline(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    def flush_pending_experience_title() -> None:
        nonlocal pending_experience_title
        if pending_experience_title is not None:
            blocks.append(f"<h3>{_render_inline(pending_experience_title)}</h3>")
            pending_experience_title = None

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        if stripped in {"---", "***", "___"}:
            flush_paragraph()
            flush_list()
            flush_pending_experience_title()
            blocks.append('<div class="section-gap"></div>')
            continue

        if _should_skip_personal_profile_link(stripped, in_contact_section=in_contact_section):
            flush_paragraph()
            flush_list()
            flush_pending_experience_title()
            continue

        period_text = _extract_period_text(stripped)
        if pending_experience_title is not None and period_text is not None:
            flush_paragraph()
            flush_list()
            blocks.append(
                '<div class="experience-heading">'
                f'<h3>{_render_inline(pending_experience_title)}</h3>'
                f'<span>{_render_inline(period_text)}</span>'
                "</div>"
            )
            pending_experience_title = None
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if level == 2:
                flush_pending_experience_title()
                in_experience_section = "經歷" in heading_text or "Experience" in heading_text
                in_contact_section = (
                    "聯絡" in heading_text
                    or "Contact" in heading_text
                    or "個人檔案" in heading_text
                    or "Profile" in heading_text
                )
            if level == 3 and in_experience_section:
                flush_pending_experience_title()
                pending_experience_title = heading_text
            else:
                flush_pending_experience_title()
                blocks.append(f"<h{level}>{_render_inline(heading_text)}</h{level}>")
            continue

        list_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if list_match:
            if _should_skip_personal_profile_link(
                list_match.group(1),
                in_contact_section=in_contact_section,
            ):
                continue
            flush_pending_experience_title()
            flush_paragraph()
            list_items.append(list_match.group(1))
            continue

        flush_pending_experience_title()
        flush_list()
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    flush_pending_experience_title()
    return "\n".join(blocks)


def _render_inline(text: str) -> str:
    normalized = _replace_links_with_urls(text)
    escaped = html.escape(normalized, quote=True)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


def _replace_links_with_urls(text: str) -> str:
    text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>.*?</a>', r"\1", text)
    return re.sub(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", r"\1", text)


def _extract_period_text(line: str) -> str | None:
    cleaned = line.strip()
    cleaned = re.sub(r"^\*{1,2}(.+?)\*{1,2}$", r"\1", cleaned).strip()
    cleaned = cleaned.strip("()（）")
    label_match = re.match(r"^(?:就職期間|任職期間|期間|Period)[:：]\s*(.+)$", cleaned, re.I)
    if label_match:
        cleaned = label_match.group(1).strip()
    if _looks_like_period(cleaned):
        return cleaned
    return None


def _looks_like_period(text: str) -> bool:
    if len(text) > 48:
        return False
    return bool(re.search(r"\d{4}|至今|現在|Present|Current", text, re.I))


def _should_skip_personal_profile_link(line: str, *, in_contact_section: bool) -> bool:
    normalized = _replace_links_with_urls(line)
    if not _contains_url(normalized):
        return False
    if in_contact_section:
        return True
    if re.search(r"個人檔案|profile|linkedin|cake(?:resume)?|104|yourator", normalized, re.I):
        return True
    return bool(
        re.search(
            r"https?://(?:www\.)?(?:linkedin\.com/in/|cake\.me/|cakeresume\.com/|104\.com\.tw/|yourator\.co/)",
            normalized,
            re.I,
        )
    )


def _contains_url(text: str) -> bool:
    return bool(re.search(r"https?://", text, re.I))
