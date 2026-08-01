#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Prefer project venv
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -e '.[dev]' -q
  PY="$ROOT/.venv/bin/python"
fi

# Common Buzz CLI locations
export PATH="$HOME/.local/bin:/Applications/Buzz.app/Contents/MacOS:$PATH"

echo "=== THINK: full adversarial verify ==="
for pack in ship-squad community-squad; do
  echo "--- pack: $pack ---"
  "$PY" -m hivepack verify "$pack"
done
