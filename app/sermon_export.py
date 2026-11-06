"""Turns a sermon note into a file: Markdown, PDF or Word.

Layout only. app/sermons.py gathers what goes in (the note, the text of each
verse in the reader's translation, and the photos' bytes) and this module
lays it out, so changing how an export looks never touches how a note is
stored. Every function here is pure and is unit tested in
tests/test_sermons.py.

A note's blocks are the shapes app/sermons.py validates: text, heading,
verse, image, quote, todo and link.
"""

import re
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Inches, Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_EMBER = colors.HexColor("#B5541C")
_WARM = colors.HexColor("#FFF3E6")
_LINE = colors.HexColor("#F0C9A3")
_MUTED = colors.HexColor("#6B5A49")

# Ballot boxes for a to-do list in Word, where the fonts have them. The PDF's
# built-in fonts don't, so it writes "(done)" instead.
_BOX_OPEN, _BOX_DONE = "☐", "☑"


def note_title(note: dict) -> str:
    return (note.get("title") or "").strip() or "Untitled sermon"


def nice_date(value) -> str:
    """"Sunday 1 November 2026" for an ISO date, "" for none."""
    if not value:
        return ""
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{day:%A} {day.day} {day:%B %Y}"


def meta_line(note: dict) -> str:
    """Speaker, church and date on one line, skipping whatever is blank."""
    return " · ".join(p for p in (note.get("speaker"), note.get("church"), nice_date(note.get("preached_on"))) if p)


def filename(note: dict, extension: str) -> str:
    """A safe, readable file name: "2026-11-01 Anxious for nothing.pdf"."""
    stem = re.sub(r"[^\w\s-]", "", note_title(note)).strip()[:80] or "Sermon"
    when = str(note.get("preached_on") or "")[:10]
    return f"{when} {stem}.{extension}".strip()


def _verse_line(block: dict, verse_texts: dict[str, str]) -> str | None:
    """The verse's text for an export, or None when there isn't one to show
    (no reference yet, or a whole chapter, which is left as a reference)."""
    return verse_texts.get(block.get("ref") or "")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def to_markdown(note: dict, verse_texts: dict[str, str], translation: str, image_files: dict[str, str] | None = None) -> str:
    """The note as Markdown. `image_files` maps a photo's storage path to the
    file name it has beside the Markdown (the zip export); without it a photo
    is written as its caption, since a lone .md file can't carry the image."""
    lines = [f"# {note_title(note)}", ""]
    meta = meta_line(note)
    if meta:
        lines += [f"*{meta}*", ""]
    if note.get("series"):
        lines.append(f"Series: {note['series']}  ")
    if note.get("passage_ref"):
        lines.append(f"Main passage: {note['passage_ref']}")
    lines.append("")

    for block in note.get("blocks") or []:
        kind = block.get("type")
        if kind == "text" and block.get("text", "").strip():
            lines += [block["text"].strip(), ""]
        elif kind == "heading" and block.get("text", "").strip():
            lines += [f"## {block['text'].strip()}", ""]
        elif kind == "verse" and block.get("ref"):
            text = _verse_line(block, verse_texts)
            lines += ([f"> {text}", ">"] if text else []) + [f"> {block['ref']} ({translation})", ""]
        elif kind == "image" and block.get("path"):
            caption = block.get("caption", "").strip() or "Photo"
            name = (image_files or {}).get(block["path"])
            lines += [f"![{caption}]({name})" if name else f"*[Photo: {caption}]*", ""]
        elif kind == "quote" and block.get("text", "").strip():
            lines.append(f"> **{block['text'].strip()}**")
            if block.get("who", "").strip():
                lines.append(f"> {block['who'].strip()}")
            lines.append("")
        elif kind == "todo":
            items = [i for i in block.get("items") or [] if i.get("text", "").strip()]
            if items:
                lines.append("**To live it out**")
                lines += [f"- [{'x' if i.get('done') else ' '}] {i['text'].strip()}" for i in items]
                lines.append("")
        elif kind == "link" and block.get("url"):
            lines += [f"[{block.get('label') or block['url']}]({block['url']})", ""]

    if note.get("passages"):
        lines += ["---", f"Passages: {', '.join(note['passages'])}"]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _para(text: str) -> str:
    """Plain text made safe for a reportlab Paragraph, which reads markup."""
    return escape(text).replace("\n", "<br/>")


def render_pdf(note: dict, verse_texts: dict[str, str], translation: str, images: dict[str, bytes]) -> bytes:
    """`images` maps a photo's storage path to its bytes; a photo that
    couldn't be read is left out rather than failing the whole export."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                            leftMargin=0.9 * inch, rightMargin=0.9 * inch, title=note_title(note))
    styles = getSampleStyleSheet()
    body = ParagraphStyle("SermonBody", parent=styles["BodyText"], fontSize=11, leading=16, spaceAfter=8)
    meta = ParagraphStyle("SermonMeta", parent=body, textColor=_MUTED, fontSize=10, leading=14)
    point = ParagraphStyle("SermonPoint", parent=styles["Heading2"], fontSize=14, spaceBefore=8, spaceAfter=6)
    verse = ParagraphStyle("SermonVerse", parent=body, fontName="Times-Italic", fontSize=12.5, leading=18, spaceAfter=4)
    ref = ParagraphStyle("SermonRef", parent=meta, textColor=_EMBER, fontName="Helvetica-Bold", spaceAfter=0)
    quote = ParagraphStyle("SermonQuote", parent=body, fontName="Helvetica-Bold", fontSize=12.5, leading=18, leftIndent=14, spaceAfter=2)
    who = ParagraphStyle("SermonWho", parent=meta, leftIndent=14)
    caption = ParagraphStyle("SermonCaption", parent=meta, fontName="Helvetica-Oblique", spaceBefore=4)
    label = ParagraphStyle("SermonLabel", parent=meta, fontName="Helvetica-Bold", textColor=_MUTED, spaceAfter=4)

    story = [Paragraph(_para(note_title(note)), styles["Title"])]
    details = [meta_line(note)]
    if note.get("series"):
        details.append(f"Series: {note['series']}")
    if note.get("passage_ref"):
        details.append(f"Main passage: {note['passage_ref']}")
    story += [Paragraph(_para(d), meta) for d in details if d]
    story.append(Spacer(1, 12))

    for block in note.get("blocks") or []:
        kind = block.get("type")
        if kind == "text" and block.get("text", "").strip():
            story.append(Paragraph(_para(block["text"].strip()), body))
        elif kind == "heading" and block.get("text", "").strip():
            story.append(Paragraph(_para(block["text"].strip()), point))
        elif kind == "verse" and block.get("ref"):
            text = _verse_line(block, verse_texts)
            cell = ([Paragraph(_para(f"“{text}”"), verse)] if text else []) + [Paragraph(_para(f"{block['ref']} · {translation}"), ref)]
            box = Table([[cell]], colWidths=[doc.width])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), _WARM), ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]))
            story += [box, Spacer(1, 10)]
        elif kind == "image" and block.get("path") in images:
            try:
                data = images[block["path"]]
                width, height = ImageReader(BytesIO(data)).getSize()
                scale = min(doc.width / width, (4.5 * inch) / height, 1.0)
                story.append(Image(BytesIO(data), width=width * scale, height=height * scale))
            except Exception:
                continue  # an unreadable photo is skipped, not fatal
            if block.get("caption", "").strip():
                story.append(Paragraph(_para(block["caption"].strip()), caption))
            story.append(Spacer(1, 10))
        elif kind == "quote" and block.get("text", "").strip():
            story.append(Paragraph(_para(f"“{block['text'].strip()}”"), quote))
            if block.get("who", "").strip():
                story.append(Paragraph(_para(block["who"].strip()), who))
            story.append(Spacer(1, 8))
        elif kind == "todo":
            items = [i for i in block.get("items") or [] if i.get("text", "").strip()]
            if items:
                story.append(Paragraph("To live it out", label))
                for item in items:
                    done = " (done)" if item.get("done") else ""
                    story.append(Paragraph(_para(f"•  {item['text'].strip()}{done}"), body))
        elif kind == "link" and block.get("url"):
            name = escape(block.get("label") or block["url"])
            url = escape(block["url"], {'"': "&quot;"})
            story.append(Paragraph(f'<link href="{url}" color="#B5541C">{name}</link> <font color="#6B5A49" size="9">{escape(block["url"])}</font>', body))

    if note.get("passages"):
        story += [Spacer(1, 10), Paragraph(_para(f"Passages: {', '.join(note['passages'])}"), meta)]
    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------
def render_docx(note: dict, verse_texts: dict[str, str], translation: str, images: dict[str, bytes]) -> bytes:
    """Same content as the PDF, in a document the person can keep editing."""
    doc = Document()
    doc.add_heading(note_title(note), level=0)
    details = [meta_line(note)]
    if note.get("series"):
        details.append(f"Series: {note['series']}")
    if note.get("passage_ref"):
        details.append(f"Main passage: {note['passage_ref']}")
    for line in filter(None, details):
        doc.add_paragraph().add_run(line).italic = True

    for block in note.get("blocks") or []:
        kind = block.get("type")
        if kind == "text" and block.get("text", "").strip():
            doc.add_paragraph(block["text"].strip())
        elif kind == "heading" and block.get("text", "").strip():
            doc.add_heading(block["text"].strip(), level=2)
        elif kind == "verse" and block.get("ref"):
            text = _verse_line(block, verse_texts)
            para = doc.add_paragraph(style="Quote")
            if text:
                para.add_run(f"“{text}”\n")
            para.add_run(f"{block['ref']} · {translation}").bold = True
        elif kind == "image" and block.get("path") in images:
            try:
                doc.add_picture(BytesIO(images[block["path"]]), width=Inches(5.8))
            except Exception:
                continue  # python-docx reads JPEG and PNG; anything else is skipped
            if block.get("caption", "").strip():
                run = doc.add_paragraph().add_run(block["caption"].strip())
                run.italic = True
                run.font.size = Pt(9.5)
        elif kind == "quote" and block.get("text", "").strip():
            para = doc.add_paragraph(style="Intense Quote")
            para.add_run(f"“{block['text'].strip()}”")
            if block.get("who", "").strip():
                para.add_run(f"\n{block['who'].strip()}").italic = True
        elif kind == "todo":
            items = [i for i in block.get("items") or [] if i.get("text", "").strip()]
            if items:
                doc.add_paragraph().add_run("To live it out").bold = True
                for item in items:
                    box = _BOX_DONE if item.get("done") else _BOX_OPEN
                    doc.add_paragraph(f"{box} {item['text'].strip()}", style="List Bullet")
        elif kind == "link" and block.get("url"):
            para = doc.add_paragraph()
            para.add_run(block.get("label") or block["url"]).bold = True
            para.add_run(f"  {block['url']}")

    if note.get("passages"):
        doc.add_paragraph().add_run(f"Passages: {', '.join(note['passages'])}").italic = True
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
