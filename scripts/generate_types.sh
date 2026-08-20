#!/usr/bin/env bash

set -e

# Orient
here="$(realpath "$(dirname "$0")/..")"

# Create venv if needed
venv="$here/.venv"
[ -d "$venv" ] || {
    uv -C "$here" venv
    uv -C "$here" pip install -r "$here/requirements.txt"
}

# Generate types
"$venv/bin/datamodel-codegen" --input "$here/schemas/plan.json" --input-file-type jsonschema --output "$here/libs/plan_g.py"
"$venv/bin/datamodel-codegen" --input "$here/schemas/scenario.json" --input-file-type jsonschema --output "$here/libs/scenario_g.py"
