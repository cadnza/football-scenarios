#!/usr/bin/env bash

set -e

# Orient
here="$(realpath "$(dirname "$0")/..")"

# Validate
"$here/.venv/bin/python" "$here/scripts/validate.py" scenarios
