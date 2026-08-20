import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

# Add root to import path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from libs.config import Config

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
        with Path(path).open() as f:
            data = yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"YAML ERROR  {path}: {e}\n")
        errors += 1
        continue

    # Validate schema conformance
    errs = sorted(validator.iter_errors(data), key=lambda e: e.path)  # pyright: ignore[reportUnknownMemberType]
    if errs:
        errors += 1
        sys.stderr.write(f"SCHEMA ERR {path}:\n")
        for e in errs:
            loc = "/".join(str(p) for p in e.path) or "<root>"
            sys.stderr.write(f"   - {loc}: {e.message}\n")

    # Break on schema non-conformance (so we can assume correct deserialization from here)
    if errs:
        continue

    # Perform post-schema checks
    config = Config.from_file(path)
    tactic_correct = data["tactic"] == config.tactic
    level_correct = data["level"] == config.level
    if not (tactic_correct and level_correct):
        errors += 1
        sys.stderr.write(f"VALUE ERR {path}:\n")
        if not tactic_correct:
            sys.stderr.write(f"   - Value of `tactic` should be `{config.tactic}`\n")
        if not level_correct:
            sys.stderr.write(f"   - Value of `level` should be `{config.level}`\n")

# Show summary
sys.stderr.write(f"\nFiles with errors: {errors}\n")

# Exit
sys.exit(1 if errors else 0)
