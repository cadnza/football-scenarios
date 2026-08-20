# Read in schema
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

# Orient
here = Path(__file__).parent.parent


@dataclass(frozen=True, kw_only=True)
class Config:
    """A plan/scenario configuration."""

    idx: int
    """This config's index."""

    tactic: str
    """This config's tactic."""

    level: str
    """This config's level."""

    sequence_number: int
    """This config's sequence number."""

    def increment(self) -> "Config":
        """Labels the next file."""
        # Increment everything by one rotation
        index = self.idx + 1
        if self.level == levels[-1]:
            level = levels[0]
            i_tactic_next = tactics.index(self.tactic) + 1
            tactic = (
                tactics[i_tactic_next] if i_tactic_next < len(tactics) else tactics[0]
            )
            sequence_number = (
                self.sequence_number + 1
                if tactic == tactics[0] and level == levels[0]
                else self.sequence_number
            )
        else:
            level = levels[levels.index(self.level) + 1]
            tactic = self.tactic
            sequence_number = self.sequence_number

        # Return
        return Config(
            idx=index,
            tactic=tactic,
            level=level,
            sequence_number=sequence_number,
        )

    @property
    def title(self) -> str:
        """This config's title."""  # noqa: D404
        return f"{self.idx}-{self.tactic}-{self.level}-{self.sequence_number}"

    @property
    def filename(self) -> str:
        """The basename of the file represented by this config."""
        return f"{self.title}.yaml"

    @property
    def filepath(self) -> Path:
        """The path of the file represented by this config."""
        dir_plans = here / "plans"
        dir_plans.mkdir(parents=True, exist_ok=True)
        return dir_plans / self.filename

    def write_stub(self) -> None:
        """Write this file's stub."""
        with self.filepath.open("w", encoding="utf-8") as f:
            f.writelines([f"tactic: {self.tactic}\n", f"level: {self.level}\n"])


# Load schema
with (here / "schemas" / "plan.json").open() as f_schema:
    schema = json.load(f_schema)

    # Read tactics
    tactics = cast("list[str]", schema["properties"]["tactic"]["enum"])

    # Read levels
    levels = cast("list[str]", schema["properties"]["level"]["enum"])

# Calculate starting point
files = sorted(
    [
        y
        for x in [
            Path("plans").glob("*.yml"),
            Path("plans").glob("*.yaml"),
        ]
        for y in x
        if re.fullmatch(
            rf"^\d+-({'|'.join(tactics)})-({'|'.join(levels)})-\d+\.ya?ml$",
            y.name,
        )
    ],
    key=lambda x: x.name,
)

# Retrieve last file as config
lf = (
    max(
        [
            Config(
                idx=int(z[0]),
                tactic=z[1],
                level=z[2],
                sequence_number=int(z[3]),
            )
            for z in [f.name.split(".")[0].split("-") for f in files]
        ],
        key=lambda x: x.idx,
    )
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
    lf.write_stub()
    lf = lf.increment()
