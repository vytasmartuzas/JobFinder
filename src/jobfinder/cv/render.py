"""Fixed CV template — renders structured content to a PDF with a stable layout.

This is the *template* half of the CV: the layout here is constant, and only the
``CVContent`` passed in changes. Built on fpdf2 (pure Python, no native libraries or
headless browser) so it runs anywhere ``uv sync`` runs.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .content import CVContent

# Layout constants (mm) and palette (RGB).
MARGIN_X = 16.0
MARGIN_TOP = 12.0
MARGIN_BOTTOM = 14.0

NAVY = (31, 48, 71)       # name
STEEL = (47, 74, 107)     # section headers
GRAY = (96, 102, 110)     # dates, role, contact lines
RULE = (172, 180, 188)    # horizontal rules
BODY = (34, 38, 43)       # body text

FONT = "Helvetica"


def _safe(text: str) -> str:
    """Guarantee a core-font-renderable string (WinAnsi/cp1252), never crash."""
    return text.encode("cp1252", "replace").decode("cp1252")


class _CVDocument(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4")
        self.core_fonts_encoding = "cp1252"
        self.set_margins(MARGIN_X, MARGIN_TOP, MARGIN_X)
        self.set_auto_page_break(True, margin=MARGIN_BOTTOM)
        self.add_page()

    # --- primitives -----------------------------------------------------------
    def _rule(self, gap_before: float = 1.0, gap_after: float = 2.0) -> None:
        self.ln(gap_before)
        y = self.get_y()
        self.set_draw_color(*RULE)
        self.set_line_width(0.3)
        self.line(self.l_margin, y, self.l_margin + self.epw, y)
        self.ln(gap_after)

    def _page_break_guard(self, needed: float = 7.0) -> None:
        if self.get_y() + needed > self.h - self.b_margin:
            self.add_page()

    def section(self, title: str) -> None:
        self.ln(2.0)
        self.set_font(FONT, "B", 11)
        self.set_text_color(*STEEL)
        self.cell(0, 6, _safe(title.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self._rule(gap_before=0.5, gap_after=2.0)

    def entry_header(self, left: str, right: str) -> None:
        self._page_break_guard()
        y = self.get_y()
        self.set_font(FONT, "", 9.5)
        date_w = self.get_string_width(_safe(right)) + 2 if right else 0
        self.set_font(FONT, "B", 10.5)
        self.set_text_color(*BODY)
        self.cell(self.epw - date_w, 5.2, _safe(left), new_x=XPos.RIGHT, new_y=YPos.TOP)
        if right:
            self.set_font(FONT, "", 9.5)
            self.set_text_color(*GRAY)
            self.cell(date_w, 5.2, _safe(right), align="R",
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            self.ln(5.2)
        self.set_xy(self.l_margin, y + 5.2)

    def italic_line(self, text: str) -> None:
        self.set_font(FONT, "I", 9.5)
        self.set_text_color(*GRAY)
        self.cell(0, 4.6, _safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def sublabel(self, text: str) -> None:
        self.set_font(FONT, "B", 9.5)
        self.set_text_color(*BODY)
        self.cell(0, 4.8, _safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullets(self, items: list[str]) -> None:
        self.set_text_color(*BODY)
        bullet_x = self.l_margin + 3.5
        text_x = bullet_x + 3.0
        text_w = self.epw - (text_x - self.l_margin)
        for item in items:
            self._page_break_guard()
            y = self.get_y()
            self.set_font(FONT, "", 9.5)
            self.set_xy(bullet_x, y)
            self.cell(3.0, 4.6, "•", new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.set_xy(text_x, y)
            self.multi_cell(text_w, 4.6, _safe(item),
                            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(self.l_margin)

    def paragraph(self, text: str) -> None:
        self.set_font(FONT, "", 9.5)
        self.set_text_color(*BODY)
        self.multi_cell(0, 4.9, _safe(text), align="J",
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def skills_table(self, rows: list[tuple[str, str]]) -> None:
        # Size the category column to the widest label so categories stay on one
        # line; the items column wraps in the remaining width.
        self.set_font(FONT, "B", 9.5)
        widest = max((self.get_string_width(_safe(c)) for c, _ in rows), default=0)
        cat_w = min(widest + 5.0, self.epw - 60.0)
        items_w = self.epw - cat_w
        for category, items in rows:
            self._page_break_guard()
            y0 = self.get_y()
            self.set_font(FONT, "B", 9.5)
            self.set_text_color(*BODY)
            self.set_xy(self.l_margin, y0)
            self.cell(cat_w, 4.6, _safe(category), new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.set_font(FONT, "", 9.5)
            self.set_xy(self.l_margin + cat_w, y0)
            self.multi_cell(items_w, 4.6, _safe(items),
                            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_y(self.get_y() + 1.4)


def render_cv_pdf(content: CVContent, out_path: str | Path) -> Path:
    """Render `content` to a PDF at `out_path` using the fixed template."""
    doc = _CVDocument()

    # Header: name + contact lines, then a rule.
    doc.set_font(FONT, "B", 20)
    doc.set_text_color(*NAVY)
    doc.cell(0, 9, _safe(content.name), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_font(FONT, "", 8.5)
    doc.set_text_color(*GRAY)
    for line in content.contact_lines:
        doc.cell(0, 4.4, _safe(line), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc._rule(gap_before=1.5, gap_after=2.5)

    if content.summary:
        doc.paragraph(content.summary)

    if content.education:
        doc.section("Education")
        for edu in content.education:
            doc.entry_header(edu.institution, edu.dates)
            if edu.degree:
                doc.italic_line(edu.degree)
            if edu.modules:
                doc.sublabel("Relevant Modules:")
                doc.bullets(edu.modules)
            if edu.projects:
                doc.sublabel("Key Projects:")
                doc.bullets(edu.projects)

    if content.certifications:
        doc.section("Certifications")
        for cert in content.certifications:
            doc.entry_header(cert.title, cert.date)
            doc.bullets(cert.bullets)
            doc.ln(1.0)

    if content.skills:
        doc.section("Technical Skills")
        doc.skills_table([(s.category, s.items) for s in content.skills])

    if content.experience:
        doc.section("Career History")
        for job in content.experience:
            doc.entry_header(job.organization, job.dates)
            if job.role:
                doc.italic_line(job.role)
            doc.bullets(job.bullets)
            doc.ln(1.5)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.output(str(out))
    return out
