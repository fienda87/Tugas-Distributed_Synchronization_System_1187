from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("**", "")
        .replace("`", "")
    )


def _inline(text: str) -> str:
    text = _escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<font name='Courier'>\1</font>", text)
    return text


def _is_table(lines: list[str], idx: int) -> bool:
    return (
        idx + 1 < len(lines)
        and lines[idx].strip().startswith("|")
        and lines[idx + 1].strip().startswith("|")
        and "---" in lines[idx + 1]
    )


def _parse_table(lines: list[str], idx: int):
    rows: list[list[str]] = []
    while idx < len(lines) and lines[idx].strip().startswith("|"):
        line = lines[idx].strip().strip("|")
        cells = [c.strip() for c in line.split("|")]
        if not all(set(c.replace(":", "").strip()) <= {"-"} for c in cells):
            rows.append([_escape(c) for c in cells])
        idx += 1
    return rows, idx


def markdown_to_flowables(markdown: str):
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=23,
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyJustify",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.4,
            alignment=4,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.4,
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallCode",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=7.2,
            leading=9,
            backColor=colors.whitesmoke,
            borderColor=colors.lightgrey,
            borderWidth=0.25,
            borderPadding=4,
            spaceBefore=4,
            spaceAfter=6,
        )
    )

    lines = markdown.splitlines()
    story = []
    idx = 0
    in_code = False
    code: list[str] = []

    while idx < len(lines):
        raw = lines[idx]
        line = raw.rstrip()

        if line.startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code), styles["SmallCode"]))
                code = []
                in_code = False
            else:
                in_code = True
            idx += 1
            continue

        if in_code:
            code.append(raw)
            idx += 1
            continue

        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 0.08 * cm))
            idx += 1
            continue

        if stripped == "---":
            story.append(PageBreak())
            idx += 1
            continue

        if _is_table(lines, idx):
            rows, idx = _parse_table(lines, idx)
            if rows:
                table = Table(rows, repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                            ("FONTSIZE", (0, 0), (-1, -1), 7.4),
                            ("LEADING", (0, 0), (-1, -1), 8.6),
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 3),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 0.2 * cm))
            continue

        if stripped.startswith("# "):
            story.append(Paragraph(_inline(stripped[2:]), styles["ReportTitle"]))
        elif stripped.startswith("## "):
            story.append(Paragraph(_inline(stripped[3:]), styles["Section"]))
        elif stripped.startswith("### "):
            story.append(Paragraph(_inline(stripped[4:]), styles["SubSection"]))
        elif stripped.startswith("- "):
            story.append(Paragraph(f"- {_inline(stripped[2:])}", styles["BulletBody"]))
        elif re.match(r"^\d+\. ", stripped):
            story.append(Paragraph(_inline(stripped), styles["BulletBody"]))
        else:
            story.append(Paragraph(_inline(stripped), styles["BodyJustify"]))

        idx += 1

    return story


def build_pdf(src: Path, dst: Path) -> None:
    doc = SimpleDocTemplate(
        str(dst),
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Tugas 2 - Distributed Synchronization System",
        author="[Nama Mahasiswa]",
    )
    story = markdown_to_flowables(src.read_text(encoding="utf-8"))
    doc.build(story)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/md_to_pdf.py input.md output.pdf")
    build_pdf(Path(sys.argv[1]), Path(sys.argv[2]))
