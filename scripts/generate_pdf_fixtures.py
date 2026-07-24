"""Generate committed PDF fixtures for formal evaluation."""

from __future__ import annotations

from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "tests" / "fixtures" / "pdf"


def _save(document: fitz.Document, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    document.close()


def _pass_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 80), "Heading", fontsize=14, fontname="tibo")
    for index in range(8):
        page.insert_text(
            (100, 120 + index * 21),
            f"Body line {index} with enough text for spacing checks.",
            fontsize=14,
            fontname="tiro",
        )
    _save(document, path)


def _wrong_font_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 120), "Body only", fontsize=14, fontname="helv")
    _save(document, path)


def _non_bold_heading_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((100, 80), "Heading", fontsize=16, fontname="tiro")
    page.insert_text((100, 120), "Body text", fontsize=14, fontname="tiro")
    _save(document, path)


def _margin_overflow_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((10, 40), "Too close to the edge", fontsize=14, fontname="tiro")
    _save(document, path)


def _cyrillic_font_path() -> Path:
    candidates = (
        Path(r"C:/Windows/Fonts/times.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return path
    msg = "Cyrillic-capable font not found for FIG-01 PDF fixtures"
    raise SystemExit(msg)


def _fig01_pdf(path: Path, *, caption_page: int) -> None:
    font_path = _cyrillic_font_path()
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_font(fontname="FigCyr", fontfile=str(font_path))
    page.insert_text(
        (100, 120),
        "Система показана на рисунке 1.",
        fontsize=14,
        fontname="FigCyr",
    )
    for number in range(2, caption_page):
        filler = document.new_page(width=595, height=842)
        filler.insert_font(fontname="FigCyr", fontfile=str(font_path))
        filler.insert_text(
            (100, 120),
            f"Промежуточная страница {number}.",
            fontsize=14,
            fontname="FigCyr",
        )
    caption = document.new_page(width=595, height=842)
    caption.insert_font(fontname="FigCyr", fontfile=str(font_path))
    caption.insert_text(
        (100, 120),
        "Рисунок 1 — Схема системы",
        fontsize=14,
        fontname="FigCyr",
    )
    _save(document, path)


def main() -> None:
    PDF.mkdir(parents=True, exist_ok=True)
    _pass_pdf(PDF / "fmt_pass.pdf")
    _wrong_font_pdf(PDF / "fmt_wrong_font.pdf")
    _non_bold_heading_pdf(PDF / "fmt_non_bold_heading.pdf")
    _margin_overflow_pdf(PDF / "fmt_margin_overflow.pdf")
    _fig01_pdf(PDF / "fig01_pass.pdf", caption_page=2)
    _fig01_pdf(PDF / "fig01_warn.pdf", caption_page=3)
    print("fixtures=", sorted(path.name for path in PDF.glob("*.pdf")))


if __name__ == "__main__":
    main()
