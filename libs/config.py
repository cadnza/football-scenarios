import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

# Orient
_here = Path(__file__).resolve().parents[1]

# Load schema
with (_here / "schemas" / "plan.json").open() as f_schema:
    _schema = json.load(f_schema)

    # Read tactics
    tactics = cast("list[str]", _schema["properties"]["tactic"]["enum"])

    # Read levels
    levels = cast("list[str]", _schema["properties"]["level"]["enum"])


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
        """The basename of each file represented by this config."""
        return f"{self.title}.yaml"

    @property
    def filepaths(self) -> tuple[Path, Path]:
        """The paths of the files represented by this config."""
        dir_plans = _here / "plans"
        dir_plans.mkdir(parents=True, exist_ok=True)
        dir_scenarios = _here / "scenarios"
        dir_scenarios.mkdir(parents=True, exist_ok=True)
        return (dir_plans / self.filename, dir_scenarios / self.filename)

    def write_stubs(self) -> None:
        """Write this file's stubs (plan and scenario)."""
        path_plans = self.filepaths[0]
        path_scenarios = self.filepaths[1]
        with path_plans.open("w", encoding="utf-8") as f:
            f.writelines([f"tactic: {self.tactic}\n", f"level: {self.level}\n"])
        with path_scenarios.open("w", encoding="utf-8") as f:
            f.writelines(
                [
                    "metadata:\n",
                    f"  tactic: {self.tactic}\n",
                    f"  difficulty: {self.level}\n",
                ],
            )

    @classmethod
    def validate_filename(cls, f: Path) -> bool:
        """Validate whether a file has a name that refers to a config."""
        return bool(
            re.fullmatch(
                rf"^\d+-({'|'.join(tactics)})-({'|'.join(levels)})-\d+\.ya?ml$",
                f.name,
            ),
        )

    @classmethod
    def from_file(cls, f: Path) -> "Config":
        """Create a new instance from a file."""
        x = f.name.split(".")[0].split("-")
        return Config(
            idx=int(x[0]),
            tactic=x[1],
            level=x[2],
            sequence_number=int(x[3]),
        )
