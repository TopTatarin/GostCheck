# Formal rule engine

The formal engine executes deterministic `class` and `script` rubric rules. It is
the blocking path for merge gates: only findings with `severity=error`,
`status=fail`, and a formal layer can produce exit code `2`.

## Components

| Module | Responsibility |
|--------|----------------|
| `rules/base.py` | `FormalRule` protocol, `RuleRunOutcome`, `RuleExecutionError` |
| `rules/context.py` | `ExecutionContext`, `LatexProject`, required `SourceKind` flags |
| `rules/registry.py` | Rule id registration, duplicate detection, `implemented` / `unsupported` |
| `rules/engine.py` | Rule scheduling, deterministic sorting, fingerprints, parallel mode |
| `rules/gate.py` | Merge gate policy and exit code mapping |

## Execution flow

1. Load `EffectiveRubric` and build `ExecutionContext`.
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
- status is `fail`

Non-blocking: `warn`, `info`, `unverifiable`, `not_applicable`, advisory layers.

With `fail_closed=true`, isolated tool errors become blocking `fail` findings.
With `fail_closed=false`, the same errors are reported as `unverifiable` warnings.

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
