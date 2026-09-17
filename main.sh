#!/usr/bin/env bash

set -e

# Orient
here="$(realpath "$(dirname "$0")")"

# Make sure codex is installed
command -v codex >/dev/null || {
    echo "Please install codex" >&2
    exit 1
}

# Read first argument as number of files to generate
[ -z "${1+x}" ] && {
    echo "Please provide a number of files to generate as \$1" >&2
    exit 1
}
n_files="$1"

# Read loop argument (if set, run in loop)
if [ -n "${2+x}" ] && [ "$2" != loop ]; then
    echo "The only acceptable second argument is 'loop'" >&2
    exit 1
fi

# Create venv if needed
venv="$here/.venv"
[ -d "$venv" ] || {
    uv -C "$here" venv
    uv -C "$here" pip install -r "$here/requirements.txt"
}

# Set Ollama model
ollama_model=qwen3.8:27b-mlx

# Open loop
while true; do

    # Stub plan files
    "$venv/bin/python" "$here/scripts/stub_files.py" "$n_files"

    # Invoke LLM agent to fill in stubbed plans
    (
        cd "$here" && ollama launch codex \
            --model "$ollama_model" \
            -- \
            exec \
            --sandbox \
            workspace-write \
            "$(cat "$here/prompts/write-plans.md")"
    )

    # Invoke LLM agent to fill in stubbed scenarios
    (
        cd "$here" && ollama launch codex \
            --model "$ollama_model" \
            -- \
            exec \
            --sandbox \
            workspace-write \
            "$(cat "$here/prompts/write-scenarios.md")"
    )

    # Break if not looping
    [ -z "${2+x}" ] && break

done
