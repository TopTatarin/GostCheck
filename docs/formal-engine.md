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

- FMT-01 strips six-letter PDF subset prefixes and checks an explicit allowlist
  of Times-compatible families and their explicit regular/bold/italic aliases.
  It weights the font and size ratios by significant characters, not span
  count. Repeated headers/footers, page numbers, geometry-confirmed headings,
  captions, numeric multi-row tables, contextual formula clusters, and
  multi-line monospaced code blocks are excluded before measuring body text.
  A font name alone never removes code or formula text: unconfirmed inline
  monospace and Computer Modern spans remain in the denominator and are
  reported as retained classifications. An empty, too small, or geometrically
  unreliable body sample is `unverifiable`, never PASS.
- FMT-02 checks detected headings for bold typography.
- FMT-03 estimates the line-spacing ratio from baselines.
- FMT-05 checks each measurable body span, embedded image, and meaningful
  vector-object bbox against configured margins. A bare page number in the
  footer zone and repeated marginalia are classified deterministically from
  geometry and cross-page repetition. The rest of the lower page is not
  ignored, so ordinary text or graphics outside any allowed boundary still
  fail. The written policy decision approved for this implementation is option
  B (task approval dated 2026-07-29): apply a configurable
  `geometry_tolerance_pt` only to PDF-coordinate comparison. The rubric and
  example config record the recommended approved value `0.5` pt; validation
  requires a finite value from `0` through `1` pt. Equality at the configured
  boundary is accepted with a deterministic floating-point comparison, while
  `0.01` pt above it fails. This is not a title-frame exception: the same
  tolerance applies to every measurable body, formula, table, image, and vector
  bbox on every page. Unreliable or zero-area geometry remains unverifiable,
  never PASS. Confirmed body overflow of about `1.7` pt in the Zoloev PDF and
  the table/footer collision of about `2.6` pt on page 42 of the MISIS PDF
  therefore remain blocking FMT-05 failures.

FMT-01 and FMT-05 attach path-safe evidence with the rule id, relative PDF path,
page, bbox, measured bounds/ratios, and a short classification diagnostic.
FMT-05 also records the measured `delta_pt` and effective
`geometry_tolerance_pt` for deterministic audit of the boundary decision.
FMT-01 splits its bounded evidence into the ratio denominators, weighted top
fonts/sizes, excluded and retained category counts, mismatch pages, and
coordinate/hash samples. They use the existing `Finding.evidence`, `path`, and
`page` fields, so the published report schema remains unchanged.

FMT-04 remains `unverifiable` for PDF-only input because paragraph indentation
cannot be established reliably from span geometry. A PDF without a text layer
therefore produces a blocking incomplete result rather than PASS. Corrupt and
password-protected PDFs are rejected during extraction.

## Appendix repository link

APP-01 runs on both LaTeX- and PDF-derived bundles. It searches only sections
identified as appendices, accepts recognizable Git repository URLs, and emits
path-free section-locator evidence. A missing repository URL is informational;
it never creates a blocking failure. A URL elsewhere in the document does not
satisfy the rule, and a document without an appendix is `not_applicable`.

## Annotation counters

ANN-03 requires a LaTeX project and compiled PDF metrics. It extracts all four
declared quantities from the annotation: pages, figures, tables, and appendices.
Physical PDF pages are counted from the extracted page map; float and appendix
counters are derived from comment- and literal-safe expanded LaTeX structure.
PASS is emitted only when every declaration is present, unambiguous, and equal
to its corresponding fact. Missing or conflicting declarations and unreliable
page metrics are `unverifiable`; mismatches retain the effective rubric severity,
including `severity_final` on final runs. Evidence is the path-free annotation
section locator.

## Algorithm structure

ALG-01 and ALG-03 use the LaTeX-derived algorithm section only. ALG-01 checks
for a real `figure` or algorithm-family environment, while ALG-03 checks for a
numbered prose description of the form `Блок N.`. Comments, literal code
environments, and matches in other sections do not satisfy either rule. Missing
sections are `unverifiable`; absent structural markers are non-blocking warnings
with the original rubric severity. Semantic suitability and completeness remain
advisory and cannot create a blocking failure.

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
