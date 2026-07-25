# Formal rule engine

The formal engine executes deterministic `class` and `script` rubric rules. It is
the blocking path for merge gates: findings with `severity=error` and either
`status=fail` or `status=unverifiable` on a formal layer produce exit code `2`.
An `unverifiable` result is reported as an incomplete check, not as a confirmed
violation.

## Components

| Module | Responsibility |
|--------|----------------|
| `rules/base.py` | `FormalRule` protocol, `RuleRunOutcome`, `RuleExecutionError` |
| `rules/context.py` | `ExecutionContext`, `LatexProject`, required `SourceKind` flags |
| `rules/registry.py` | Rule id registration, duplicate detection, `implemented` / `unsupported` |
| `rules/engine.py` | Rule scheduling, deterministic sorting, fingerprints, parallel mode |
| `rules/gate.py` | Merge gate policy and exit code mapping |

## Execution flow

1. Load `EffectiveRubric` and build `ExecutionContext`. For LaTeX runs, `bundle`
   retains AST-derived sections, discovered bibliography files are passed through
   `bib_paths`, and compiled-PDF spans/pages are carried independently in
   `pdf_bundle`.
2. Select enabled rules whose capabilities include `class` or `script`.
3. For each rule in rubric order:
   - missing registry entry → `unverifiable`
   - `unsupported` registration → `unverifiable`
   - required sources absent → `unverifiable` (PDF-only runs never fake a pass for LaTeX/Bib rules)
   - `supports()` is false → `not_applicable`
   - otherwise run the rule; exceptions become `tool_error` findings
4. Sort findings by rubric order, evidence locator, fingerprint.
5. Evaluate gate policy and return exit code `0` or `2`.

## Gate policy

Blocking finding:

- layer is `class`, `script`, or `class+script`
- severity is `error`
- status is `fail` (confirmed violation) or `unverifiable` (blocking incomplete check)

Non-blocking: warning/info severities, `not_applicable`, and all advisory
LLM/vision `unverifiable` findings.

With `fail_closed=true`, isolated tool errors become blocking `fail` findings.
With `fail_closed=false`, the same errors are reported as `unverifiable` warnings.

Published schema `1.2` keeps separate `formal_errors` and
`blocking_unverifiable` counters. The general `unverifiable` counter still
contains both blocking formal and non-blocking advisory results.
The published header sets `degraded=true` whenever
`blocking_unverifiable > 0`, even if the build stage itself completed. Missing
formal sources/tools are therefore visible in the JSON header, counts, Markdown,
and GitHub summary. LLM/vision incomplete checks never increment the blocking
counter and do not enable degraded mode by themselves.

## PDF-only formatting

For a PDF input with a usable text layer, FMT-01, FMT-02, FMT-03, and FMT-05
run directly against PyMuPDF `DocumentBundle` page/span geometry. They do not
require a `LatexProject`:

- FMT-01 checks Times New Roman-compatible font names and approved size.
- FMT-02 checks detected headings for bold typography.
- FMT-03 estimates the line-spacing ratio from baselines.
- FMT-05 checks measurable page text against configured margins.

FMT-04 remains `unverifiable` for PDF-only input because paragraph indentation
cannot be established reliably from span geometry. A PDF without a text layer
therefore produces a blocking incomplete result rather than PASS. Corrupt and
password-protected PDFs are rejected during extraction.

## Fingerprints

Each finding can be serialized with a stable SHA-256 fingerprint over its JSON
payload. Parallel and sequential runs must produce identical serialized output.

## Example

```python
from normocontrol.rules import ExecutionContext, FormalEngine, RuleRegistry

registry = RuleRegistry()
engine = FormalEngine(registry)
result = engine.run(context)
assert result.exit_code in {0, 2}
```

Individual rule implementations are registered in later tasks (`D-02` … `D-05`).
