# GitHub Actions for NORMACTRL

Workflow file: [`.github/workflows/normocontrol.yml`](../.github/workflows/normocontrol.yml).

## Jobs

| Job | Required for merge | Role |
|-----|--------------------|------|
| `lint-and-unit` | **yes** | ruff, mypy, pytest+coverage |
| `build-latex` | no | diagnostic XeLaTeX build; a failure is visible but this job is not a required branch-protection check |
| `formal-gate` | **yes** | mandatory XeLaTeX + biber build, PDF/reference validation, blocking ChkTeX, and deterministic `normocontrol run` checks |
| `publish-report` | no | downloads artifact and upserts one PR comment |

Semantic/LLM jobs are intentionally **not** in this workflow and must never be required checks.
See [`.github/workflows/semantic-advisory.yml`](../.github/workflows/semantic-advisory.yml),
[self-hosted-runner.md](self-hosted-runner.md), and [cloud-fallback.md](cloud-fallback.md).

## Triggers and safety

- `pull_request`, `workflow_dispatch`
- **No** `pull_request_target`
- Default `permissions: contents: read`
- `publish-report` adds `pull-requests: write` only
- Concurrency cancels outdated runs for the same PR
- Official actions are pinned to major versions (`checkout@v7`, `setup-python@v7`, `upload-artifact@v4`)

## Artifacts

- `normocontrol-report-<sha>` — `report.json`, `report.md`, `summary.json` (pass + fail outs)
- `normocontrol-report-<sha>` also contains formal-gate LaTeX, biber, and ChkTeX logs
- `latex-build-<sha>` — logs and PDF from the diagnostic build

Both upload steps use `if: always()`, so diagnostics remain available when
compilation, unresolved-reference validation, ChkTeX, or the formal rules fail.

## Mandatory TeX contract

The composite setup action installs the explicit Ubuntu package set only when
`install-tex: "true"` is requested. The set provides `latexmk`, `chktex`,
XeLaTeX, `biber`, `biblatex-gost`, Cyrillic support, and TeX Gyre fonts.
The LaTeX jobs are pinned to `ubuntu-24.04`; `formal-gate` requests the
toolchain directly and therefore cannot treat a missing `latexmk` as a
degraded success.

The synthetic compile fixture intentionally lives below a path containing
spaces, contains Cyrillic text and a biber bibliography, and emits a benign
package warning while still producing a non-empty PDF. Its class retains the
auditable `Times New Roman` requirement and uses `\IfFontExistsTF` to fall back
to `TeX Gyre Termes` on GitHub-hosted runners. Polyglossia uses FreeSerif for
Cyrillic glyphs missing from Ubuntu 24.04's TeX Gyre Termes. Proprietary Times
New Roman is not installed in CI.

The same gate verifies that a missing `.sty`, a permanently unresolved
reference, a biber parse error, and a blocking ChkTeX diagnostic all return
nonzero. `latexmk -Werror` promotes final unresolved reference/citation
diagnostics after all required passes; the explicit final-log check provides
a second guard. Unrelated warnings do not invalidate a non-empty PDF.

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

# Linux with the packages from docs/setup-linux.md installed:
fixture_dir="tests/fixtures/latex-ci/compile-pass/source with spaces"
mkdir -p build/latex/local
(cd "$fixture_dir" && latexmk -xelatex -Werror -interaction=nonstopmode \
  -halt-on-error -file-line-error \
  -outdir="$PWD/../../../../../build/latex/local" main.tex)
test -s build/latex/local/main.pdf
chktex -q "$fixture_dir/main.tex"
```
