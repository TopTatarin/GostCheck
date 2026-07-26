# Troubleshooting

## Reusable workflow rejects submission_path

**Symptom:** consumer preflight or `formal-gate` reports
`invalid submission_path`.
**Action:** pass a path relative to the private repository root, for example
`thesis/main.tex` or `submissions/current.pdf`. Do not pass an absolute path,
`..`, a NUL/control character, or a missing target. A symlink or Windows
junction may point within the checkout, but any escape outside the consumer
workspace is rejected. Confirm that the private caller checks out the file and
that its case matches exactly on Linux.

If the submitted project is valid but the action cannot install GostCheck,
confirm the consumer pins a release tag or full commit SHA containing both
`.github/workflows/reusable-thesis.yml` and the nested setup action. Do not
replace the private `submission_path` with a public synthetic fixture to make
the gate green.

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
The source-level `normocontrol` fixture checks run before TeX setup; the same
required job then installs TeX and must pass the independent XeLaTeX build.

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
Termes at compile time via `\IfFontExistsTF`; Polyglossia uses FreeSerif for
Cyrillic glyphs. If fallback lookup fails, verify `fc-match "TeX Gyre Termes"`
and the `FreeSerif`, `FreeSans`, and `FreeMono` families with `fc-match`, then
install `fonts-texgyre` and `fonts-freefont-ttf`.

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
**Action:** Run `ollama ps`. `100% CPU` is a valid fallback but not a GPU baseline.
For OOM, free VRAM or reduce `LLM_NUM_CTX`/`--num-ctx`; values above the tested 8192
are explicit opt-in. Use `CUDA_VISIBLE_DEVICES=-1` only after restarting the daemon
as described in [gpu-runbook.md](gpu-runbook.md). Semantic stays advisory — formal
merge unaffected.

## Ollama doctor is UNVERIFIABLE

**Symptom:** `normocontrol llm doctor --provider ollama` does not return `status=OK`.
**Action:** Read `detail`: `endpoint is unavailable` means the daemon is unreachable;
`configured model is not available` means run `ollama pull qwen3:8b-q4_K_M`;
`strict JSON schema capability is unavailable` means the daemon/model cannot satisfy
the mandatory schema probe. Do not bypass the schema. On Windows keep the default
`http://127.0.0.1:11434/v1`; `localhost` may resolve to IPv6. Local Ollama calls ignore
HTTP proxy variables, so a corporate proxy cannot capture synthetic or document text.

## Ollama response is unverifiable

**Symptom:** detail mentions token-limit truncation or JSON schema mismatch.
**Action:** Increase `LLM_MAX_OUTPUT_TOKENS` only within the available context/VRAM, or
shorten the input. A complete Markdown-fenced JSON object is accepted and still
Pydantic-validated. Separate `thinking`/`reasoning` is never treated as answer content;
Qwen3 is called with `think: false`. Invalid output stays `unverifiable` and cannot
change the formal merge gate.

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

## CLI summary says report was not generated

**Symptom:** `normocontrol run` prints `(not generated)` after `report.md` or
`report.json`.
**Action:** First read the `exit_code` line. Codes `3` and `4` stop before
aggregate and normally have no fresh reports. Fix the input/configuration for
code `3`; for code `4`, rerun with the same flags after checking the tool
failure. A command using `--only` without `aggregate` may intentionally omit
`report.md`; include the aggregate stage for both published reports. Do not
mistake files left by an older run in an existing output directory for fresh
artifacts: an error summary always marks both as not generated.

## CLI summary path is shortened

**Symptom:** `input`, `report.md`, or `report.json` starts with `…/`.
**Action:** This is the privacy-safe representation of a path outside the
current checkout. Relative paths inside the checkout remain directly usable.
Pass a relative `--out` under the checkout if a fully navigable console path is
needed; do not disable redaction or print environment/provider payloads.

## Formal per-rule metric has zero denominators

**Symptom:** `evaluate_formal_fixtures.py` prints
`expected=0 actual=0 TP=0 FP=0 FN=0 TN=0` and zero precision/recall/F1.
**Action:** The rule is absent from the annotated synthetic corpus. Add a
synthetic fixture and catalog labels for that `rule_id`; do not copy a real ВКР
into the repository. Zero metrics are intentional and do not fabricate perfect
coverage.

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
