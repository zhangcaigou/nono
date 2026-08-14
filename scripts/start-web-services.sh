#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible alias. Python model-service lifecycle is managed separately.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${script_dir}/start-java-backend.sh" "$@"
