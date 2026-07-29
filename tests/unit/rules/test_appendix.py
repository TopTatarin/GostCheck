from __future__ import annotations

import unicodedata

from normocontrol.domain import FindingStatus, Severity
from normocontrol.extract.base import (
    DocumentBundle,
    ExtractionQuality,
    Section,
    SectionKind,
    SourceFile,
    SourceFormat,
    make_locator,
    sha256_text,
)
from normocontrol.rubric.models import Severity as RubricSeverity
from normocontrol.rules.appendix import App01RepositoryLinkRule
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.register import default_formal_registry

from .helpers import effective_rule, execution_context, minimal_rubric


def _bundle(*parts: tuple[str, SectionKind, str]) -> DocumentBundle:
    text = "\n".join(f"{title}\n{body}" for title, _, body in parts)
    source_hash = sha256_text(text)
    sections: list[Section] = []
    cursor = 0
    for title, kind, body in parts:
        section_text = f"{title}\n{body}"
        start = text.index(section_text, cursor)
        end = start + len(section_text)
        sections.append(
            Section(
                section_id=f"section-{len(sections) + 1}",
                title=title,
                kind=kind,
                level=1,
                char_start=start,
                char_end=end,
                locator=make_locator(source_hash, start, end),
            )
        )
        cursor = end
    return DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=source_hash,
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="synthetic.pdf", sha256="a" * 64),),
        sections=tuple(sections),
        chunks=(),
    )


def _run(bundle: DocumentBundle):
    rule = effective_rule("APP-01", severity=RubricSeverity.INFO)
    context = execution_context(minimal_rubric(rule), bundle=bundle)
    registry = default_formal_registry()
    return FormalEngine(registry).run(context).findings[0]


def test_repository_url_in_appendix_is_a_path_free_pass() -> None:
    bundle = _bundle(
        (
            "Приложение А",
            SectionKind.APPENDIX,
            "Исходный код: https://github.com/example/synthetic-project.",
        ),
    )

    finding = _run(bundle)

    assert finding.status is FindingStatus.PASS
    assert finding.severity is Severity.INFO
    assert finding.evidence[0].locator == bundle.sections[0].locator
    assert "github.com/example" not in finding.message


def test_missing_repository_url_is_info_not_fail() -> None:
    finding = _run(
        _bundle(
            ("Приложение А", SectionKind.APPENDIX, "Листинг синтетического алгоритма."),
        )
    )

    assert finding.status is FindingStatus.INFO
    assert finding.severity is Severity.INFO


def test_url_outside_appendix_does_not_satisfy_rule() -> None:
    finding = _run(
        _bundle(
            ("Введение", SectionKind.INTRODUCTION, "https://github.com/example/project"),
        )
    )

    assert finding.status is FindingStatus.NOT_APPLICABLE


def test_lookalike_url_is_not_accepted_as_repository() -> None:
    finding = _run(
        _bundle(
            (
                "Приложение А",
                SectionKind.APPENDIX,
                "Справка: https://example.org/github.com-not-a-repository",
            ),
        )
    )

    assert finding.status is FindingStatus.INFO


def test_nfd_plural_appendix_heading_is_recognized() -> None:
    title = unicodedata.normalize("NFD", "ПРИЛОЖЕНИЯ")
    finding = _run(
        _bundle(
            (title, SectionKind.OTHER, "Репозиторий: https://gitlab.com/example/project"),
        )
    )

    assert finding.status is FindingStatus.PASS


def test_duplicate_appendices_select_matching_evidence_deterministically() -> None:
    bundle = _bundle(
        ("Приложение А", SectionKind.APPENDIX, "Описание комплекта."),
        (
            "Приложение Б",
            SectionKind.APPENDIX,
            "Репозиторий: https://codeberg.org/example/project",
        ),
    )

    first = _run(bundle)
    second = _run(bundle)

    assert first == second
    assert first.evidence[0].locator == bundle.sections[1].locator


def test_default_registry_contains_app_01() -> None:
    registration = default_formal_registry().get(App01RepositoryLinkRule.rule_id)

    assert registration is not None
