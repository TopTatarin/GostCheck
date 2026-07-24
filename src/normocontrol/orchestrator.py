"""Full-pipeline orchestrator: build -> formal -> semantic -> aggregate."""

from __future__ import annotations

import json
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from normocontrol.cache import (
    CACHE_DIR_NAME,
    CacheKeyParts,
    LockError,
    OutputLock,
    StageCache,
    atomic_write_json,
    ensure_writable_out_dir,
    hash_file,
    hash_paths,
    hash_text,
)
from normocontrol.domain import (
    Evidence,
    ExitCode,
    Finding,
    FindingStatus,
    RuleLayer,
    RunReport,
    Severity,
    StageResult,
)
from normocontrol.errors import ConfigurationError, LocatedValidationError, NormocontrolError
from normocontrol.extract.base import DocumentBundle, ExtractionError
from normocontrol.extract.latex import LatexExtractor
from normocontrol.extract.pdf import PdfExtractor
from normocontrol.llm.base import LlmProvider
from normocontrol.llm.config import ProviderName, load_llm_config
from normocontrol.llm.disabled import DisabledProvider
from normocontrol.llm.ollama import OllamaProvider
from normocontrol.llm.yandex import YandexProvider
from normocontrol.reporting.aggregate import publish_reports
from normocontrol.reporting.json_report import ReportMeta
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.loader import load_config, load_rubric
from normocontrol.rubric.models import EffectiveRubric, NormocontrolConfig, WorkProfile
from normocontrol.rules.context import ExecutionContext, LatexProject
from normocontrol.rules.engine import FormalEngine
from normocontrol.rules.gate import formal_exit_code
from normocontrol.rules.register import default_formal_registry
from normocontrol.run_context import RunRequest, RunState, StageName
from normocontrol.semantic.engine import SemanticEngine
from normocontrol.semantic.schemas import SemanticFinding, SemanticReport, SemanticStatus
from normocontrol.tools.latexmk import LatexBuildResult, LatexBuildService, LatexBuildStatus

BuildFn = Callable[[Path, Path], LatexBuildResult]
ProviderFactory = Callable[[], LlmProvider]


@dataclass(slots=True)
class OrchestratorHooks:
    """Optional test seams for build and LLM providers."""

    build_service: LatexBuildService | None = None
    provider_factory: ProviderFactory | None = None
    clock: Callable[[], float] = time.perf_counter


class Orchestrator:
    """Execute the documented stage order and publish a ``RunReport``."""

    def __init__(self, hooks: OrchestratorHooks | None = None) -> None:
        self._hooks = hooks or OrchestratorHooks()
        self._canceled = False

    def run(self, request: RunRequest) -> RunReport:
        """Run the pipeline and always attempt to leave diagnosable artifacts."""
        state = RunState()
        stages: list[StageResult] = []
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)
        lock: OutputLock | None = None
        try:
            ensure_writable_out_dir(request.out_dir)
            lock = OutputLock(request.out_dir)
            lock.acquire()
            cache = StageCache(request.out_dir / CACHE_DIR_NAME)
            source = self._resolve_source(request.source)
            config, rubric = self._load_config_and_rubric(request)
            if request.apply_final_severity:
                rubric = apply_final_severity(rubric)

            source_hash = self._source_hash(source)
            rubric_hash = hash_file(request.rubric_path.resolve())
            config_hash = hash_file(request.config_path.resolve())
            base_key = {
                "source_hash": source_hash,
                "rubric_hash": rubric_hash,
                "config_hash": config_hash,
                "tool_version": request.tool_version,
            }

            bundle: DocumentBundle | None = None
            latex: LatexProject | None = None
            pdf_path: Path | None = None
            build_meta: dict[str, Any] = {}

            if request.only.includes_stage(StageName.BUILD):
                build_stage, bundle, latex, pdf_path, build_meta = self._stage_build(
                    request=request,
                    source=source,
                    cache=cache,
                    base_key=base_key,
                    state=state,
                )
                stages.append(build_stage)
                self._write_stage_artifact(
                    request.out_dir,
                    StageName.BUILD,
                    build_stage,
                    build_meta,
                )
                state.mark_completed(StageName.BUILD)
            else:
                bundle, latex, pdf_path = self._extract_only(source)

            if self._canceled:
                return self._canceled_report(request, stages, state)

            formal_findings: tuple[Finding, ...] = ()
            if request.only.includes_stage(StageName.FORMAL):
                formal_stage, formal_findings = self._stage_formal(
                    request=request,
                    config=config,
                    rubric=rubric,
                    bundle=bundle,
                    latex=latex,
                    pdf_path=pdf_path,
                    cache=cache,
                    base_key=base_key,
                    state=state,
                )
                stages.append(formal_stage)
                self._write_stage_artifact(
                    request.out_dir,
                    StageName.FORMAL,
                    formal_stage,
                    {"finding_count": len(formal_findings)},
                )
                state.mark_completed(StageName.FORMAL)

            if self._canceled:
                return self._canceled_report(request, stages, state)

            semantic_findings: tuple[Finding, ...] = ()
            if request.only.includes_stage(StageName.SEMANTIC) and not request.no_llm:
                semantic_stage, semantic_findings = self._stage_semantic(
                    request=request,
                    bundle=bundle,
                    cache=cache,
                    base_key=base_key,
                    state=state,
                )
                stages.append(semantic_stage)
                self._write_stage_artifact(
                    request.out_dir,
                    StageName.SEMANTIC,
                    semantic_stage,
                    {"finding_count": len(semantic_findings)},
                )
                state.mark_completed(StageName.SEMANTIC)
            elif request.only.includes_stage(StageName.SEMANTIC) and request.no_llm:
                skipped = StageResult(name=StageName.SEMANTIC.value, findings=(), duration_ms=0.0)
                stages.append(skipped)
                self._write_stage_artifact(
                    request.out_dir,
                    StageName.SEMANTIC,
                    skipped,
                    {"skipped": True, "reason": "no_llm"},
                )
                state.mark_completed(StageName.SEMANTIC)

            if self._canceled:
                return self._canceled_report(request, stages, state)

            exit_code = self._resolve_exit_code(formal_findings, state)
            if request.only.includes_stage(StageName.AGGREGATE):
                started = self._hooks.clock()
                aggregate = StageResult(
                    name=StageName.AGGREGATE.value,
                    findings=(),
                    duration_ms=max(0.0, (self._hooks.clock() - started) * 1000.0),
                )
                stages = [*stages, aggregate]
                report = RunReport(
                    tool_version=request.tool_version,
                    exit_code=exit_code,
                    stages=tuple(stages),
                )
                all_findings = tuple(
                    finding for stage in stages for finding in stage.findings
                )
                publish_reports(
                    report,
                    request.out_dir,
                    meta=ReportMeta(
                        commit_sha=(
                            os.environ.get("GITHUB_SHA")
                            or os.environ.get("COMMIT_SHA")
                            or "unknown"
                        ),
                        profile=config.work_profile.value,
                        rubric_version=rubric.meta.version,
                        model_id=(
                            None
                            if request.no_llm
                            else (request.provider or "disabled")
                        ),
                        degraded=bool(build_meta.get("degraded")),
                        approvals_required=any(
                            "APPROVAL_REQUIRED" in finding.message.upper()
                            for finding in all_findings
                        ),
                        artifact_name=None,
                        repo_root=None,
                    ),
                    clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
                )
                self._write_stage_artifact(
                    request.out_dir,
                    StageName.AGGREGATE,
                    aggregate,
                    {"exit_code": int(exit_code), "published": True},
                )
                state.mark_completed(StageName.AGGREGATE)
            else:
                report = RunReport(
                    tool_version=request.tool_version,
                    exit_code=exit_code,
                    stages=tuple(stages),
                )
                atomic_write_json(
                    request.out_dir / "report.json",
                    json.loads(report.model_dump_json()),
                )

            atomic_write_json(
                request.out_dir / "run_state.json",
                {
                    "completed_stages": state.completed_stages,
                    "canceled": state.canceled,
                    "exit_code": int(exit_code),
                    "messages": state.messages,
                },
            )
            return report
        except ConfigurationError:
            raise
        except LocatedValidationError:
            raise
        except LockError:
            raise
        except NormocontrolError:
            raise
        except OSError as error:
            raise ConfigurationError(f"input/output error: {error}") from error
        finally:
            if lock is not None:
                lock.release()
            signal.signal(signal.SIGINT, previous_handler)

    def _handle_sigint(self, _signum: int, _frame: object) -> None:
        self._canceled = True

    def _resolve_source(self, source: Path) -> Path:
        if not source.exists():
            raise ConfigurationError(f"source path does not exist: {source}")
        if source.is_dir():
            for name in ("main.tex", "main.pdf"):
                candidate = source / name
                if candidate.is_file():
                    return candidate.resolve()
            raise ConfigurationError(f"directory has no main.tex or main.pdf: {source}")
        suffix = source.suffix.casefold()
        if suffix not in {".tex", ".pdf"}:
            raise ConfigurationError("supported source extensions are .tex and .pdf")
        return source.resolve()

    def _load_config_and_rubric(
        self,
        request: RunRequest,
    ) -> tuple[NormocontrolConfig, EffectiveRubric]:
        try:
            config = load_config(request.config_path)
            if request.profile is not None:
                try:
                    chosen = WorkProfile(request.profile)
                except ValueError as error:
                    raise ConfigurationError(f"unknown profile: {request.profile}") from error
                config = config.model_copy(update={"work_profile": chosen})
            rubric = expand_rubric(load_rubric(request.rubric_path), config)
        except LocatedValidationError:
            raise
        except (OSError, ValidationError, ValueError) as error:
            raise ConfigurationError(f"invalid config/rubric: {error}") from error
        return config, rubric

    def _source_hash(self, source: Path) -> str:
        if source.suffix.casefold() == ".tex":
            root = source.parent
            files = [path for path in root.rglob("*") if path.is_file()]
            return hash_paths(files)
        return hash_file(source)

    def _extract_only(
        self,
        source: Path,
    ) -> tuple[DocumentBundle, LatexProject | None, Path | None]:
        root = source.parent
        suffix = source.suffix.casefold()
        if suffix == ".tex":
            bundle = LatexExtractor(root).extract(source)
            return bundle, LatexProject(root=root, main_tex=source), None
        bundle = PdfExtractor(root).extract(source)
        return bundle, None, source

    def _stage_build(
        self,
        *,
        request: RunRequest,
        source: Path,
        cache: StageCache,
        base_key: dict[str, str],
        state: RunState,
    ) -> tuple[StageResult, DocumentBundle, LatexProject | None, Path | None, dict[str, Any]]:
        started = self._hooks.clock()
        key = CacheKeyParts(stage=StageName.BUILD.value, model_hash="none", **base_key)
        cached = cache.get(key)
        if cached is not None:
            bundle = DocumentBundle.model_validate(cached["bundle"])
            latex = None
            if cached.get("latex_main"):
                latex = LatexProject(
                    root=Path(cached["latex_root"]),
                    main_tex=Path(cached["latex_main"]),
                )
            pdf_path = Path(cached["pdf_path"]) if cached.get("pdf_path") else None
            cached_findings = tuple(
                Finding.model_validate(item) for item in cached.get("findings", [])
            )
            cached_meta = dict(cached.get("meta", {}))
            cached_meta["cache"] = "hit"
            duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
            stage = StageResult(name="build", findings=cached_findings, duration_ms=duration)
            return stage, bundle, latex, pdf_path, cached_meta

        findings: list[Finding] = []
        meta: dict[str, Any] = {"cache": "miss"}
        try:
            bundle, latex, pdf_path = self._extract_only(source)
        except ExtractionError as error:
            raise ConfigurationError(str(error)) from error

        if latex is not None:
            build_service = self._hooks.build_service or LatexBuildService()
            result = build_service.build(latex.root, latex.main_tex)
            meta["latexmk_status"] = result.status.value
            meta["latexmk_returncode"] = result.returncode
            if result.status is LatexBuildStatus.SUCCESS:
                compiled = latex.main_tex.with_suffix(".pdf")
                if compiled.is_file():
                    pdf_path = compiled
            elif result.status is LatexBuildStatus.TOOL_MISSING:
                findings.append(
                    Finding(
                        rule_id="SYS-03",
                        layer=RuleLayer.SCRIPT,
                        severity=Severity.WARN,
                        status=FindingStatus.UNVERIFIABLE,
                        message="latexmk недоступен; продолжение в degraded mode без PDF",
                    )
                )
                meta["degraded"] = True
            else:
                status = (
                    FindingStatus.FAIL
                    if request.fail_closed
                    else FindingStatus.UNVERIFIABLE
                )
                severity = Severity.ERROR if request.fail_closed else Severity.WARN
                findings.append(
                    Finding(
                        rule_id="SYS-03",
                        layer=RuleLayer.SCRIPT,
                        severity=severity,
                        status=status,
                        message=f"сборка LaTeX не удалась: {result.status.value}",
                        evidence=(Evidence(locator="latexmk"),),
                    )
                )
                meta["degraded"] = not request.fail_closed
                if request.fail_closed:
                    state.exit_code = ExitCode.INTERNAL_ERROR
                    state.messages.append("build failed with fail_closed=true")

        cache.put(
            key,
            {
                "bundle": json.loads(bundle.model_dump_json()),
                "latex_root": str(latex.root) if latex else None,
                "latex_main": str(latex.main_tex) if latex else None,
                "pdf_path": str(pdf_path) if pdf_path else None,
                "findings": [json.loads(item.model_dump_json()) for item in findings],
                "meta": meta,
            },
        )
        duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
        return (
            StageResult(name="build", findings=tuple(findings), duration_ms=duration),
            bundle,
            latex,
            pdf_path,
            meta,
        )

    def _stage_formal(
        self,
        *,
        request: RunRequest,
        config: NormocontrolConfig,
        rubric: EffectiveRubric,
        bundle: DocumentBundle | None,
        latex: LatexProject | None,
        pdf_path: Path | None,
        cache: StageCache,
        base_key: dict[str, str],
        state: RunState,
    ) -> tuple[StageResult, tuple[Finding, ...]]:
        started = self._hooks.clock()
        filtered = filter_rubric(rubric, request.only.allows_rule)
        key = CacheKeyParts(
            stage=StageName.FORMAL.value,
            model_hash=hash_text(f"fail_closed={request.fail_closed}"),
            **base_key,
        )
        cached = cache.get(key)
        if cached is not None:
            findings = tuple(Finding.model_validate(item) for item in cached["findings"])
            duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
            return StageResult(name="formal", findings=findings, duration_ms=duration), findings

        if bundle is None:
            raise ConfigurationError("document bundle missing before formal stage")

        context = ExecutionContext(
            rubric=filtered,
            config=config,
            bundle=bundle,
            latex=latex,
            pdf_path=pdf_path,
            bib_paths=(),
            fail_closed=request.fail_closed,
            canceled=self._canceled,
        )
        try:
            result = FormalEngine(
                default_formal_registry(build_service=self._hooks.build_service)
            ).run(context)
        except Exception as error:
            if request.fail_closed:
                state.exit_code = ExitCode.INTERNAL_ERROR
                state.messages.append(f"formal engine exception: {type(error).__name__}")
                finding = Finding(
                    rule_id="SYS-03",
                    layer=RuleLayer.SCRIPT,
                    severity=Severity.ERROR,
                    status=FindingStatus.FAIL,
                    message=f"formal engine error: {type(error).__name__}",
                )
                findings = (finding,)
            else:
                finding = Finding(
                    rule_id="SYS-03",
                    layer=RuleLayer.SCRIPT,
                    severity=Severity.WARN,
                    status=FindingStatus.UNVERIFIABLE,
                    message=f"formal engine error: {type(error).__name__}",
                )
                findings = (finding,)
                state.messages.append("formal engine exception treated as unverifiable")
            duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
            cache.put(key, {"findings": [json.loads(item.model_dump_json()) for item in findings]})
            return StageResult(name="formal", findings=findings, duration_ms=duration), findings

        findings = result.findings
        cache.put(key, {"findings": [json.loads(item.model_dump_json()) for item in findings]})
        duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
        return StageResult(name="formal", findings=findings, duration_ms=duration), findings

    def _stage_semantic(
        self,
        *,
        request: RunRequest,
        bundle: DocumentBundle | None,
        cache: StageCache,
        base_key: dict[str, str],
        state: RunState,
    ) -> tuple[StageResult, tuple[Finding, ...]]:
        started = self._hooks.clock()
        if bundle is None:
            finding = Finding(
                rule_id="GEN-01",
                layer=RuleLayer.LLM,
                severity=Severity.WARN,
                status=FindingStatus.UNVERIFIABLE,
                message="semantic stage skipped: document bundle missing",
            )
            duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
            stage = StageResult(
                name="semantic",
                findings=(finding,),
                duration_ms=duration,
            )
            return stage, (finding,)

        try:
            llm_config = load_llm_config(
                provider_override=request.provider,
                no_llm=request.no_llm,
            )
        except ConfigurationError as error:
            finding = Finding(
                rule_id="GEN-01",
                layer=RuleLayer.LLM,
                severity=Severity.WARN,
                status=FindingStatus.UNVERIFIABLE,
                message=f"semantic provider config error: {error}",
            )
            state.messages.append(str(error))
            duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
            stage = StageResult(
                name="semantic",
                findings=(finding,),
                duration_ms=duration,
            )
            return stage, (finding,)

        model_hash = hash_text(f"{llm_config.provider.value}:{llm_config.model or 'none'}")
        key = CacheKeyParts(stage=StageName.SEMANTIC.value, model_hash=model_hash, **base_key)
        cached = cache.get(key)
        if cached is not None:
            findings = tuple(Finding.model_validate(item) for item in cached["findings"])
            duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
            return StageResult(name="semantic", findings=findings, duration_ms=duration), findings

        try:
            provider = self._make_provider(llm_config)
            report: SemanticReport = SemanticEngine(
                provider,
                model_id=llm_config.model or provider.name,
            ).run(bundle)
            selected = [
                item for item in report.findings if request.only.allows_rule(item.rule_id)
            ]
            findings = tuple(semantic_finding_to_domain(item) for item in selected)
        except Exception as error:
            finding = Finding(
                rule_id="GEN-01",
                layer=RuleLayer.LLM,
                severity=Severity.WARN,
                status=FindingStatus.UNVERIFIABLE,
                message=f"semantic tool error: {type(error).__name__}",
            )
            findings = (finding,)
            state.messages.append(f"semantic advisory tool error: {type(error).__name__}")

        cache.put(key, {"findings": [json.loads(item.model_dump_json()) for item in findings]})
        duration = max(0.0, (self._hooks.clock() - started) * 1000.0)
        return StageResult(name="semantic", findings=findings, duration_ms=duration), findings

    def _make_provider(self, llm_config: Any) -> LlmProvider:
        if self._hooks.provider_factory is not None:
            return self._hooks.provider_factory()
        if llm_config.provider is ProviderName.DISABLED:
            return DisabledProvider()
        if llm_config.provider is ProviderName.OLLAMA:
            return OllamaProvider(llm_config)
        return YandexProvider(llm_config)

    def _resolve_exit_code(
        self,
        formal_findings: tuple[Finding, ...],
        state: RunState,
    ) -> ExitCode:
        if state.exit_code is ExitCode.INTERNAL_ERROR:
            return ExitCode.INTERNAL_ERROR
        if formal_findings:
            return formal_exit_code(formal_findings)
        return ExitCode.SUCCESS

    def _canceled_report(
        self,
        request: RunRequest,
        stages: list[StageResult],
        state: RunState,
    ) -> RunReport:
        state.canceled = True
        state.messages.append("run canceled")
        report = RunReport(
            tool_version=request.tool_version,
            exit_code=ExitCode.SUCCESS
            if not any(
                finding.status is FindingStatus.FAIL
                for stage in stages
                for finding in stage.findings
            )
            else ExitCode.FORMAL_FAILURE,
            stages=tuple(stages),
        )
        atomic_write_json(
            request.out_dir / "canceled.json",
            {
                "canceled": True,
                "completed_stages": state.completed_stages,
                "messages": state.messages,
                "exit_code": int(report.exit_code),
            },
        )
        atomic_write_json(
            request.out_dir / "report.json",
            json.loads(report.model_dump_json()),
        )
        return report

    @staticmethod
    def _write_stage_artifact(
        out_dir: Path,
        stage: StageName,
        result: StageResult,
        meta: dict[str, Any],
    ) -> None:
        atomic_write_json(
            out_dir / "stages" / f"{stage.value}.json",
            {
                "stage": json.loads(result.model_dump_json()),
                "meta": meta,
            },
        )


def apply_final_severity(rubric: EffectiveRubric) -> EffectiveRubric:
    """Apply ``severity_final`` where present (explicit ``--final`` only)."""
    updated = []
    for rule in rubric.rules:
        if rule.severity_final is not None:
            updated.append(rule.model_copy(update={"severity": rule.severity_final}))
        else:
            updated.append(rule)
    return rubric.model_copy(update={"rules": tuple(updated)})


def filter_rubric(
    rubric: EffectiveRubric,
    predicate: Callable[[str], bool],
) -> EffectiveRubric:
    """Keep rules accepted by ``predicate`` without mutating disabled semantics."""
    kept = tuple(rule for rule in rubric.rules if predicate(rule.id))
    return rubric.model_copy(update={"rules": kept})


def semantic_finding_to_domain(item: SemanticFinding) -> Finding:
    """Convert an advisory semantic finding into the public ``Finding`` contract."""
    status = {
        SemanticStatus.PASS: FindingStatus.INFO,
        SemanticStatus.WARN: FindingStatus.WARN,
        SemanticStatus.INFO: FindingStatus.INFO,
        SemanticStatus.NOT_APPLICABLE: FindingStatus.NOT_APPLICABLE,
        SemanticStatus.UNVERIFIABLE: FindingStatus.UNVERIFIABLE,
    }[item.status]
    severity = Severity.WARN if status is FindingStatus.WARN else Severity.INFO
    evidence = tuple(
        Evidence(locator=entry.locator, description=entry.quote) for entry in item.evidence
    )
    return Finding(
        rule_id=item.rule_id,
        layer=RuleLayer.LLM,
        severity=severity,
        status=status,
        message=item.summary,
        evidence=evidence,
    )


def run_pipeline(request: RunRequest, hooks: OrchestratorHooks | None = None) -> RunReport:
    """Public helper used by CLI and tests."""
    return Orchestrator(hooks).run(request)
