import glob
import json
import sys

import yaml
from jsonschema import Draft202012Validator

# Open validator
with open("schemas/plan.json") as f:
    schema = json.load(f)
validator = Draft202012Validator(schema)

# Collect files
files = sorted(glob.glob("plans/*.yml") + glob.glob("plans/*.yaml"))
print(f"Found {len(files)} plan files")

# Open error counter
errors = 0

# Loop through files
for path in files:
    # Validate YAML structure
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"YAML ERROR  {path}: {e}")
        errors += 1
        continue

    # Validate schema conformance
    errs = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errs:
        errors += 1
        print(f"SCHEMA ERR {path}:")
        for e in errs:
            loc = "/".join(str(p) for p in e.path) or "<root>"
            print(f"   - {loc}: {e.message}")
    else:
        tactics = {d["tactic"] for d in [data]}
        print(f"OK         {path}  [{data['tactic']}] phases={len(data['phases'])}")

# Show summary
print(f"\nFiles with errors: {errors}")

# Exit
sys.exit(1 if errors else 0)
