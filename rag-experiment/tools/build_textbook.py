"""인공지능 입문 교재 PDF 생성기.

tools/content_part{1..4}.py 의 CHAPTERS(16개 장)를 읽어
data/raw/인공지능_입문_교재.pdf 로 렌더링한다.

- 한국어 TTF(Malgun Gothic)를 임베딩 → pdfplumber로 정상 텍스트 추출 보장(mojibake 방지)
- 목차(페이지 번호 포함), 부/장/절 구조, 예시·수식·의사코드 박스, 장 요약, 핵심 용어 표

실행:  python tools/build_textbook.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "raw" / "인공지능_입문_교재.pdf"
BOOK_TITLE = "인공지능 입문"
BOOK_SUBTITLE = "기초 개념부터 딥러닝, 트랜스포머와 RAG까지"

FONT_DIR = Path("C:/Windows/Fonts")
FONT_REGULAR = "Malgun"
FONT_BOLD = "Malgun-Bold"


# ── 폰트 등록 ──────────────────────────────────────────────────────────
def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(FONT_DIR / "malgun.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_DIR / "malgunbd.ttf")))
    pdfmetrics.registerFontFamily(
        FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD,
        italic=FONT_REGULAR, boldItalic=FONT_BOLD,
    )


# ── 콘텐츠 로드 ────────────────────────────────────────────────────────
def load_chapters() -> list[dict]:
    chapters: list[dict] = []
    for i in range(1, 5):
        path = Path(__file__).resolve().parent / f"content_part{i}.py"
        spec = importlib.util.spec_from_file_location(f"content_part{i}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        chapters.extend(module.CHAPTERS)
    chapters.sort(key=lambda c: c["num"])
    return chapters


# ── 스타일 ─────────────────────────────────────────────────────────────
def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    styles["body"] = ParagraphStyle(
        "body", parent=base["Normal"], fontName=FONT_REGULAR,
        fontSize=10.5, leading=17, alignment=TA_JUSTIFY,
        spaceAfter=7, firstLineIndent=10,
    )
    styles["intro"] = ParagraphStyle(
        "intro", parent=styles["body"], textColor=colors.HexColor("#333333"),
        leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=12,
        firstLineIndent=0, fontSize=10.5, leading=17,
    )
    styles["part_num"] = ParagraphStyle(
        "part_num", parent=base["Normal"], fontName=FONT_BOLD,
        fontSize=15, textColor=colors.HexColor("#1a5276"), alignment=TA_CENTER,
        spaceAfter=6,
    )
    styles["part_title"] = ParagraphStyle(
        "part_title", parent=base["Normal"], fontName=FONT_BOLD,
        fontSize=26, textColor=colors.HexColor("#0b3d5c"), alignment=TA_CENTER,
        leading=32,
    )
    styles["chapter_num"] = ParagraphStyle(
        "chapter_num", parent=base["Normal"], fontName=FONT_BOLD,
        fontSize=12, textColor=colors.HexColor("#2471a3"), spaceAfter=2,
    )
    styles["chapter_title"] = ParagraphStyle(
        "chapter_title", parent=base["Normal"], fontName=FONT_BOLD,
        fontSize=21, textColor=colors.HexColor("#0b3d5c"), leading=26,
        spaceAfter=10,
    )
    styles["section"] = ParagraphStyle(
        "section", parent=base["Normal"], fontName=FONT_BOLD,
        fontSize=13.5, textColor=colors.HexColor("#154360"), leading=18,
        spaceBefore=12, spaceAfter=5,
    )
    styles["heading_box"] = ParagraphStyle(
        "heading_box", parent=base["Normal"], fontName=FONT_BOLD,
        fontSize=10.5, textColor=colors.HexColor("#7d3c00"), spaceAfter=3,
    )
    styles["example"] = ParagraphStyle(
        "example", parent=styles["body"], fontSize=10, leading=16,
        firstLineIndent=0, textColor=colors.HexColor("#4a3b1a"),
        leftIndent=8, rightIndent=8,
    )
    styles["formula"] = ParagraphStyle(
        "formula", parent=base["Normal"], fontName=FONT_REGULAR,
        fontSize=11, leading=17, alignment=TA_CENTER,
        textColor=colors.HexColor("#0b3d5c"), spaceBefore=2, spaceAfter=2,
    )
    styles["code"] = ParagraphStyle(
        "code", parent=base["Normal"], fontName=FONT_REGULAR,
        fontSize=9, leading=13, textColor=colors.HexColor("#1b2631"),
        leftIndent=6,
    )
    styles["summary"] = ParagraphStyle(
        "summary", parent=styles["body"], fontSize=10, leading=15,
        firstLineIndent=0, leftIndent=14, bulletIndent=4, spaceAfter=4,
    )
    styles["term"] = ParagraphStyle(
        "term", parent=base["Normal"], fontName=FONT_BOLD, fontSize=9.5,
        leading=13, textColor=colors.HexColor("#154360"),
    )
    styles["term_desc"] = ParagraphStyle(
        "term_desc", parent=base["Normal"], fontName=FONT_REGULAR, fontSize=9.5,
        leading=13, alignment=TA_LEFT,
    )
    styles["title_main"] = ParagraphStyle(
        "title_main", parent=base["Normal"], fontName=FONT_BOLD, fontSize=40,
        alignment=TA_CENTER, textColor=colors.HexColor("#0b3d5c"), leading=48,
    )
    styles["title_sub"] = ParagraphStyle(
        "title_sub", parent=base["Normal"], fontName=FONT_REGULAR, fontSize=15,
        alignment=TA_CENTER, textColor=colors.HexColor("#2471a3"), leading=22,
    )
    styles["title_foot"] = ParagraphStyle(
        "title_foot", parent=base["Normal"], fontName=FONT_REGULAR, fontSize=11,
        alignment=TA_CENTER, textColor=colors.HexColor("#555555"), leading=18,
    )
    styles["toc_h"] = ParagraphStyle(
        "toc_h", parent=base["Normal"], fontName=FONT_BOLD, fontSize=18,
        textColor=colors.HexColor("#0b3d5c"), spaceAfter=12,
    )
    return styles


# ── 문서 템플릿 (목차 notify + 페이지 번호) ───────────────────────────
class BookDoc(BaseDocTemplate):
    def afterFlowable(self, flowable) -> None:
        if not hasattr(flowable, "style"):
            return
        name = flowable.style.name
        text = flowable.getPlainText()
        if name == "part_title":
            self.notify("TOCEntry", (0, text, self.page))
        elif name == "chapter_title":
            self.notify("TOCEntry", (1, text, self.page))
        elif name == "section":
            self.notify("TOCEntry", (2, text, self.page))


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT_REGULAR, 8.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    w, _ = A4
    if doc.page > 1:
        canvas.drawCentredString(w / 2.0, 1.1 * cm, str(doc.page))
        canvas.drawString(2 * cm, 1.1 * cm, BOOK_TITLE)
    canvas.restoreState()


def _blank(canvas, doc) -> None:  # 표지 전용(번호 없음)
    pass


# ── 플로어블 빌더 ──────────────────────────────────────────────────────
def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def key_terms_table(terms: list[dict], st: dict) -> Table:
    rows = [[p(t["term"], st["term"]), p(t.get("desc", ""), st["term_desc"])] for t in terms]
    tbl = Table(rows, colWidths=[5.0 * cm, 11.0 * cm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e0e0e0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 2),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f8fb")),
    ]))
    return tbl


def boxed(flowables: list, bg: str, border: str) -> Table:
    tbl = Table([[flowables]], colWidths=[16.4 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def section_flowables(sec: dict, st: dict) -> list:
    out: list = [p(sec["title"], st["section"])]
    for para in sec.get("paras", []):
        out.append(p(para, st["body"]))
    if sec.get("formula"):
        inner = [p("수식", st["heading_box"])]
        for line in str(sec["formula"]).split("\n"):
            inner.append(p(line, st["formula"]))
        out.append(Spacer(1, 3))
        out.append(boxed(inner, "#f0f6fb", "#c5d9e8"))
        out.append(Spacer(1, 4))
    if sec.get("example"):
        inner = [p("예시", st["heading_box"]), p(sec["example"], st["example"])]
        out.append(Spacer(1, 3))
        out.append(boxed(inner, "#fdf8ee", "#e8d9b5"))
        out.append(Spacer(1, 4))
    if sec.get("code"):
        inner = [p("의사코드", st["heading_box"]),
                 Preformatted(escape(str(sec["code"])), st["code"])]
        out.append(Spacer(1, 3))
        out.append(boxed(inner, "#f5f7f8", "#d5dbdf"))
        out.append(Spacer(1, 4))
    return out


def chapter_flowables(ch: dict, st: dict, prev_part: str | None) -> tuple[list, str]:
    out: list = []
    part = ch.get("part", "")
    if part != prev_part:
        # 부 표지 페이지
        out.append(NextPageTemplate("plain"))
        out.append(PageBreak())
        out.append(Spacer(1, 7 * cm))
        part_no = part.split(" ")[0] if part else ""
        part_name = part[len(part_no):].strip() if part_no else part
        out.append(p(part_no, st["part_num"]))
        out.append(p(part_name, st["part_title"]))
        out.append(NextPageTemplate("body"))
    out.append(PageBreak())
    out.append(p(f"제{ch['num']}장", st["chapter_num"]))
    out.append(p(ch["title"], st["chapter_title"]))
    if ch.get("intro"):
        out.append(boxed([p(ch["intro"], st["intro"])], "#eef4f9", "#cfe0ee"))
        out.append(Spacer(1, 8))
    for sec in ch.get("sections", []):
        out.extend(section_flowables(sec, st))
    # 장 요약
    if ch.get("summary"):
        out.append(Spacer(1, 8))
        summ: list = [p("이 장의 요약", st["heading_box"])]
        for item in ch["summary"]:
            summ.append(Paragraph("• " + escape(str(item)), st["summary"]))
        out.append(boxed(summ, "#f2f9f2", "#c9e2c9"))
    # 핵심 용어
    if ch.get("key_terms"):
        out.append(Spacer(1, 10))
        out.append(p("핵심 용어", st["section"]))
        out.append(key_terms_table(ch["key_terms"], st))
    return out, part


def title_page(st: dict) -> list:
    return [
        Spacer(1, 5.5 * cm),
        p(BOOK_TITLE, st["title_main"]),
        Spacer(1, 0.6 * cm),
        p(BOOK_SUBTITLE, st["title_sub"]),
        Spacer(1, 9 * cm),
        p("인공지능 · 머신러닝 · 딥러닝 · LLM · RAG", st["title_foot"]),
        p("입문자를 위한 종합 개념 교재", st["title_foot"]),
    ]


def toc_flowables(st: dict) -> list:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc0", fontName=FONT_BOLD, fontSize=12, leading=20,
                       textColor=colors.HexColor("#0b3d5c"), spaceBefore=8),
        ParagraphStyle("toc1", fontName=FONT_REGULAR, fontSize=10.5, leading=16,
                       leftIndent=12),
        ParagraphStyle("toc2", fontName=FONT_REGULAR, fontSize=9.5, leading=13,
                       leftIndent=28, textColor=colors.HexColor("#555555")),
    ]
    return [p("목  차", st["toc_h"]), toc]


# ── 메인 ───────────────────────────────────────────────────────────────
def build() -> None:
    register_fonts()
    st = build_styles()
    chapters = load_chapters()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BookDoc(
        str(OUT_PATH), pagesize=A4,
        leftMargin=2.3 * cm, rightMargin=2.3 * cm,
        topMargin=2.2 * cm, bottomMargin=2.0 * cm,
        title=BOOK_TITLE, author="AI Textbook Generator",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([
        PageTemplate(id="plain", frames=[frame], onPage=_blank),
        PageTemplate(id="body", frames=[frame], onPage=_footer),
    ])

    story: list = []
    story.append(NextPageTemplate("plain"))
    story.extend(title_page(st))
    story.append(PageBreak())
    story.extend(toc_flowables(st))
    story.append(NextPageTemplate("body"))

    prev_part: str | None = None
    for ch in chapters:
        flows, prev_part = chapter_flowables(ch, st, prev_part)
        story.extend(flows)

    doc.multiBuild(story)
    print(f"생성 완료: {OUT_PATH}  ({len(chapters)}개 장)")


if __name__ == "__main__":
    build()
