# Troubleshooting

## latexmk / chktex missing

**Symptom:** `doctor` shows not found; CI `build-latex` degraded.  
**Action:** Install TeX Live / MiKTeX or ignore for fixture-only formal runs.
Formal-gate on demo fixtures does not require a green latexmk on the runner.

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
