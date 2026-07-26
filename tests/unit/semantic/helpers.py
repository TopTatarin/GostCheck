from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from normocontrol.extract.base import (
    DocumentBundle,
    ExtractedDocument,
    ExtractionQuality,
    HeadingCandidate,
    SourceFile,
    SourceFormat,
    sha256_text,
)
from normocontrol.extract.chunking import Chunker
from normocontrol.extract.sections import SectionDetector
from normocontrol.llm.base import ChatMessage, LlmProvider, ProbeResult

SECTION_PARTS = (
    ("Аннотация", "Синтетическое доказательство описывает цель и результаты."),
    ("Введение", "Synthetic evidence подтверждает актуальность и необходимость решения."),
    (
        "Обзор научно-технической информации",
        "Сравнение подходов образует тематическую классификацию. "
        "Вопросы обзора получили обобщённые ответы.",
    ),
    (
        "Структурный системный анализ",
        "Описано только текущее состояние объекта и его проблемы.",
    ),
    ("Постановка задачи", "Цель измерима. Задачи перечислены в изменённом порядке."),
    (
        "Математическая модель",
        "Переменные заданы символами и подробно пояснены. Модель приведена в общем виде.",
    ),
    (
        "Алгоритм",
        "Алгоритм представлен проверяемым псевдокодом. Шаги выполняются последовательно.",
    ),
    ("Анализ результатов", "Достигнуто 95 процентов; одна задача выполнена частично."),
    ("Заключение", "Все задачи сопоставлены с результатами и оценены количественно."),
    ("Основной раздел", "Результат предыдущего раздела используется следующим разделом."),
)


def make_bundle(parts: Sequence[tuple[str, str]] = SECTION_PARTS) -> DocumentBundle:
    text = "\n".join(f"{title}\n{body}" for title, body in parts)
    headings = tuple(
        HeadingCandidate(
            title=title,
            level=1,
            char_start=text.index(title),
            origin="latex_ast",
        )
        for title, _ in parts
    )
    extracted = ExtractedDocument(
        source_format=SourceFormat.LATEX,
        source_hash=sha256_text(text),
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="synthetic/main.tex", sha256="0" * 64),),
        headings=headings,
    )
    sections = SectionDetector().detect(extracted)
    chunks = Chunker(token_budget=100).chunk(extracted, sections)
    return DocumentBundle(
        source_format=extracted.source_format,
        source_hash=extracted.source_hash,
        text=text,
        extraction_quality=extracted.extraction_quality,
        source_files=extracted.source_files,
        sections=sections,
        chunks=chunks,
    )


class QueueProvider(LlmProvider):
    def __init__(self, responses: Sequence[object], name: str = "mock") -> None:
        self.responses = list(responses)
        self.calls: list[tuple[ChatMessage, ...]] = []
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def health_check(self) -> ProbeResult:
        return ProbeResult(provider=self.name, available=True, model_available=True, detail="mock")

    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        self.calls.append(messages)
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return response_model.model_validate(payload)


def response_payload(
    rule_id: str,
    elements: Sequence[str],
    *,
    status: str = "pass",
    state: str = "present",
    quote: str | None = None,
    chunk_id: str | None = None,
    confidence: Any = 0.9,
) -> dict[str, object]:
    evidence = [] if quote is None or chunk_id is None else [{"chunk_id": chunk_id, "quote": quote}]
    return {
        "rule_id": rule_id,
        "status": status,
        "confidence": confidence,
        "summary": "Синтетический структурированный результат.",
        "evidence": evidence,
        "elements": [
            {"element": element, "state": state, "evidence": evidence} for element in elements
        ],
    }
