"""SYS-01..03 formal rules."""

from __future__ import annotations

import re
from pathlib import Path

from normocontrol.domain import Finding, FindingStatus, RuleLayer, Severity
from normocontrol.rubric.models import EffectiveRule
from normocontrol.rules._findings import make_rule_finding
from normocontrol.rules.base import FormalRule, RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, SourceKind
from normocontrol.rules.latex_source import LatexProjectReader
from normocontrol.rules.protected_config import (
    default_protected_config_path,
    load_protected_files_config,
)
from normocontrol.tools.chktex import ChktexRunner
from normocontrol.tools.latexmk import LatexBuildService, LatexBuildStatus


def _protected_config_path(context: ExecutionContext) -> Path:
    assert context.latex is not None
    return default_protected_config_path(context.latex.root)


class Sys01ProtectedClassRule:
    rule_id = "SYS-01"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        config = load_protected_files_config(_protected_config_path(context))
        if config is None or not config.class_files:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.UNVERIFIABLE,
                        message="APPROVAL_REQUIRED: эталонный .cls/.sty не утверждён",
                    ),
                )
            )
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        known = {item.path: item.sha256 for item in config.class_files}
        findings: list[Finding] = []
        for relative_path, expected in known.items():
            candidate = context.latex.root / relative_path
            if not candidate.is_file():
                findings.append(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message=f"отсутствует защищённый файл {relative_path}",
                        path=relative_path,
                    )
                )
                continue
            actual = reader.sha256_file(candidate)
            if actual != expected:
                findings.append(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message=f"hash mismatch для {relative_path}",
                        path=relative_path,
                    )
                )
        if findings:
            return RuleRunOutcome(findings=tuple(findings))
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="защищённые файлы совпадают с эталоном",
                ),
            )
        )


class Sys02ProtectedPreambleRule:
    rule_id = "SYS-02"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        config = load_protected_files_config(_protected_config_path(context))
        reader = LatexProjectReader.load(context.latex.root, context.latex.main_tex)
        preamble = reader.snapshot.preamble
        for forbidden in config.forbidden_preamble if config else ():
            if re.search(forbidden.pattern, preamble, flags=re.IGNORECASE | re.MULTILINE):
                return RuleRunOutcome(
                    findings=(
                        make_rule_finding(
                            rule,
                            layer=RuleLayer.SCRIPT,
                            status=FindingStatus.FAIL,
                            message=forbidden.message,
                            path="preamble",
                        ),
                    )
                )
        default_patterns = (
            (r"\\usepackage\s*\{geometry\}", "запрещён \\usepackage{geometry} в преамбуле"),
            (r"\\usepackage\s*\{fontspec\}", "запрещён \\usepackage{fontspec} в преамбуле"),
            (r"\\usepackage\s*\{setspace\}", "запрещён \\usepackage{setspace} в преамбуле"),
            (r"\\setlength\s*\{\s*\\parindent\s*\}", "запрещено изменение \\parindent"),
        )
        for regex, message in default_patterns:
            if re.search(regex, preamble, flags=re.IGNORECASE):
                return RuleRunOutcome(
                    findings=(
                        make_rule_finding(
                            rule,
                            layer=RuleLayer.SCRIPT,
                            status=FindingStatus.FAIL,
                            message=message,
                            path="preamble",
                        ),
                    )
                )
        return RuleRunOutcome(
            findings=(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="преамбула не содержит запрещённых переопределений",
                ),
            )
        )


class Sys03BuildRule:
    rule_id = "SYS-03"
    required_sources = frozenset({SourceKind.LATEX_PROJECT})

    def __init__(
        self,
        build_service: LatexBuildService | None = None,
        chktex: ChktexRunner | None = None,
    ) -> None:
        self._build = build_service or LatexBuildService()
        self._chktex = chktex or ChktexRunner()

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del rule
        return context.latex is not None

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        assert context.latex is not None
        build = self._build.build(context.latex.root, context.latex.main_tex)
        findings: list[Finding] = []
        if build.status is LatexBuildStatus.TOOL_MISSING:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.UNVERIFIABLE,
                        message="latexmk недоступен; проверка сборки невозможна",
                    ),
                )
            )
        if build.status is LatexBuildStatus.TIMEOUT:
            return RuleRunOutcome(
                findings=(
                    make_rule_finding(
                        rule,
                        layer=RuleLayer.SCRIPT,
                        status=FindingStatus.FAIL,
                        message="latexmk превысил лимит времени",
                    ),
                )
            )
        if build.status is LatexBuildStatus.MISSING_DEPENDENCY:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.FAIL,
                    message=f"отсутствует файл: {', '.join(build.missing_files)}",
                )
            )
        elif build.status is LatexBuildStatus.COMPILE_ERROR:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.FAIL,
                    message="ошибка компиляции LaTeX",
                )
            )
        for points in build.overfull_hboxes_pt:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.WARN,
                    severity=Severity.WARN,
                    message=f"overfull hbox {points}pt (>15pt)",
                )
            )
        chktex = self._chktex.lint(context.latex.root, context.latex.main_tex)
        if not chktex.available:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.UNVERIFIABLE,
                    severity=Severity.INFO,
                    message="chktex недоступен",
                )
            )
        elif chktex.returncode != 0:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.WARN,
                    severity=Severity.WARN,
                    message="chktex сообщил предупреждения",
                )
            )
        if not findings and build.status is LatexBuildStatus.SUCCESS:
            findings.append(
                make_rule_finding(
                    rule,
                    layer=RuleLayer.SCRIPT,
                    status=FindingStatus.PASS,
                    message="документ успешно компилируется",
                )
            )
        return RuleRunOutcome(findings=tuple(findings))


def system_rules(
    *,
    build_service: LatexBuildService | None = None,
    chktex: ChktexRunner | None = None,
) -> tuple[FormalRule, ...]:
    return (
        Sys01ProtectedClassRule(),
        Sys02ProtectedPreambleRule(),
        Sys03BuildRule(build_service=build_service, chktex=chktex),
    )
