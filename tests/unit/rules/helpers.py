"""Shared builders for formal engine unit tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from normocontrol.domain import Finding, FindingStatus, RuleLayer, Severity
from normocontrol.extract.base import (
    DocumentBundle,
    ExtractionQuality,
    Section,
    SectionKind,
    SourceFile,
    SourceFormat,
    sha256_text,
)
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rubric.models import (
    Capability,
    EffectiveRubric,
    EffectiveRule,
    NormocontrolConfig,
    WorkProfile,
)
from normocontrol.rubric.models import (
    Severity as RubricSeverity,
)
from normocontrol.rules.base import RuleExecutionError, RuleRunOutcome
from normocontrol.rules.context import ExecutionContext, LatexProject, SourceKind

ROOT = Path(__file__).resolve().parents[3]
RUBRIC_PATH = ROOT / "rubric.yaml"
CONFIG_PATH = ROOT / "normocontrol.yaml.example"


def default_config() -> NormocontrolConfig:
    return load_config(CONFIG_PATH)


def effective_rule(
    rule_id: str,
    *,
    layer: str = "script",
    capabilities: tuple[Capability, ...] = (Capability.SCRIPT,),
    severity: RubricSeverity = RubricSeverity.ERROR,
    enabled: bool = True,
) -> EffectiveRule:
    return EffectiveRule(
        id=rule_id,
        src="M1",
        rule="formal rule text",
        layer=layer,
        capabilities=capabilities,
        check="formal check text",
        severity=severity,
        enabled=enabled,
    )


def minimal_rubric(*rules: EffectiveRule) -> EffectiveRubric:
    meta = load_rubric(RUBRIC_PATH).meta
    return EffectiveRubric(meta=meta, work_profile=WorkProfile.SOFTWARE, rules=rules)


def latex_bundle() -> DocumentBundle:
    text = "Synthetic thesis body for formal engine tests."
    source_hash = sha256_text(text)
    section = Section(
        section_id="introduction",
        title="Введение",
        kind=SectionKind.INTRODUCTION,
        level=1,
        char_start=0,
        char_end=len(text),
        locator=f"sha256:{source_hash}:0-{len(text)}",
    )
    return DocumentBundle(
        source_format=SourceFormat.LATEX,
        source_hash=source_hash,
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="main.tex", sha256="a" * 64),),
        sections=(section,),
        chunks=(),
    )


def latex_project(root: Path | None = None) -> LatexProject:
    project_root = root or Path("fixtures/latex/pass")
    return LatexProject(root=project_root, main_tex=project_root / "main.tex")


def pdf_bundle() -> DocumentBundle:
    text = "PDF-only synthetic text."
    source_hash = sha256_text(text)
    section = Section(
        section_id="body",
        title="Основной текст",
        kind=SectionKind.OTHER,
        level=1,
        char_start=0,
        char_end=len(text),
        locator=f"sha256:{source_hash}:0-{len(text)}",
    )
    return DocumentBundle(
        source_format=SourceFormat.PDF,
        source_hash=source_hash,
        text=text,
        extraction_quality=ExtractionQuality.HIGH,
        source_files=(SourceFile(path="main.pdf", sha256="b" * 64),),
        sections=(section,),
        chunks=(),
    )


def execution_context(
    rubric: EffectiveRubric,
    *,
    bundle: DocumentBundle | None = None,
    latex: LatexProject | None = None,
    pdf_path: Path | None = None,
    bib_paths: tuple[Path, ...] = (),
    fail_closed: bool = False,
    canceled: bool = False,
    config: NormocontrolConfig | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        rubric=rubric,
        config=config or default_config(),
        bundle=bundle,
        latex=latex,
        pdf_path=pdf_path,
        bib_paths=bib_paths,
        fail_closed=fail_closed,
        canceled=canceled,
    )


@dataclass
class StubFormalRule:
    """Test double implementing ``FormalRule``."""

    rule_id: str
    required_sources: frozenset[SourceKind]
    applicable: bool = True
    findings: tuple[Finding, ...] = ()
    error: Exception | None = None

    def supports(self, context: ExecutionContext, rule: EffectiveRule) -> bool:
        del context, rule
        return self.applicable

    def run(self, context: ExecutionContext, rule: EffectiveRule) -> RuleRunOutcome:
        del context, rule
        if self.error is not None:
            if isinstance(self.error, RuleExecutionError):
                raise self.error
            raise self.error
        return RuleRunOutcome(findings=self.findings)


def formal_fail(
    rule_id: str,
    *,
    layer: RuleLayer = RuleLayer.SCRIPT,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        layer=layer,
        severity=Severity.ERROR,
        status=FindingStatus.FAIL,
        message="нарушение",
    )
