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

## Reusable workflow for a private thesis repository

The public GostCheck repository keeps its own synthetic self-tests in
`.github/workflows/normocontrol.yml`. A consumer repository calls the separate
`.github/workflows/reusable-thesis.yml` workflow through its `workflow_call`
trigger. The consumer checkout is the source of `submission_path`; the reusable
workflow never substitutes `tests/fixtures/demo/pass` or
`tests/fixtures/demo/fail`.

Use a private repository for the thesis and pin GostCheck to a reviewed commit
SHA or an immutable release tag. The following is a complete consumer workflow
for `.github/workflows/thesis.yml`:

```yaml
name: Thesis formal validation

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  thesis:
    uses: TopTatarin/GostCheck/.github/workflows/reusable-thesis.yml@v0.2.0
    with:
      submission_path: thesis/main.tex
      profile: software
      fail_closed: true
      upload_report: true
      provider: disabled
```

For the strongest supply-chain pin, replace `v0.2.0` with the full 40-character
pinned commit SHA that contains the reviewed reusable workflow. Do not use a
moving branch such as `main`. The caller grants only `contents: read` for
checkouts and `pull-requests: write` for the metadata-only PR comment. Do not
use `pull_request_target`.

`submission_path` is relative to the root of the private consumer checkout and
may identify a project directory, `.tex`, or `.pdf`. The workflow rejects an
absolute path, `..`, NUL/control characters, missing targets, unsupported file
types, and a symlink or junction that resolves outside the checkout. Both the
preflight job and `formal-gate` validate the path; `formal-gate` runs
`normocontrol run` on that resolved consumer input.

Allowed profiles are `software` and `research`. `fail_closed: true` is the safe
default. `provider: disabled` keeps document text local to the runner. Any
semantic provider remains advisory: it is not in the required formal dependency
chain and must not be configured as a required branch-protection check.

When `upload_report` is true, the artifact contains `report.json`, `report.md`,
`run_state.json`, stage JSON diagnostics, and a technical log. Its path list
does not include the submitted `.tex`, source tree, or PDF. The PR comment
contains only the checked relative path, caller commit SHA, profile, gate, and
run URL. It never copies report findings or thesis content.

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

The same required job first runs the unchanged source-level `normocontrol`
pass/fail fixtures, then installs TeX and runs the hard build checks. This
ordering avoids feeding the deliberately free CI font into the separate PDF
rule that requires an embedded Times-compatible font name; that public rule is
not weakened. The job cannot finish green before the later PDF and ChkTeX
checks succeed.

The gate verifies that a missing `.sty`, a permanently unresolved
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

In a private consumer repository, require the reusable `lint-and-unit` and
`formal-gate` results after confirming their exact names in a completed run.
Keep `publish-report` and every semantic/advisory result non-required.

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
