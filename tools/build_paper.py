"""Renders paper/whitepaper.md to an A4 academic PDF.

Deliberately a small hand-rolled Markdown subset rather than a general converter:
the paper uses headings, paragraphs, fenced code, tables, bullet and numbered
lists, and nothing else. Running header and page numbers are drawn on a canvas
callback.
"""
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph,
    Preformatted, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "paper" / "whitepaper.md"
OUT = ROOT / "paper" / "whitepaper.pdf"

RUNNING_HEAD = "Measuring What Was Said, Not Only How It Sounded"
SERIF, SERIF_B, SERIF_I = "Times-Roman", "Times-Bold", "Times-Italic"
MONO = "Courier"


def styles() -> dict:
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", parent=base["Title"], fontName=SERIF_B,
                                fontSize=17, leading=21, spaceAfter=8)
    s["subtitle"] = ParagraphStyle("subtitle", parent=base["Normal"], fontName=SERIF_I,
                                   fontSize=11.5, leading=15, alignment=TA_CENTER,
                                   spaceAfter=14)
    s["authors"] = ParagraphStyle("authors", parent=base["Normal"], fontName=SERIF,
                                  fontSize=10, leading=14, alignment=TA_CENTER,
                                  spaceAfter=18)
    s["h1"] = ParagraphStyle("h1", parent=base["Normal"], fontName=SERIF_B,
                             fontSize=13, leading=16, spaceBefore=16, spaceAfter=7,
                             keepWithNext=1)
    s["h2"] = ParagraphStyle("h2", parent=base["Normal"], fontName=SERIF_B,
                             fontSize=11, leading=14, spaceBefore=11, spaceAfter=5,
                             keepWithNext=1)
    s["h3"] = ParagraphStyle("h3", parent=base["Normal"], fontName=SERIF_I,
                             fontSize=10.5, leading=13, spaceBefore=9, spaceAfter=4,
                             keepWithNext=1)
    s["body"] = ParagraphStyle("body", parent=base["Normal"], fontName=SERIF,
                               fontSize=9.8, leading=13.4, alignment=TA_JUSTIFY,
                               spaceAfter=6)
    s["bullet"] = ParagraphStyle("bullet", parent=s["body"], leftIndent=11,
                                 bulletIndent=2, spaceAfter=3)
    s["code"] = ParagraphStyle("code", parent=base["Code"], fontName=MONO,
                               fontSize=6.6, leading=8.0, textColor=colors.HexColor("#1a1a1a"))
    s["cell"] = ParagraphStyle("cell", parent=base["Normal"], fontName=SERIF,
                               fontSize=8.4, leading=10.6)
    s["cellh"] = ParagraphStyle("cellh", parent=s["cell"], fontName=SERIF_B)
    s["ref"] = ParagraphStyle("ref", parent=s["body"], leftIndent=13, firstLineIndent=-13,
                              alignment=TA_JUSTIFY, spaceAfter=5)
    return s


def inline(text: str) -> str:
    """Markdown emphasis and code spans to reportlab inline markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.6">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = text.replace("—", "&#8212;").replace("–", "&#8211;")
    text = text.replace("“", "&#8220;").replace("”", "&#8221;")
    text = text.replace("’", "&#8217;").replace("‘", "&#8216;")
    return text


def build_table(rows: list[list[str]], st: dict) -> Table:
    header, *body = rows
    data = [[Paragraph(inline(c), st["cellh"]) for c in header]]
    data += [[Paragraph(inline(c), st["cell"]) for c in r] for r in body]

    ncols = len(header)
    avail = 168 * mm
    # First column carries the label; give it more room when there are few columns.
    if ncols == 2:
        widths = [avail * 0.42, avail * 0.58]
    elif ncols == 3:
        widths = [avail * 0.34, avail * 0.33, avail * 0.33]
    else:
        widths = [avail / ncols] * ncols

    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f3f1")]),
    ]))
    return t


def parse(md: str, st: dict) -> list:
    flow, lines, i = [], md.split("\n"), 0
    in_title_block = True

    while i < len(lines):
        line = lines[i]

        # fenced code
        if line.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            flow.append(Spacer(1, 3))
            flow.append(Preformatted("\n".join(block), st["code"]))
            flow.append(Spacer(1, 6))
            continue

        # tables
        if line.startswith("|") and i + 1 < len(lines) and set(lines[i + 1]) <= set("|-: "):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not set("".join(cells)) <= set("-: "):
                    rows.append(cells)
                i += 1
            flow.append(Spacer(1, 3))
            flow.append(build_table(rows, st))
            flow.append(Spacer(1, 8))
            continue

        stripped = line.strip()

        if stripped == "---":
            i += 1
            continue

        if stripped.startswith("#### ") or stripped.startswith("### "):
            level = 3 if stripped.startswith("### ") else 3
            text = stripped.lstrip("#").strip()
            if in_title_block:
                flow.append(Paragraph(inline(text), st["subtitle"]))
            else:
                flow.append(Paragraph(inline(text), st["h3"]))
            i += 1
            continue

        if stripped.startswith("## "):
            in_title_block = False
            flow.append(Paragraph(inline(stripped[3:].strip()), st["h1"]))
            i += 1
            continue

        if stripped.startswith("# "):
            flow.append(Paragraph(inline(stripped[2:].strip()), st["title"]))
            i += 1
            continue

        if re.match(r"^\d+\.\s", stripped):
            num, text = stripped.split(". ", 1)
            style = st["ref"] if "References" in "".join(l for l in lines[max(0, i - 40):i] if l.startswith("## ")) else st["bullet"]
            flow.append(Paragraph(inline(text), style, bulletText=f"{num}."))
            i += 1
            continue

        if stripped.startswith("- "):
            flow.append(Paragraph(inline(stripped[2:]), st["bullet"], bulletText="•"))
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        # paragraph: gather until blank or a structural line
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith(("#", "|", "```", "- ", "---")) or re.match(r"^\d+\.\s", nxt):
                break
            para.append(nxt)
            i += 1

        text = " ".join(para)
        style = st["authors"] if in_title_block and "@" in text else st["body"]
        flow.append(Paragraph(inline(text), style))

    return flow


def decorate(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setFont(SERIF_I, 7.8)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(21 * mm, A4[1] - 13 * mm, RUNNING_HEAD)
        canvas.drawRightString(A4[0] - 21 * mm, A4[1] - 13 * mm, "Ansari & Krishnan")
        canvas.setStrokeColor(colors.HexColor("#bbbbbb"))
        canvas.setLineWidth(0.4)
        canvas.line(21 * mm, A4[1] - 15 * mm, A4[0] - 21 * mm, A4[1] - 15 * mm)
    canvas.setFont(SERIF, 8.6)
    canvas.setFillColor(colors.HexColor("#333333"))
    canvas.drawCentredString(A4[0] / 2, 12 * mm, str(doc.page))
    canvas.restoreState()


def main() -> int:
    st = styles()
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=21 * mm, rightMargin=21 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="Measuring What Was Said, Not Only How It Sounded",
        author="Almas Ansari; Haresh Krishnan",
        subject="Architecture of a hybrid deterministic/generative speech assessment system",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=decorate)])
    doc.build(parse(SRC.read_text(encoding="utf-8"), st))
    print(f"  wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
