"""REV-01..04 and REV-07 formal literature-review rules."""

from __future__ import annotations

import re

from normocontrol.domain import FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._rule_outcomes import rule_outcome
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.bib_parser import BibEntry, entry_field, load_bib_entries
from normocontrol.rules.cite_symbols import cite_keys, paragraphs_without_cite, word_count
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader

_REVIEW_SECTION = "Обзор НТИ"
_FOREIGN_TYPES = frozenset({"article", "inproceedings"})
_FORBIDDEN_DOMAINS = (
    ("wikipedia.", "wikipedia"),
    ("habr.com", "habr.com"),
    ("stackoverflow.com", "stackoverflow.com"),
)


def _reader(context: ExecutionContext) -> LatexProjectReader:
    assert context.latex is not None
    return LatexProjectReader.load(context.latex.root, context.latex.main_tex)


def _bib_entries(context: ExecutionContext) -> tuple[BibEntry, ...]:
    assert context.latex is not None
    paths = tuple(
        path if path.is_absolute() else context.latex.root / path for path in context.bib_paths
    )
    return load_bib_entries(paths)


def _entries_by_key(entries: tuple[BibEntry, ...]) -> dict[str, BibEntry]:
    return {entry.key: entry for entry in entries}


def _review_body(context: ExecutionContext) -> str | None:
    return _reader(context).section_body(_REVIEW_SECTION)


def _review_cite_keys(context: ExecutionContext) -> frozenset[str]:
    body = _review_body(context)
    if body is None:
        return frozenset()
    return cite_keys(body)


def _latin_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for char in letters if "a" <= char.casefold() <= "z")
    return latin / len(letters)


def _is_foreign_peer(entry: BibEntry) -> bool:
    if entry.entry_type not in _FOREIGN_TYPES:
        return False
    author = entry_field(entry, "author") or ""
    title = entry_field(entry, "title") or ""
    combined = f"{author} {title}"
    return _latin_ratio(combined) >= 0.6


def _entry_year(entry: BibEntry) -> int | None:
    raw = entry_field(entry, "year")
    if raw is None:
        return None
    match = re.search(r"(19|20)\d{2}", raw)
    if match is None:
        return None
    return int(match.group(0))


def _forbidden_source(entry: BibEntry) -> str | None:
    url = (entry_field(entry, "url") or "").casefold()
    if not url:
        return None
    for needle, label in _FORBIDDEN_DOMAINS:
        if needle in url:
            return label
    if "arxiv.org" in url:
        blob = " ".join(entry.fields.values()).casefold()
        if "published" not in blob:
            return "arxiv.org"
    return None


class Rev01MinimumSourcesRule:
    rule_id = "REV-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        body = _review_body(context)
        if body is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message=f"раздел «{_REVIEW_SECTION}» не найден",
            )
        count = len(_review_cite_keys(context))
        if count >= 20:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.PASS,
                message=f"в обзоре процитировано {count} источников",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.WARN,
            severity=Severity.WARN,
            message=f"в обзоре процитировано {count} источников (<20)",
        )


class Rev02ForeignPeerReviewedRule:
    rule_id = "REV-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        body = _review_body(context)
        if body is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message=f"раздел «{_REVIEW_SECTION}» не найден",
            )
        entries = _entries_by_key(_bib_entries(context))
        foreign = [
            key
            for key in _review_cite_keys(context)
            if key in entries and _is_foreign_peer(entries[key])
        ]
        count = len(foreign)
        if count >= 10:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.PASS,
                message=f"в обзоре {count} зарубежных рецензируемых источников",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.WARN,
            severity=Severity.WARN,
            message=f"в обзоре {count} зарубежных рецензируемых источников (<10)",
        )


class Rev03RecentSourcesRule:
    rule_id = "REV-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        body = _review_body(context)
        if body is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message=f"раздел «{_REVIEW_SECTION}» не найден",
            )
        defense_year = context.config.params.defense_year
        if defense_year is None:
            defense_year = context.rubric.meta.params_to_approve.defense_year
        threshold = int(defense_year) - 5
        target_share = context.config.params.recent_sources_share
        if target_share is None:
            target_share = context.rubric.meta.params_to_approve.recent_sources_share
        required_share = float(target_share)
        entries = _entries_by_key(_bib_entries(context))
        cited_keys = _review_cite_keys(context)
        years: list[int] = []
        for key in cited_keys:
            entry = entries.get(key)
            if entry is None:
                continue
            year = _entry_year(entry)
            if year is not None:
                years.append(year)
        if not years:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.UNVERIFIABLE,
                message="не удалось определить годы источников обзора",
            )
        recent = sum(1 for year in years if year >= threshold)
        share = recent / len(years)
        if share >= required_share:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.PASS,
                message=f"доля свежих источников {share:.0%} (>= {required_share:.0%})",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.WARN,
            severity=Severity.WARN,
            message=f"доля свежих источников {share:.0%} (< {required_share:.0%})",
        )


class Rev04ForbiddenSourceTypesRule:
    rule_id = "REV-04"
    required_sources = frozenset({SourceKind.LATEX_PROJECT, SourceKind.BIB_FILES})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        body = _review_body(context)
        if body is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message=f"раздел «{_REVIEW_SECTION}» не найден",
            )
        entries = _entries_by_key(_bib_entries(context))
        forbidden: list[str] = []
        for key in _review_cite_keys(context):
            entry = entries.get(key)
            if entry is None:
                continue
            label = _forbidden_source(entry)
            if label is not None:
                forbidden.append(f"{key} ({label})")
        if forbidden:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.FAIL,
                message=f"запрещённые источники: {', '.join(forbidden[:5])}",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="запрещённые типы источников не обнаружены",
        )


class Rev07CitationDensityRule:
    rule_id = "REV-07"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        body = _review_body(context)
        if body is None:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message=f"раздел «{_REVIEW_SECTION}» не найден",
            )
        sparse = paragraphs_without_cite(body)
        words = word_count(body)
        cites = len(cite_keys(body))
        approx_pages = max(1, words // 300)
        if cites < approx_pages:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message=(
                    f"мало ссылок в обзоре ({cites} на ~{approx_pages} стр.); "
                    f"длинных абзацев без \\cite: {len(sparse)}"
                ),
            )
        if sparse:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.WARN,
                severity=Severity.WARN,
                message=f"длинные абзацы без \\cite: {len(sparse)}",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="ссылки распределены по тексту обзора",
        )


def review_rules() -> tuple[
    Rev01MinimumSourcesRule,
    Rev02ForeignPeerReviewedRule,
    Rev03RecentSourcesRule,
    Rev04ForbiddenSourceTypesRule,
    Rev07CitationDensityRule,
]:
    return (
        Rev01MinimumSourcesRule(),
        Rev02ForeignPeerReviewedRule(),
        Rev03RecentSourcesRule(),
        Rev04ForbiddenSourceTypesRule(),
        Rev07CitationDensityRule(),
    )
