#!/usr/bin/env bash
# Reproducible demo wrapper (dry-run by default; no gh/git mutations).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="dry-run"
OUT="build/demo"
SOFTWARE_PDF=""
RESEARCH_PDF=""
CONFIRM=0

usage() {
  cat <<'EOF'
Usage: demo/run_demo.sh [--mode dry-run|local|execute-github|baseline]
                        [--out DIR] [--software-pdf PATH] [--research-pdf PATH]
                        [--i-understand-github-mutations]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode|-Mode) MODE="${2:-}"; shift 2 ;;
    --out|-Out) OUT="${2:-}"; shift 2 ;;
    --software-pdf) SOFTWARE_PDF="${2:-}"; shift 2 ;;
    --research-pdf) RESEARCH_PDF="${2:-}"; shift 2 ;;
    --i-understand-github-mutations) CONFIRM=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

PYTHON="python"
if [[ -x .venv312/bin/python ]]; then
  PYTHON=".venv312/bin/python"
elif [[ -x .venv312/Scripts/python.exe ]]; then
  PYTHON=".venv312/Scripts/python.exe"
fi

ARGS=(demo/run_demo.py --mode "$MODE" --out "$OUT")
[[ -n "$SOFTWARE_PDF" ]] && ARGS+=(--software-pdf "$SOFTWARE_PDF")
[[ -n "$RESEARCH_PDF" ]] && ARGS+=(--research-pdf "$RESEARCH_PDF")
[[ "$CONFIRM" -eq 1 ]] && ARGS+=(--i-understand-github-mutations)

"$PYTHON" "${ARGS[@]}"
