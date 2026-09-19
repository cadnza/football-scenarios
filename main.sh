#!/usr/bin/env bash

set -e

# SERVER: ./.venv/bin/mlx_lm.server

# Orient
here="$(realpath "$(dirname "$0")")"

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

# Make sure aider is installed
command -v aider >/dev/null || {
    echo "Please install aider" >&2
    exit 1
}

# Check server
curl -s --fail-with-body http://localhost:8080/v1/models >/dev/null || {
    echo "Failed to connect to OpenAI server" >&2
    exit 1
}

# Create venv if needed
venv="$here/.venv"
[ -d "$venv" ] || {
    uv -C "$here" venv
    uv -C "$here" pip install -r "$here/requirements.txt"
}

# Set model ID
model_id=mlx-community/Qwen3.8-27B-4bit

# Export environment variables
export OPENAI_API_BASE=http://127.0.0.1:8080/v1
export OPENAI_API_KEY=oranges

aider --no-gitignore --model "openai/$model_id" --yes-always --message-file

# Open loop
while true; do

    # Stub plan files
    "$venv/bin/python" "$here/scripts/stub_files.py" "$n_files"

    # Invoke LLM agent to fill in stubbed plans
    (
        cd "$here" && aider \
            --no-gitignore \
            --model "openai/$model_id" \
            --yes-always \
            --message-file "$here/prompts/write-plans.md"
    )

    # Invoke LLM agent to fill in stubbed scenarios
    (
        cd "$here" && aider \
            --no-gitignore \
            --model "openai/$model_id" \
            --yes-always \
            --message-file "$here/prompts/write-scenarios.md"
    )

    # Break if not looping
    [ -z "${2+x}" ] && break

done
