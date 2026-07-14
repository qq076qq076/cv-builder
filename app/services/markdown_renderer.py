from __future__ import annotations

import html
import re


def render_markdown(markdown: str) -> str:
    """Render the small, trusted markdown subset used by generated outputs."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(line.strip() for line in paragraph if line.strip())
            if text:
                blocks.append(f"<p>{_render_inline(text)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_type
        if list_items and list_type:
            items = "".join(f"<li>{_render_inline(item)}</li>" for item in list_items)
            blocks.append(f"<{list_type}>{items}</{list_type}>")
            list_items.clear()
        list_type = None

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
            continue

        if line in {"---", "***", "___"}:
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
            continue

        unordered = re.match(r"^[-*+]\s+(.+)$", line)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            current_type = "ul" if unordered else "ol"
            item = (unordered or ordered).group(1)
            if list_type != current_type:
                flush_list()
                list_type = current_type
            list_items.append(item)
            continue

        if list_items:
            flush_list()
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    return "".join(blocks)


def _render_inline(text: str) -> str:
    escaped = html.escape(text, quote=True)

    def render_link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2)
        if not href.startswith(("https://", "http://", "mailto:")):
            return label
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>'

    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", render_link, escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped
