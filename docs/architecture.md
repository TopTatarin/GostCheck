# Architecture

## Pipeline

```text
source (.tex/.pdf)
  → build (latexmk / extract)
  → formal (deterministic rules + gate)
  → semantic (LLM advisory, optional)
  → aggregate (report.json, report.md, summary.json)
```

## Layers

| Layer | Blocks merge? | Notes |
|-------|---------------|-------|
| `class` / `script` / `class+script` | yes (exit 2) | Formal findings with severity error + status fail |
| `llm` / `vision` | never | Only warn/info/not_applicable/unverifiable/skipped |

## Profiles

`software` | `research` | `organizational` — explicit only (no `auto`).
Research disables prefixes `ARC`, `ALG`, `IMP`; organizational disables more
(see `normocontrol.rubric.profiles`).

## CI

- **Formal workflow** (`.github/workflows/normocontrol.yml`): PR + dispatch;
  required jobs `lint-and-unit`, `formal-gate`.
- **Semantic advisory** (`.github/workflows/semantic-advisory.yml`): dispatch only;
  never required.

## Related docs

- [data-flow.md](data-flow.md)
- [formal-engine.md](formal-engine.md)
- [github-actions.md](github-actions.md)
- [llm-providers.md](llm-providers.md)
