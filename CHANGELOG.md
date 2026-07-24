# Changelog

## [0.1.0] — 2026-07-24

PoC NORMACTRL / GostCheck: formal gate + advisory LLM + GitHub CI.

### Added

- Orchestrator CLI `normocontrol run` (build → formal → semantic → aggregate).
- Stable `report.json` / `report.md` / `summary.json` with fingerprints and redaction.
- GitHub Actions formal-gate, artifacts, PR comment marker.
- Optional semantic-advisory workflow (Ollama self-hosted / Yandex / disabled).
- Reproducible demo pass/fail/fixed contracts and dry-run GitHub plan.
- Security/privacy/setup/troubleshooting/acceptance docs and `scripts/release_check.py`.

### Security

- LLM never blocks merge; secrets and student PDFs stay out of git.
- Self-hosted GPU jobs are dispatch-only on trusted `main`.

[0.1.0]: https://github.com/TopTatarin/GostCheck/releases/tag/v0.1.0
