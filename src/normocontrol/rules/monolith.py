"""ANN-02 and INT-02 monolith text rules."""

from __future__ import annotations

from normocontrol.domain import FindingStatus, RuleLayer
from normocontrol.extract.base import SectionKind
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader


class Ann02MonolithRule:
    rule_id = "ANN-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        annotation = next(
            (
                section
                for section in reader.snapshot.sections
                if section.kind is SectionKind.ANNOTATION
            ),
            None,
        )
        body = (
            reader.section_body(annotation.title)
            if annotation
            else reader.section_body("Аннотация")
        )
        if body is None:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.UNVERIFIABLE,
                        message="раздел «Аннотация» не найден",
                    ),
                )
            )
        if reader.contains_list_environment(body):
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message="в аннотации обнаружены itemize/enumerate",
                    ),
                )
            )
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="аннотация не содержит маркированных списков",
                ),
            )
        )


class Int02MonolithRule:
    rule_id = "INT-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        introduction = next(
            (
                section
                for section in reader.snapshot.sections
                if section.kind is SectionKind.INTRODUCTION
            ),
            None,
        )
        body = (
            reader.section_body(introduction.title)
            if introduction
            else reader.section_body("Введение")
        )
        if body is None:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.UNVERIFIABLE,
                        message="раздел «Введение» не найден",
                    ),
                )
            )
        if reader.contains_list_environment(body):
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message="во введении обнаружены itemize/enumerate",
                    ),
                )
            )
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="введение не содержит маркированных списков",
                ),
            )
        )


def monolith_rules() -> tuple[Ann02MonolithRule, Int02MonolithRule]:
    return Ann02MonolithRule(), Int02MonolithRule()
