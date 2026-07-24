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

If the runner is offline, the Ollama job stays queued. The formal workflow
(`lint-and-unit`, `formal-gate`) continues independently.

## Registration (insert GitHub one-time commands here)

1. In GitHub: **Settings → Actions → Runners → New self-hosted runner → Windows**.
2. Paste the **one-time** configure commands GitHub shows into an elevated PowerShell
   on the GPU machine. **Do not commit the token** to the repository or this document.
3. Example shape (replace with the live commands from GitHub UI):

```powershell
# --- paste GitHub-generated download / extract commands here ---
# --- paste GitHub-generated config command here (contains a one-time token) ---
.\config.cmd --url https://github.com/<OWNER>/<REPO> --token <ONE_TIME_TOKEN> `
  --labels "windows,x64,gpu,normocontrol" --name "normocontrol-gpu"
# --- paste GitHub-generated run service install commands here ---
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
