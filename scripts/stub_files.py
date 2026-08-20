# Read in schema
import sys
from pathlib import Path

# Add root to import path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from libs.config import Config, levels, tactics

# Calculate starting point
files = sorted(
    [
        y
        for x in [
            Path("plans").glob("*.yml"),
            Path("plans").glob("*.yaml"),
        ]
        for y in x
        if Config.validate_filename(y)
    ],
    key=lambda x: x.name,
)

# Retrieve last file as config
lf = (
    max(
        [Config.from_file(f) for f in files],
        key=lambda x: x.idx,
    ).increment()
    if files
    else Config(
        idx=1,
        tactic=tactics[0],
        level=levels[0],
        sequence_number=1,
    )
)

# Read number of files
n_args = 1
if len(sys.argv) < 1 + n_args:
    msg = "Please supply a number of files to generate"
    raise ValueError(msg)
n_files = int(sys.argv[1])

# Generate files
for _ in range(n_files):
    lf.write_stubs()
    lf = lf.increment()
