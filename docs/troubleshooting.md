# Troubleshooting

## latexmk / chktex missing

**Symptom:** `doctor` shows not found, or CI fails during TeX setup.
**Action:** Install the package set from [setup-linux.md](setup-linux.md).
`formal-gate` requires `latexmk`, `chktex`, XeLaTeX, and `biber`; none of these
tools has a degraded-success path.

## LaTeX compilation or biber fails

**Symptom:** `formal-gate` stops before `normocontrol run`; the artifact contains
`latexmk.log`, `.log`, or `.blg`.
**Action:** Download `normocontrol-report-<sha>` and inspect `build/latex/`.
An absent `.sty` or a biber parse error is blocking. Reproduce with
`latexmk -xelatex -Werror -interaction=nonstopmode -halt-on-error -file-line-error
-outdir=build/latex/local main.tex`.

## PDF exists but references are unresolved

**Symptom:** `latexmk` creates a PDF but `formal-gate` reports a blocking
unresolved reference or citation.
**Action:** Fix the missing `\label`, citation key, or bibliography input.
The gate already lets `latexmk` perform the necessary reruns; remaining
undefined-reference diagnostics are therefore blocking.

## ChkTeX blocks formal-gate

**Symptom:** `build/latex/formal-pass/chktex.log` contains a diagnostic and
`formal-gate` is red.
**Action:** Run `chktex -q path/to/main.tex`, fix the reported source issue, and
rerun the gate. Blocking diagnostics are not suppressed with `|| true`.

## Times New Roman absent on CI

**Symptom:** the synthetic fixture runs on a host without Times New Roman.
**Action:** No proprietary font is needed. The synthetic `.cls` keeps the
Times New Roman declaration for formal inspection and falls back to TeX Gyre
Termes at compile time via `\IfFontExistsTF`. If fallback lookup fails, verify
`fc-match "TeX Gyre Termes"` and install `fonts-texgyre`.

## Missing font / PDF geometry

**Symptom:** FMT-* unverifiable or fail on real PDF.  
**Action:** Ensure fonts embedded; re-export PDF; check
[formal-engine.md](formal-engine.md). Synthetic demo fixtures may report
unverifiable PDF metrics without failing the gate.

## PDF extraction / encrypted PDF

**Symptom:** ExtractionError or empty sections.  
**Action:** Unlock PDF; prefer LaTeX source when available; confirm path stays
inside project root (no `..` escapes).

## Ollama CPU / OOM

**Symptom:** Slow replies, `100% CPU`, process killed.  
**Action:** See [gpu-runbook.md](gpu-runbook.md): reduce `--num-ctx`, free VRAM,
or `CUDA_VISIBLE_DEVICES=-1` for CPU. Semantic stays advisory — formal merge
unaffected.

## GitHub token / PR comment

**Symptom:** publish-report neutral / 403.  
**Action:** Fork PRs lack `pull-requests: write`; artifact still uploaded.
Rerun on a branch in the home repo.

## Runner offline / queued forever

**Symptom:** `semantic-ollama` pending.  
**Action:** Expected when self-hosted is down. Formal checks still merge-ready.
See [self-hosted-runner.md](self-hosted-runner.md).

## Artifact missing

**Symptom:** `--missing-artifact` PR comment.  
**Action:** Re-run `formal-gate`; confirm `upload-artifact` `if: always()`.

## Yandex 401 / 429

**Symptom:** cloud_blocked or tool_error_advisory in `status.json`.  
**Action:** Check `YANDEX_AI_API_KEY`, model URI (`YANDEX_MODEL`), quotas.
Use official Yandex AI Studio pricing / model gallery — **do not hardcode
prices** in code. Require `ALLOW_CLOUD_DATA=true` for real documents.
See [cloud-fallback.md](cloud-fallback.md).

## Windows ExecutionPolicy

**Symptom:** `.ps1` cannot run.  
**Action:** `powershell -ExecutionPolicy Bypass -File ...` or CurrentUser
RemoteSigned ([setup-windows.md](setup-windows.md)).
