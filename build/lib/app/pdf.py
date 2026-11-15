"""Renders a stored reading plan as a downloadable PDF.

Kept separate from app/plan.py (pure scheduling logic): this module's only
job is layout, so swapping the PDF library later never touches how the
schedule itself is generated.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.plan import plan_title

_BRASS = colors.HexColor("#8a6d3f")
_LINE = colors.HexColor("#ddd3bf")
_PAPER = colors.HexColor("#f6f2e9")


def render_plan_pdf(plan: dict) -> bytes:
    """`plan` is a reading_plans row: start_date, days, translation, overview, schedule, and title if it has one."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER, topMargin=0.75 * inch, bottomMargin=0.75 * inch
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("PlanTitle", parent=styles["Title"], spaceAfter=6)
    cell_style = ParagraphStyle("PlanCell", parent=styles["BodyText"], fontSize=9, leading=11)

    story = [
        # Paragraph reads its text as markup, so a title the model wrote is escaped.
        Paragraph(escape(plan_title(plan)), title_style),
        Paragraph(
            f"Starting {plan['start_date']}, {plan['translation']} translation",
            styles["BodyText"],
        ),
        Spacer(1, 12),
        Paragraph(escape(plan["overview"]), styles["BodyText"]),
        Spacer(1, 18),
    ]

    # Plain strings in a Table cell don't wrap, so a long reading list would
    # get clipped instead of flowing to a second line. Paragraph cells wrap
    # to the column width like any other reportlab flowable.
    rows = [["Day", "Date", "Reading"]]
    for entry in plan["schedule"]:
        rows.append(
            [
                str(entry["day"]),
                str(entry["date"]),
                Paragraph(", ".join(entry["references"]), cell_style),
            ]
        )

    table = Table(rows, colWidths=[0.6 * inch, 1.1 * inch, 4.8 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _BRASS),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _PAPER]),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buffer.getvalue()
