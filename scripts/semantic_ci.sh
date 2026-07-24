#!/usr/bin/env bash
# Advisory semantic CI wrapper (Linux/macOS). Never blocks formal merge.
set -euo pipefail

PROVIDER=""
SOURCE="tests/fixtures/demo/pass"
OUT="build/semantic"
ALLOW_CLOUD=0

usage() {
  cat <<'EOF'
Usage: scripts/semantic_ci.sh [--provider ollama|yandex|disabled] [--source PATH] [--out DIR] [--allow-cloud-data]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider|-Provider)
      PROVIDER="${2:-}"
      shift 2
      ;;
    --source)
      SOURCE="${2:-}"
      shift 2
      ;;
    --out|-Out)
      OUT="${2:-}"
      shift 2
      ;;
    --allow-cloud-data)
      ALLOW_CLOUD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

ARGS=(scripts/semantic_ci.py --source "$SOURCE" --out "$OUT")
if [[ -n "$PROVIDER" ]]; then
  ARGS+=(--provider "$PROVIDER")
fi
if [[ "$ALLOW_CLOUD" -eq 1 ]]; then
  ARGS+=(--allow-cloud-data)
fi

python "${ARGS[@]}"
