# Cloud fallback (Yandex advisory)

Yandex AI Studio is an **opt-in advisory** backend. Formal merge decisions never depend
on cloud availability, latency, or API errors.

Related workflow: [`.github/workflows/semantic-advisory.yml`](../.github/workflows/semantic-advisory.yml).
Provider contract: [llm-providers.md](llm-providers.md).

## When to use

| Backend | Runner | Environment | Secret |
|---------|--------|-------------|--------|
| `ollama` | self-hosted GPU | `local-gpu` | none (local) |
| `yandex` | `ubuntu-latest` | `semantic-cloud` | `YANDEX_AI_API_KEY` |
| `disabled` | `ubuntu-latest` | — | — |

Select via repository variable **`LLM_BACKEND`** (`ollama` \| `yandex` \| `disabled`)
or the `backend` input on `workflow_dispatch`.

## Yandex job guards

- Environment **`semantic-cloud`** with manual approval.
- Secret **`YANDEX_AI_API_KEY`** mapped to `LLM_API_KEY` only on `semantic-yandex`.
- Optional repo variable **`YANDEX_MODEL`** (`gpt://<folder>/<model>/...`).
- Real document text requires `allow_cloud_data=true` on dispatch **and**
  `ALLOW_CLOUD_DATA=true` in the job env. Without that flag the script publishes
  `status=cloud_blocked` and exits successfully (no network).
- If opt-in is true but neither `YANDEX_AI_API_KEY` nor `LLM_API_KEY` is present,
  the wrapper publishes `status=cloud_credentials_missing` without starting the
  normocontrol subprocess.
- Checkout is always trusted **`main`** tip (same as the GPU job).

## Local / CI script

```bash
bash scripts/semantic_ci.sh --provider disabled --out build/semantic
bash scripts/semantic_ci.sh --provider yandex --out build/semantic   # blocked without --allow-cloud-data
bash scripts/semantic_ci.sh --provider yandex --out build/semantic --allow-cloud-data
```

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/semantic_ci.ps1 -Provider disabled
powershell -ExecutionPolicy Bypass -File scripts/semantic_ci.ps1 -Provider yandex -AllowCloudData
```

Underlying process exits (including tool errors) are normalized to a green advisory
job with an explicit `status` in `build/semantic/status.json`. `blocks_merge` is
always `false`. Uploaded report artifacts use seven-day retention.

## Branch protection

Do **not** add any `semantic-*` or `publish-semantic` job as a required status check.
Required checks remain only `lint-and-unit` and `formal-gate` from the formal workflow.
