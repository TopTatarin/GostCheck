"""APP-01 repository-link check for appendix sections."""

from __future__ import annotations

import re
import unicodedata

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.extract.base import Section, SectionKind
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind

_APPENDIX_TITLE_RE = re.compile(
    r"^(?:приложен(?:ие|ия)|appendix|appendices)(?:\b|\s)",
    re.IGNORECASE,
)
_REPOSITORY_URL_RE = re.compile(
    r"""
    \bhttps?://
    (?:
        (?:www\.)?
        (?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org|git\.sr\.ht)
        /[A-Za-z0-9_.~-]+/[A-Za-z0-9_.~-]+
        |
        [A-Za-z0-9.-]+(?::\d+)?/[^\s<>{}\[\]"']+\.git
    )
    (?:[/?#][^\s<>{}\[\]"']*)?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_appendix(section: Section) -> bool:
    if section.kind is SectionKind.APPENDIX:
        return True
    title = unicodedata.normalize("NFC", section.title).casefold().replace("ё", "е")
    title = re.sub(r"^\s*\d+(?:\.\d+)*[.\s:—-]+", "", title)
    return _APPENDIX_TITLE_RE.match(title.strip()) is not None


class App01RepositoryLinkRule:
    """Report whether an appendix contains a recognizable Git repository URL."""

    rule_id = "APP-01"
    required_sources: frozenset[SourceKind] = frozenset()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.bundle is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.bundle is not None
        appendices = tuple(section for section in context.bundle.sections if _is_appendix(section))
        if not appendices:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.NOT_APPLICABLE,
                        message="раздел приложений не найден",
                    ),
                )
            )

        for section in appendices:
            body = context.bundle.text[section.char_start : section.char_end]
            if _REPOSITORY_URL_RE.search(body) is not None:
                return RuleRunOutcome(
                    findings=(
                        make_rule_finding(
                            rule,
                            layer=RuleLayer.SCRIPT,
                            status=FindingStatus.PASS,
                            message="в приложениях найдена ссылка на Git-репозиторий",
                            evidence_locator=section.locator,
                        ),
                    )
                )

        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.INFO,
                    message="в приложениях не найдена ссылка на Git-репозиторий",
                    evidence_locator=appendices[0].locator,
                ),
            )
        )


def appendix_rules() -> tuple[App01RepositoryLinkRule]:
    return (App01RepositoryLinkRule(),)
