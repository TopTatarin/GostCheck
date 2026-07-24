# Demo: reproducible pass / fail / fix cycle

Scripts and golden contracts for showing how formal-gate allows or blocks merge.
Student PDFs stay out of git (`samples/private/`).

## Quick start (safe)

```powershell
powershell -ExecutionPolicy Bypass -File demo/run_demo.ps1 -Mode dry-run
```

```bash
bash demo/run_demo.sh --mode dry-run
```

Default **dry-run**:

1. Runs local golden checks on `tests/fixtures/demo/{pass,fail}` plus a **fixed** copy (STR-01 repaired).
2. Compares reports to `demo/expected/*-report.json`.
3. Prints the planned `git`/`gh` commands for demo PRs.
4. **Does not** call mutating `gh`/`git` commands.

## Expected local exits

| Fixture | Exit | Gate | Blocking |
|---------|-----:|------|----------|
| `tests/fixtures/demo/pass` | 0 | pass | — |
| `tests/fixtures/demo/fail` | 2 | fail | `STR-01` (section order) |
| fixed (fail + pass `main.tex`) | 0 | pass | — |

## GitHub scenarios (manual / execute plan)

| Scenario | Branch | Intent |
|----------|--------|--------|
| A | `demo/pass` | Safe text on pass fixture → required checks green → merge allowed after human approval |
| B | `demo/fail` | One controlled STR-01 violation → `formal-gate` blocks → fix commit → merge opens |

**Required checks (branch protection):** `lint-and-unit`, `formal-gate`  
**Never required:** `build-latex`, `publish-report`, any `semantic-*`  
**PR comment marker:** `<!-- normocontrol-report -->`  
**Manual step:** нормоконтролёр reviews advisory comment / report artifact, then approves merge.

` --mode execute-github` only prints the command plan after allowlist + `--i-understand-github-mutations`. It still **does not** auto-commit, push, merge, or delete branches (protected-branch / stale-PR corner cases stay manual).

Allowlist remote: `TopTatarin/GostCheck`.

## Private baseline (software / research)

Place local PDFs under `samples/private/` (gitignored) or pass paths:

```powershell
powershell -ExecutionPolicy Bypass -File demo/run_demo.ps1 -Mode baseline `
  -SoftwarePdf samples/private/anisimova.pdf `
  -ResearchPdf samples/private/zoloev.pdf
```

- Missing files → clear **SKIP** (not a failure).
- Reports go to `build/demo/baseline/` (gitignored) and are marked **exploratory / legacy-input**.
- This is **not** a claim that historical theses must satisfy the draft 2026 rubric.
- Profiles: software keeps ARC/ALG/IMP; research disables ARC/ALG/IMP prefixes.

## Artifacts to expect in Actions

- `normocontrol-report-<sha>` — `report.json`, `report.md`, `summary.json`
- PR comment upserted by `scripts/ci_comment.py` with the marker above
- Semantic advisory (if dispatched) is optional and non-blocking
