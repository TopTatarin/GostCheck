from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from normocontrol.extract.base import (
    ExtractionQuality,
    PdfEncryptedError,
    PdfExtractionError,
    SectionKind,
)
from normocontrol.extract.pdf import PdfExtractor


def save_pdf(document: fitz.Document, path: Path, **kwargs: object) -> Path:
    document.save(path, **kwargs)
    document.close()
    return path


def test_two_column_pdf_uses_column_reading_order_and_retains_layout(tmp_path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((50, 50), "Synthetic title", fontsize=18)
    page.insert_text((50, 120), "LEFT-FIRST", fontsize=11)
    page.insert_text((50, 160), "LEFT-SECOND", fontsize=11)
    page.insert_text((330, 120), "RIGHT-FIRST", fontsize=11)
    page.insert_text((330, 160), "RIGHT-SECOND", fontsize=11)
    path = save_pdf(document, tmp_path / "columns.pdf")

    bundle = PdfExtractor(tmp_path).extract(path)

    assert bundle.extraction_quality is ExtractionQuality.HIGH
    assert bundle.text.index("LEFT-FIRST") < bundle.text.index("LEFT-SECOND")
    assert bundle.text.index("LEFT-SECOND") < bundle.text.index("RIGHT-FIRST")
    assert all(span.page == 1 and span.font and span.font_size for span in bundle.spans)
    assert bundle.pages[0].width == pytest.approx(595)


def test_pdf_without_text_layer_is_explicitly_degraded(tmp_path: Path) -> None:
    document = fitz.open()
    document.new_page()
    path = save_pdf(document, tmp_path / "scan.pdf")

    bundle = PdfExtractor(tmp_path).extract(path)

    assert bundle.text == ""
    assert bundle.extraction_quality is ExtractionQuality.DEGRADED
    assert bundle.warnings == ("PDF_NO_TEXT_LAYER",)
    assert bundle.chunks == ()


def test_rotated_and_mixed_page_sizes_are_retained(tmp_path: Path) -> None:
    document = fitz.open()
    first = document.new_page(width=595, height=842)
    first.insert_text((50, 50), "A4 page")
    first.set_rotation(90)
    second = document.new_page(width=842, height=1191)
    second.insert_text((50, 50), "A3 page")
    path = save_pdf(document, tmp_path / "geometry.pdf")

    bundle = PdfExtractor(tmp_path).extract(path)

    assert [page.rotation for page in bundle.pages] == [90, 0]
    assert bundle.pages[0].width == pytest.approx(842)
    assert bundle.pages[1].width == pytest.approx(842)
    assert bundle.pages[0].height != bundle.pages[1].height
    assert {span.page for span in bundle.spans} == {1, 2}


def test_outline_has_priority_and_addresses_conclusion(tmp_path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 80), "Conclusion", fontsize=20)
    page.insert_text((50, 120), "Synthetic result", fontsize=11)
    document.set_toc([[1, "Заключение", 1]])
    path = save_pdf(document, tmp_path / "outline.pdf")

    bundle = PdfExtractor(tmp_path).extract(path)

    conclusion = next(
        section for section in bundle.sections if section.kind is SectionKind.CONCLUSION
    )
    assert conclusion.title == "Заключение"
    assert conclusion.page_start == 1


def test_repeated_large_running_header_is_not_a_section(tmp_path: Path) -> None:
    document = fitz.open()
    for page_number in range(3):
        page = document.new_page()
        page.insert_text((50, 35), "REPEATED HEADER", fontsize=16)
        for line in range(4):
            page.insert_text((50, 100 + line * 20), f"body {page_number}-{line}", fontsize=10)
        if page_number == 1:
            page.insert_text((50, 300), "Conclusion", fontsize=18)
    path = save_pdf(document, tmp_path / "headers.pdf")

    bundle = PdfExtractor(tmp_path).extract(path)

    assert all(section.title != "REPEATED HEADER" for section in bundle.sections)
    assert any(section.kind is SectionKind.CONCLUSION for section in bundle.sections)


def test_corrupt_and_encrypted_pdf_fail_with_typed_safe_errors(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a real document")
    with pytest.raises(PdfExtractionError, match=r"corrupt\.pdf"):
        PdfExtractor(tmp_path).extract(corrupt)

    document = fitz.open()
    document.new_page().insert_text((50, 50), "private synthetic text")
    encrypted = save_pdf(
        document,
        tmp_path / "encrypted.pdf",
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-unit-test",
        user_pw="user-unit-test",
    )
    with pytest.raises(PdfEncryptedError, match="requires a password"):
        PdfExtractor(tmp_path).extract(encrypted)


class FakePage:
    rotation = 0
    rect = fitz.Rect(0, 0, 595, 842)

    def get_text(self, _: str, *, sort: bool) -> dict[str, object]:
        assert sort is False
        return {
            "blocks": [
                {
                    "type": 0,
                    "bbox": (0, 0, 0, 0),
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "oﬃce",
                                    "size": 12,
                                    "font": "Synthetic",
                                    "bbox": (0, 0, 0, 0),
                                }
                            ]
                        }
                    ],
                }
            ]
        }


class FakePdf:
    page_count = 1

    def load_page(self, _: int) -> FakePage:
        return FakePage()

    def get_toc(self, *, simple: bool) -> list[list[object]]:
        assert simple is True
        return []


def test_ligatures_are_normalized_and_zero_bbox_degrades_quality() -> None:
    extracted = PdfExtractor()._extract_document(FakePdf(), "fake.pdf", b"synthetic")

    assert extracted.text == "office"
    assert extracted.spans[0].bbox.x0 == extracted.spans[0].bbox.x1 == 0
    assert extracted.extraction_quality is ExtractionQuality.DEGRADED
    assert extracted.warnings == ("PDF_ZERO_BBOX",)
