#!/usr/bin/env bash

set -e

# Orient
here="$(realpath "$(dirname "$0")")"

# Read first argument as number of files to generate
[ -z "$1" ] && {
    echo "Please provide a number of files to generate as \$1" >&2
    exit 1
}
n_files="$1"

# Create venv if needed
venv="$here/.venv"
[ -d "$venv" ] || {
    uv -C "$here" venv
    uv -C "$here" pip install -r "$here/requirements.txt"
}

# Stub plan files
mkdir -p "$here/plans"
"$venv/bin/python" "$here/scripts/stub_plans.py" "$n_files"

# Invoke LLM to fill in stubbed plans
codex \
    --oss \
    --local-provider ollama \
    -m qwen3.8:27b-mlx \
    exec \
    "$(cat "$here/prompts/write-plans.md")"
