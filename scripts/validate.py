import json
import sys
from pathlib import Path
from typing import Literal, cast

import yaml
from jsonschema import Draft202012Validator

# Add root to import path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from libs.config import Config

# Orient
here = Path(__file__).resolve().parents[1]

# Parse argument
n_args = 1
if len(sys.argv) < 1 + n_args:
    msg = "Please supply either `plans` or `scenarios`"
    raise ValueError(msg)
mode = sys.argv[1]
if mode not in ["plans", "scenarios"]:
    msg = f"Invalid argument `{mode}`; please supply either `plans` or `scenarios`"
    raise ValueError(msg)
mode = cast("Literal['plans', 'scenarios']", mode)

# Open validator
with (
    here / "schemas" / ("plan.json" if mode == "plans" else "scenario.json")
).open() as f:
    schema = json.load(f)
validator = Draft202012Validator(schema)

# Collect files
dir_working = here / ("plans" if mode == "plans" else "scenarios")
files = sorted(
    [y for x in [dir_working.glob("*.yml"), dir_working.glob("*.yaml")] for y in x],
    key=lambda x: x.name,
)
sys.stderr.write(
    f"Found {len(files)} {'plan' if mode == 'plans' else 'scenario'} files\n",
)

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

    # Prepare for post-schema checks
    config = Config.from_file(path)

    # Switch on mode
    match mode:
        case "plans":
            tactic_correct = data["tactic"] == config.tactic
            level_correct = data["level"] == config.level
            if not (tactic_correct and level_correct):
                errors += 1
                sys.stderr.write(f"VALUE ERR {path}:\n")
                if not tactic_correct:
                    sys.stderr.write(
                        f"   - Value of `tactic` should be `{config.tactic}`\n",
                    )
                if not level_correct:
                    sys.stderr.write(
                        f"   - Value of `level` should be `{config.level}`\n",
                    )
        case "scenarios":
            raise NotImplementedError  # TODO: Handle

# Show summary
sys.stderr.write(f"\nFiles with errors: {errors}\n")

# Exit
sys.exit(1 if errors else 0)
