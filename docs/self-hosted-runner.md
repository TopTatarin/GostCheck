# Self-hosted GPU runner (Ollama advisory)

Advisory semantic jobs may run on a labelled Windows GPU machine. They are **never**
required branch-protection checks and must not block formal merge.

Related workflow: [`.github/workflows/semantic-advisory.yml`](../.github/workflows/semantic-advisory.yml).

## Labels

Register the runner with exactly these labels:

```text
self-hosted, windows, x64, gpu, normocontrol
```

The `semantic-ollama` job uses:

```yaml
runs-on: [self-hosted, windows, x64, gpu, normocontrol]
environment: local-gpu
```

## Safety rules

| Rule | Why |
|------|-----|
| Trigger is `workflow_dispatch` only | Public / fork PRs never land on the GPU box automatically |
| `github.ref == refs/heads/main` | Feature branches and arbitrary refs are rejected |
| Checkout `ref: main` | Exact trusted main tip; no SHA input to spoof |
| Environment `local-gpu` with required reviewers | Manual approval before GPU work |
| `permissions: contents: read` | Minimal token |
| No `pull_request` / `pull_request_target` | Untrusted PR code does not execute on self-hosted |
| No `YANDEX_AI_API_KEY` on this job | Cloud secrets stay off the local runner |
| Report retention is 7 days | Advisory diagnostics are not retained indefinitely |
| Cleanup step uses `if: always()` | Checkout, temporary submission and reports are removed after upload or failure |

If the runner is offline, the Ollama job stays queued. The formal workflow
(`lint-and-unit`, `formal-gate`) continues independently.

## Registration (insert GitHub one-time commands here)

1. In GitHub: **Settings → Actions → Runners → New self-hosted runner → Windows**.
2. Paste the **one-time** configure commands GitHub shows into an elevated PowerShell
   on the GPU machine. **Do not commit the token, service credentials, generated
   runner name or computer name** to the repository or this document.
3. Use the live download, configure and service-install commands from GitHub UI.
   Keep that transcript outside the repository. Its shape is intentionally not
   reproduced here because it contains host-specific values and short-lived credentials.

```powershell
# Run only the commands shown by GitHub in the local administrative shell.
# Do not save the shell transcript under the GostCheck repository.
```

4. Create environment **`local-gpu`** (Settings → Environments) and enable required
   reviewers.
5. Set repository variable **`LLM_BACKEND=ollama`** when you want dispatch to select
   the GPU job (or pass `backend=ollama` in the workflow_dispatch UI).

## Local dry-run

```powershell
powershell -ExecutionPolicy Bypass -File scripts/semantic_ci.ps1 -Provider disabled
powershell -ExecutionPolicy Bypass -File scripts/semantic_ci.ps1 -Provider ollama
```

`disabled` writes `build/semantic/status.json` without network. Ollama requires a
running daemon and model (see [gpu-runbook.md](gpu-runbook.md)).

After artifact upload, the self-hosted job changes to `${{ runner.temp }}`, rejects a
drive-root path, verifies that the final `GITHUB_WORKSPACE` directory name matches
`GITHUB_REPOSITORY`, and removes the workspace contents. The cleanup step is guarded by
`if: always()`, so it also runs after test or upload failures.
