import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

# Open validator
with Path("schemas/plan.json").open() as f:
    schema = json.load(f)
validator = Draft202012Validator(schema)

# Collect files
files = sorted(
    [y for x in [Path("plans").glob("*.yml"), Path("plans").glob("*.yaml")] for y in x],
    key=lambda x: x.name,
)
sys.stderr.write(f"Found {len(files)} plan files\n")

# Open error counter
errors = 0

# Loop through files
for path in files:
    # Validate YAML structure
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        sys.stderr.write(f"YAML ERROR  {path}: {e}\n")
        errors += 1
        continue

    # Validate schema conformance
    errs = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errs:
        errors += 1
        sys.stderr.write(f"SCHEMA ERR {path}:\n")
        for e in errs:
            loc = "/".join(str(p) for p in e.path) or "<root>"
            sys.stderr.write(f"   - {loc}: {e.message}\n")
    else:
        tactics = {d["tactic"] for d in [data]}
        sys.stderr.write(
            f"OK         {path}  [{data['tactic']}] phases={len(data['phases'])}\n",
        )

# Show summary
sys.stderr.write(f"\nFiles with errors: {errors}\n")

# Exit
sys.exit(1 if errors else 0)
