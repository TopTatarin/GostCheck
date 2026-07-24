# GitHub Actions for NORMACTRL

Workflow file: [`.github/workflows/normocontrol.yml`](../.github/workflows/normocontrol.yml).

## Jobs

| Job | Required for merge | Role |
|-----|--------------------|------|
| `lint-and-unit` | **yes** | ruff, mypy, pytest+coverage |
| `build-latex` | no | best-effort latexmk; degraded marker if missing |
| `formal-gate` | **yes** | `normocontrol run` on demo pass (must be 0); fail fixture must exit 2; uploads artifacts `if: always()` |
| `publish-report` | no | downloads artifact and upserts one PR comment |

Semantic/LLM jobs are intentionally **not** in this workflow and must never be required checks.

## Triggers and safety

- `pull_request`, `workflow_dispatch`
- **No** `pull_request_target`
- Default `permissions: contents: read`
- `publish-report` adds `pull-requests: write` only
- Concurrency cancels outdated runs for the same PR
- Official actions are pinned to major versions (`checkout@v7`, `setup-python@v7`, `upload-artifact@v4`)

## Artifacts

- `normocontrol-report-<sha>` — `report.json`, `report.md`, `summary.json` (pass + fail outs)
- `latex-build-<sha>` — latex logs / degraded status

## PR comment

`scripts/ci_comment.py` updates a single comment marked with:

```text
<!-- normocontrol-report -->
```

Fork PRs / read-only tokens finish **neutral** (exit 0) and still keep artifacts.

```bash
python scripts/ci_comment.py --summary build/pass/summary.json --repo OWNER/REPO --pr 123
python scripts/ci_comment.py --missing-artifact --neutral --repo OWNER/REPO --pr 123
```

## Branch protection (manual Settings step)

Required status checks on `main`:

1. `lint-and-unit`
2. `formal-gate`

Do **not** require `build-latex`, `publish-report`, or any semantic job.

## Local checks

```bash
python -m pytest -q tests/unit/test_ci_comment.py tests/unit/test_workflow_normocontrol.py
actionlint .github/workflows/normocontrol.yml
python -m ruff check scripts/ci_comment.py tests/unit/test_ci_comment.py
```
