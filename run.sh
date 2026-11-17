#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -d .deps ]; then
  export PYTHONPATH=".deps:.${PYTHONPATH:+:$PYTHONPATH}"
fi
exec python3 "$@"
