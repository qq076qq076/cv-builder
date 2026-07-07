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

TECHNICAL_LAYOUT = "technical"
STANDARD_LAYOUT = "standard"


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
        layout_variant = _select_layout_variant(markdown=markdown, job=job)
        html_content = template.render(
            resume=resume,
            job=job,
            content_html=_render_markdown_subset(
                markdown,
                layout_variant=layout_variant,
            ),
            layout_variant=layout_variant,
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


def _render_markdown_subset(markdown: str, *, layout_variant: str = STANDARD_LAYOUT) -> str:
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    pending_experience_title: str | None = None
    in_experience_section = False
    in_contact_section = False
    current_section: str | None = None
    section_blocks: list[tuple[str, list[str]]] = []

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

    def flush_section() -> None:
        nonlocal blocks, current_section
        if blocks:
            section_blocks.append((current_section or "", blocks))
            blocks = []

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
                f'<span> | {_render_inline(period_text)}</span>'
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
                flush_section()
                current_section = heading_text
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
                display_heading = _display_section_heading(heading_text) if level == 2 else heading_text
                blocks.append(f"<h{level}>{_render_inline(display_heading)}</h{level}>")
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
    flush_section()
    return "\n".join(_order_sections(section_blocks, layout_variant=layout_variant))


def _order_sections(
    section_blocks: list[tuple[str, list[str]]],
    *,
    layout_variant: str,
) -> list[str]:
    ordered_sections = section_blocks
    if layout_variant == TECHNICAL_LAYOUT:
        ordered_sections = sorted(section_blocks, key=lambda item: _technical_section_rank(item[0]))

    rendered: list[str] = []
    for index, (section_name, blocks) in enumerate(ordered_sections):
        section_class = "resume-section"
        if _is_skill_section(section_name):
            section_class += " resume-section-skills"
        if layout_variant == TECHNICAL_LAYOUT and _is_skill_section(section_name):
            section_class += " resume-section-featured"

        rendered.append(
            f'<section class="{section_class}" data-section="{html.escape(section_name, quote=True)}">'
        )
        rendered.extend(blocks)
        rendered.append("</section>")
        if index != len(ordered_sections) - 1:
            rendered.append("")
    return rendered


def _technical_section_rank(section_name: str) -> tuple[int, str]:
    normalized = section_name.lower()
    if not section_name:
        return (0, normalized)
    if any(keyword in section_name for keyword in ("摘要", "Summary", "Profile")):
        return (1, normalized)
    if _is_skill_section(section_name):
        return (2, normalized)
    if any(keyword in section_name for keyword in ("經歷", "Experience")):
        return (3, normalized)
    if any(keyword in section_name for keyword in ("專案", "Project")):
        return (4, normalized)
    if any(keyword in section_name for keyword in ("學歷", "Education")):
        return (5, normalized)
    if any(keyword in section_name for keyword in ("證照", "Certificate", "Certification")):
        return (6, normalized)
    if any(keyword in section_name for keyword in ("語言", "Language")):
        return (7, normalized)
    if any(keyword in section_name for keyword in ("聯絡", "Contact")):
        return (8, normalized)
    return (9, normalized)


def _is_skill_section(section_name: str) -> bool:
    normalized = section_name.lower()
    return "技能" in section_name or "skill" in normalized or "技術" in section_name


def _display_section_heading(section_name: str) -> str:
    normalized = section_name.lower()
    if any(keyword in section_name for keyword in ("摘要",)) or "summary" in normalized:
        return "專業摘要 / Summary"
    if _is_skill_section(section_name):
        return "核心技能 / Skills"
    if any(keyword in section_name for keyword in ("經歷",)) or "experience" in normalized:
        return "工作經歷 / Work Experience"
    if any(keyword in section_name for keyword in ("專案",)) or "project" in normalized:
        return "專案經驗 / Projects"
    if any(keyword in section_name for keyword in ("學歷",)) or "education" in normalized:
        return "學歷 / Education"
    if any(keyword in section_name for keyword in ("證照",)) or "certificat" in normalized:
        return "證照 / Certifications"
    if any(keyword in section_name for keyword in ("語言",)) or "language" in normalized:
        return "語言能力 / Languages"
    if any(keyword in section_name for keyword in ("聯絡",)) or "contact" in normalized:
        return "聯絡方式 / Contact"
    return section_name


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


def _select_layout_variant(*, markdown: str, job: TrackedJob) -> str:
    signal_text = " ".join(
        [
            job.title,
            job.company,
            job.url,
            job.description,
            markdown[:4000],
        ]
    ).lower()
    technical_keywords = {
        "software",
        "frontend",
        "front-end",
        "backend",
        "back-end",
        "fullstack",
        "full-stack",
        "developer",
        "engineer",
        "devops",
        "sre",
        "data engineer",
        "machine learning",
        "ai engineer",
        "python",
        "javascript",
        "typescript",
        "react",
        "vue",
        "angular",
        "node",
        "java",
        "kubernetes",
        "docker",
        "cloud",
        "api",
        "系統",
        "軟體",
        "前端",
        "後端",
        "全端",
        "工程師",
        "開發",
        "資料工程",
        "機器學習",
        "雲端",
        "維運",
        "平台",
    }
    matches = sum(1 for keyword in technical_keywords if keyword in signal_text)
    return TECHNICAL_LAYOUT if matches >= 2 else STANDARD_LAYOUT
