"""CAP-01 caption text rule."""

from __future__ import annotations

import re

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._rule_outcomes import rule_outcome
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.latex_symbols import caption_arguments

_CAPITALIZED_RE = re.compile(r"^[A-ZА-ЯЁ]")


class Cap01CaptionCapitalizationRule:
    rule_id = "CAP-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        captions = caption_arguments(reader.snapshot.body)
        if not captions:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.NOT_APPLICABLE,
                message="\\caption не обнаружены",
            )
        invalid: list[str] = []
        for caption in captions:
            stripped = caption.strip()
            if not stripped:
                invalid.append("пустая подпись")
                continue
            if not _CAPITALIZED_RE.match(stripped):
                invalid.append(stripped[:32])
                continue
            if stripped.endswith("."):
                invalid.append(stripped[:32])
        if invalid:
            return rule_outcome(
                rule,
                layer=RuleLayer.SCRIPT,
                status=FindingStatus.FAIL,
                message=f"некорректные подписи: {', '.join(invalid)}",
            )
        return rule_outcome(
            rule,
            layer=RuleLayer.SCRIPT,
            status=FindingStatus.PASS,
            message="наименования рисунков/таблиц оформлены корректно",
        )


def caption_rules() -> tuple[Cap01CaptionCapitalizationRule,]:
    return (Cap01CaptionCapitalizationRule(),)
