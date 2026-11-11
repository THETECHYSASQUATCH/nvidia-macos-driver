#!/bin/bash
# Build-only entry point; output stays in the directory explicitly supplied by the caller.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/build_nvrm.py" "$@"
