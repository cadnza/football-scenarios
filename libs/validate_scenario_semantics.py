import sys
from pathlib import Path
from typing import Optional, cast

from libs.scenario_g import (
    BallState,
    CheckToBallAction,
    CrossAction,
    DribbleAction,
    DropAction,
    FootballTacticalScenario,
    MarkAction,
    MoveAction,
    OverlapAction,
    PassAction,
    Player,
    PressAction,
    Role,
    RunAction,
    ShiftAction,
    ShotAction,
    TeamType,
    ThirdManRunAction,
    TrackRunnerAction,
    TurnoverAction,
    UnderlapAction,
    Zone,
    ZonePosition,
)

# Add root to import path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import math

# === Realism configuration (normalized units per second over a 1x1 pitch) ===
_MAX_SPEED_NORM = 0.25  # threshold for individual movement realism (tune to taste)
_MAX_SHIFT_SPEED_NORM = 0.20  # threshold for rigid defensive block SHIFT realism


def validate_scenario_semantics(data: "FootballTacticalScenario", path: Path, /) -> int:  # noqa: C901, PLR0912, PLR0915
    """Semantically validate a scenario."""
    errors = 0

    def err(msg: str) -> None:
        nonlocal errors
        errors += 1
        sys.stderr.write(f"VALUE ERR {path}:\n")
        sys.stderr.write(f"   - {msg}\n")

    # --- Build team/player indices ---
    atk_ids: set[str] = {p.id for p in data.attacking_team.players}  # pyright: ignore[reportUnknownMemberType]
    def_ids: set[str] = {p.id for p in data.defending_team.players}  # pyright: ignore[reportUnknownMemberType]
    all_ids: set[str] = atk_ids | def_ids

    # Global uniqueness across teams
    if len(atk_ids) + len(def_ids) != len(all_ids):
        err("Player IDs must be globally unique across attacking and defending teams")

    # GK presence advisory (keep or remove based on policy)
    atk_has_gk = any(p.role == Role.GK for p in data.attacking_team.players)
    def_has_gk = any(p.role == Role.GK for p in data.defending_team.players)
    if not atk_has_gk:
        err(
            "Attacking team has no GK; ensure this is intentional for a training scenario",
        )
    if not def_has_gk:
        err(
            "Defending team has no GK; ensure this is intentional for a training scenario",
        )

    # --- Canonical geometry per schema (normalized pitch) ---
    # Depth bands: DEF=[0,1/3], MID=[1/3,2/3], ATT=[2/3,1]
    BAND_Y = {0: (0.0, 1.0 / 3.0), 1: (1.0 / 3.0, 2.0 / 3.0), 2: (2.0 / 3.0, 1.0)}  # noqa: N806

    # Lateral lanes: 11 equal width lanes across x=[0,1]
    def lane_bounds(ix: int) -> tuple[float, float]:
        w = 1.0 / 11.0
        return (ix * w, (ix + 1) * w)

    center_lane = 5
    lane_index: dict[Zone, int] = {
        # Outermost
        Zone.DEF_LEFT_CORNER: 0,
        Zone.MID_LEFT_TOUCHLINE: 0,
        Zone.ATT_LEFT_CORNER: 0,
        Zone.DEF_RIGHT_CORNER: 10,
        Zone.MID_RIGHT_TOUCHLINE: 10,
        Zone.ATT_RIGHT_CORNER: 10,
        # Wing / halfspace / channel / center lanes
        Zone.DEF_LEFT_WING: 1,
        Zone.MID_LEFT_WING: 1,
        Zone.ATT_LEFT_WING: 1,
        Zone.DEF_LEFT_HALFSPACE: 2,
        Zone.MID_LEFT_HALFSPACE: 2,
        Zone.ATT_LEFT_HALFSPACE: 2,
        Zone.DEF_LEFT_CHANNEL: 3,
        Zone.MID_LEFT_CHANNEL: 3,
        Zone.ATT_LEFT_CHANNEL: 3,
        Zone.DEF_CENTER_LEFT: 4,
        Zone.MID_CENTER_LEFT: 4,
        Zone.ATT_ZONE14_LEFT: 4,
        Zone.DEF_CENTER: 5,
        Zone.MID_CENTER: 5,
        Zone.ATT_ZONE14: 5,
        Zone.DEF_CENTER_RIGHT: 6,
        Zone.MID_CENTER_RIGHT: 6,
        Zone.ATT_ZONE14_RIGHT: 6,
        Zone.DEF_RIGHT_CHANNEL: 7,
        Zone.MID_RIGHT_CHANNEL: 7,
        Zone.ATT_RIGHT_CHANNEL: 7,
        Zone.DEF_RIGHT_HALFSPACE: 8,
        Zone.MID_RIGHT_HALFSPACE: 8,
        Zone.ATT_RIGHT_HALFSPACE: 8,
        Zone.DEF_RIGHT_WING: 9,
        Zone.MID_RIGHT_WING: 9,
        Zone.ATT_RIGHT_WING: 9,
        # Box overlay (approximate lanes)
        Zone.LEFT_BOX: 4,
        Zone.CENTER_BOX: 5,
        Zone.RIGHT_BOX: 6,
        Zone.SIX_YARD_BOX: 5,
        Zone.PENALTY_SPOT: 5,
    }
    band_index: dict[Zone, int] = {}
    for z in Zone:
        name = z.name
        if name.startswith("DEF_"):
            band_index[z] = 0
        elif name.startswith("MID_"):
            band_index[z] = 1
        elif name.startswith("ATT_") or z in {
            Zone.LEFT_BOX,
            Zone.CENTER_BOX,
            Zone.RIGHT_BOX,
            Zone.SIX_YARD_BOX,
            Zone.PENALTY_SPOT,
        }:
            band_index[z] = 2
        else:
            band_index[z] = 1

    # Box / penalty area geometry
    PA_X = (18.0 / 68.0, 50.0 / 68.0)  # noqa: N806
    PA_Y = (87.0 / 105.0, 1.0)  # noqa: N806
    SIX_X = (22.0 / 68.0, 46.0 / 68.0)  # noqa: N806
    SIX_Y = (99.0 / 105.0, 1.0)  # noqa: N806
    PENALTY_SPOT = (0.5, 94.0 / 105.0)  # noqa: N806

    pa_w = PA_X[1] - PA_X[0]
    third = pa_w / 3.0
    BOX_X = {  # noqa: N806
        Zone.LEFT_BOX: (PA_X[0], PA_X[0] + third),
        Zone.CENTER_BOX: (PA_X[0] + third, PA_X[0] + 2 * third),
        Zone.RIGHT_BOX: (PA_X[0] + 2 * third, PA_X[1]),
    }
    BOX_Y = (PA_Y[0], PA_Y[1])  # noqa: N806

    def zone_rect(z: Zone) -> tuple[tuple[float, float], tuple[float, float]]:
        """Return ((x0,x1),(y0,y1)) bounds for zone z."""
        if z in (Zone.LEFT_BOX, Zone.CENTER_BOX, Zone.RIGHT_BOX):
            return (BOX_X[z], BOX_Y)
        if z == Zone.SIX_YARD_BOX:
            return (SIX_X, SIX_Y)
        if z == Zone.PENALTY_SPOT:
            return (
                (PENALTY_SPOT[0], PENALTY_SPOT[0]),
                (PENALTY_SPOT[1], PENALTY_SPOT[1]),
            )
        b = band_index[z]
        l = lane_index.get(z, center_lane)  # noqa: E741
        return (lane_bounds(l), BAND_Y[b])

    def apply_offsets(z: Zone, pos: Optional["ZonePosition"]) -> tuple[float, float]:
        """Return point in zone, using lane/depth offsets ∈ [-1,1] if provided."""
        (x0, x1), (y0, y1) = zone_rect(z)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if pos is None or z == Zone.PENALTY_SPOT:
            return (cx, cy)
        lane_offset = cast("int | None", pos.lane_offset)  # pyright: ignore[reportUnknownMemberType]
        depth_offset = cast("int | None", pos.depth_offset)  # pyright: ignore[reportUnknownMemberType]
        lx = lane_offset if lane_offset is not None else 0.0
        ly = depth_offset if depth_offset is not None else 0.0
        x = cx + lx * (x1 - x0) / 2.0
        y = cy + ly * (y1 - y0) / 2.0
        return (x, y)

    # Lateral & forward helpers (attacking team's perspective)
    def is_outside_relative(to_z: Zone, ref_z: Zone) -> bool:
        to_l, ref_l = (
            lane_index.get(to_z, center_lane),
            lane_index.get(ref_z, center_lane),
        )
        if ref_l < center_lane:
            return to_l < ref_l
        if ref_l > center_lane:
            return to_l > ref_l
        return to_l != center_lane

    def is_inside_relative(to_z: Zone, ref_z: Zone) -> bool:
        to_l, ref_l = (
            lane_index.get(to_z, center_lane),
            lane_index.get(ref_z, center_lane),
        )
        return abs(to_l - center_lane) < abs(ref_l - center_lane)

    def is_forward_progress(to_z: Zone, from_z: Zone) -> bool:
        return band_index.get(to_z, 2) >= band_index.get(from_z, 2)

    # --- Persistent player & ball state ---
    player_zone: dict[str, Zone] = {}
    player_pos: dict[str, tuple[float, float]] = {}

    def seed_player(p: "Player") -> None:
        player_zone[p.id] = p.starting_zone  # pyright: ignore[reportUnknownMemberType]
        player_pos[p.id] = apply_offsets(p.starting_zone, p.starting_position)  # pyright: ignore[reportUnknownMemberType]

    for p in data.attacking_team.players:
        seed_player(p)
    for p in data.defending_team.players:
        seed_player(p)

    ball_owner: str | None = data.initial_state.ball_owner
    ball_zone: Zone = data.initial_state.ball_zone
    ball_state: BallState = data.initial_state.ball_state

    # Ball owner invariants
    if ball_state == BallState.CONTROLLED:
        if ball_owner is None:
            err("Ball owner must be present when ball_state is CONTROLLED")
        elif ball_owner not in all_ids:
            err("Ball owner must be a known player ID on either team")
        elif player_zone.get(ball_owner) != ball_zone:
            err(
                "Initial ball_zone must equal ball owner's current zone when ball_state is CONTROLLED",
            )
    elif ball_owner is not None:
        err("Ball owner must be null when ball_state is LOOSE")

    # --- Phases & timeline ---
    phase_ids: set[str] = {ph.id for ph in data.plan.phases}  # pyright: ignore[reportUnknownMemberType]
    for i, ev in enumerate(data.events):
        if ev.sequence != (i + 1):  # pyright: ignore[reportUnknownMemberType]
            err(f"Event[{i}] sequence must equal {i + 1}")
        if ev.phase_id not in phase_ids:
            err(
                f"Event[{i}] phase_id='{ev.phase_id}' must reference an existing plan.phases.id",
            )

    # --- Concurrency checks ---
    active_intervals: dict[str, list[tuple[float, float, str]]] = {
        pid: [] for pid in all_ids
    }
    shift_intervals: list[tuple[float, float]] = []

    def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
        # half-open [start, end)
        return (a[0] < b[1]) and (b[0] < a[1])

    def reg(pid: str, action_type: str, start: float, end: float) -> None:
        rng = (start, end)
        for other in active_intervals.get(pid, []):
            if overlaps(rng, (other[0], other[1])) and other[2] in (
                "MOVE",
                "RUN",
                "DRIBBLE",
                "DROP",
                "OVERLAP",
                "UNDERLAP",
                "CHECK_TO_BALL",
                "TRACK_RUNNER",
                "MARK",
                "PRESS",
            ):
                err(
                    f"Event overlap: {action_type} overlaps with {other[2]} for player '{pid}'",
                )
                break
        active_intervals[pid].append((start, end, action_type))

    # --- Realism helper: speed check ---
    def speed_check(  # noqa: PLR0913
        *,
        pid: str,
        start_pt: tuple[float, float],
        end_pt: tuple[float, float],
        duration: float,
        label: str,
        idx: int,
    ) -> None:
        if duration <= 0:
            return
        dx = end_pt[0] - start_pt[0]
        dy = end_pt[1] - start_pt[1]
        dist = math.hypot(dx, dy)  # normalized units over 1x1 pitch
        speed = dist / duration
        if speed > _MAX_SPEED_NORM:
            err(
                f"Event[{idx}] {label}: unrealistic speed {speed:.3f} > {_MAX_SPEED_NORM:.3f} for player '{pid}'",
            )

    def check_player(pid: str, label: str, i: int) -> None:
        if pid not in all_ids:
            err(f"Event[{i}] references unknown player '{pid}' in {label}")

    # --- Event loop ---
    for i, ev in enumerate(data.events):
        start = cast("int", ev.start_time)  # pyright: ignore[reportUnknownMemberType]
        end = start + ev.duration
        act = ev.action.root

        match act:
            # Action handlers (semantic + realism)
            case PassAction():
                check_player(act.from_player, "PASS.from_player", i)
                check_player(act.to_player, "PASS.to_player", i)
                if ball_state != BallState.CONTROLLED or ball_owner != act.from_player:
                    err(
                        f"Event[{i}] PASS requires controlled ball by from_player '{act.from_player}' at start",
                    )
                if player_zone.get(act.from_player) != act.from_zone:
                    err(
                        f"Event[{i}] PASS.from_zone must equal passer '{act.from_player}' current zone at start",
                    )
                # PASS does not move players
                ball_owner = act.to_player
                ball_zone = act.to_zone
                ball_state = BallState.CONTROLLED

            case DribbleAction():
                check_player(act.player, "DRIBBLE.player", i)
                if ball_state != BallState.CONTROLLED or ball_owner != act.player:
                    err(
                        f"Event[{i}] DRIBBLE requires controlled ball by '{act.player}' at start",
                    )
                if player_zone.get(act.player) != act.from_zone:
                    err(
                        f"Event[{i}] DRIBBLE.from_zone must equal player's current zone at start",
                    )
                start_pt = player_pos[act.player]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.player,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="DRIBBLE",
                    idx=i,
                )
                reg(act.player, "DRIBBLE", start, end)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt
                ball_owner = act.player
                ball_zone = act.to_zone
                ball_state = BallState.CONTROLLED

            case MoveAction():
                check_player(act.player, "MOVE.player", i)
                if player_zone.get(act.player) != act.from_zone:
                    err(
                        f"Event[{i}] MOVE.from_zone must equal player's current zone at start",
                    )
                start_pt = player_pos[act.player]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.player,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="MOVE",
                    idx=i,
                )
                reg(act.player, "MOVE", start, end)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case RunAction():
                check_player(act.player, "RUN.player", i)
                if player_zone.get(act.player) != act.from_zone:
                    err(
                        f"Event[{i}] RUN.from_zone must equal player's current zone at start",
                    )
                start_pt = player_pos[act.player]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.player,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="RUN",
                    idx=i,
                )
                reg(act.player, "RUN", start, end)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case OverlapAction():
                check_player(act.runner, "OVERLAP.runner", i)
                check_player(act.outside_player, "OVERLAP.outside_player", i)
                ref_zone = player_zone.get(act.outside_player)
                if ref_zone is None:
                    err(
                        f"Event[{i}] OVERLAP requires outside_player '{act.outside_player}' to have a known zone",
                    )
                else:
                    if not is_outside_relative(act.to_zone, ref_zone):
                        err(
                            f"Event[{i}] OVERLAP.to_zone must be laterally outside relative to outside_player's lane",
                        )
                    runner_from = player_zone.get(act.runner)
                    if runner_from and not is_forward_progress(
                        act.to_zone,
                        runner_from,
                    ):
                        err(
                            f"Event[{i}] OVERLAP.to_zone should represent forward progression",
                        )
                start_pt = player_pos[act.runner]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.runner,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="OVERLAP",
                    idx=i,
                )
                reg(act.runner, "OVERLAP", start, end)
                player_zone[act.runner] = act.to_zone
                player_pos[act.runner] = end_pt

            case UnderlapAction():
                check_player(act.runner, "UNDERLAP.runner", i)
                check_player(act.outside_player, "UNDERLAP.outside_player", i)
                ref_zone = player_zone.get(act.outside_player)
                if ref_zone is None:
                    err(
                        f"Event[{i}] UNDERLAP requires outside_player '{act.outside_player}' to have a known zone",
                    )
                else:
                    if not is_inside_relative(act.to_zone, ref_zone):
                        err(
                            f"Event[{i}] UNDERLAP.to_zone must be laterally inside relative to outside_player's lane",
                        )
                    runner_from = player_zone.get(act.runner)
                    if runner_from and not is_forward_progress(
                        act.to_zone,
                        runner_from,
                    ):
                        err(
                            f"Event[{i}] UNDERLAP.to_zone should represent forward progression",
                        )
                start_pt = player_pos[act.runner]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.runner,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="UNDERLAP",
                    idx=i,
                )
                reg(act.runner, "UNDERLAP", start, end)
                player_zone[act.runner] = act.to_zone
                player_pos[act.runner] = end_pt

            case CheckToBallAction():
                check_player(act.player, "CHECK_TO_BALL.player", i)
                if act.to_zone != ball_zone:
                    err(
                        f"Event[{i}] CHECK_TO_BALL.to_zone must equal the ball's zone at event start",
                    )
                start_pt = player_pos[act.player]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.player,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="CHECK_TO_BALL",
                    idx=i,
                )
                reg(act.player, "CHECK_TO_BALL", start, end)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case ThirdManRunAction():
                check_player(act.runner, "THIRD_MAN_RUN.runner", i)
                start_pt = player_pos[act.runner]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.runner,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="THIRD_MAN_RUN",
                    idx=i,
                )
                reg(act.runner, "THIRD_MAN_RUN", start, end)
                player_zone[act.runner] = act.to_zone
                player_pos[act.runner] = end_pt

            case CrossAction():
                check_player(act.from_player, "CROSS.from_player", i)
                if ball_state != BallState.CONTROLLED or ball_owner != act.from_player:
                    err(
                        f"Event[{i}] CROSS requires controlled ball by from_player '{act.from_player}' at start",
                    )
                if act.result.name == "RECEIVED":
                    if act.target_player is None:
                        err(f"Event[{i}] CROSS.result=RECEIVED requires target_player")
                    else:
                        check_player(act.target_player, "CROSS.target_player", i)
                # Ball state update
                if act.result.name == "RECEIVED":
                    ball_owner = act.target_player
                    ball_zone = act.target_zone
                    ball_state = BallState.CONTROLLED
                elif act.result.name in ("DEFENDED", "LOOSE"):
                    ball_owner = None
                    ball_zone = act.target_zone
                    ball_state = BallState.LOOSE
                elif act.result.name == "OUT_OF_PLAY":
                    if i != len(data.events) - 1:
                        err(
                            f"Event[{i}] CROSS.result=OUT_OF_PLAY must be the final event",
                        )

            case ShotAction():
                check_player(act.player, "SHOT.player", i)
                if ball_state != BallState.CONTROLLED or ball_owner != act.player:
                    err(
                        f"Event[{i}] SHOT requires controlled ball by shooter '{act.player}' at start",
                    )
                if player_zone.get(act.player) != act.shot_zone:
                    err(
                        f"Event[{i}] SHOT.shot_zone must equal shooter's current zone at start",
                    )
                if act.result.name in ("GOAL", "OUT_OF_PLAY"):
                    if i != len(data.events) - 1:
                        err(
                            f"Event[{i}] SHOT.result={act.result.name} must be the final event",
                        )
                else:
                    ball_owner = None
                    ball_state = BallState.LOOSE
                    ball_zone = act.shot_zone

            case PressAction():
                check_player(act.player, "PRESS.player", i)
                check_player(act.target_player, "PRESS.target_player", i)
                if act.player in atk_ids:
                    err(
                        f"Event[{i}] PRESS presser '{act.player}' should belong to defending_team",
                    )
                if act.target_player in def_ids:
                    err(
                        f"Event[{i}] PRESS target '{act.target_player}' should belong to attacking_team",
                    )
                # Approximate presser endpoint: along line to target, stopping 'pressing_distance' short
                start_pt = player_pos[act.player]
                target_pt = player_pos[act.target_player]
                vx, vy = target_pt[0] - start_pt[0], target_pt[1] - start_pt[1]
                d = math.hypot(vx, vy)
                stop_d = max(0.0, d - act.pressing_distance)
                if d > 1e-6:  # noqa: PLR2004
                    scale = stop_d / d
                    end_pt = (start_pt[0] + vx * scale, start_pt[1] + vy * scale)
                else:
                    end_pt = start_pt
                speed_check(
                    pid=act.player,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="PRESS",
                    idx=i,
                )
                reg(act.player, "PRESS", start, end)
                player_pos[act.player] = end_pt

            case MarkAction():
                check_player(act.defender, "MARK.defender", i)
                check_player(act.attacker, "MARK.attacker", i)
                if act.defender in atk_ids:
                    err(
                        f"Event[{i}] MARK defender '{act.defender}' should belong to defending_team",
                    )
                if act.attacker in def_ids:
                    err(
                        f"Event[{i}] MARK attacker '{act.attacker}' should belong to attacking_team",
                    )
                # Goal-side means toward defending team's own goal (y increasing, capped at 1.0)
                start_pt = player_pos[act.defender]
                att_pt = player_pos[act.attacker]
                end_pt = (att_pt[0], min(1.0, att_pt[1] + act.goal_side_distance))
                speed_check(
                    pid=act.defender,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="MARK",
                    idx=i,
                )
                reg(act.defender, "MARK", start, end)
                player_pos[act.defender] = end_pt

            case TrackRunnerAction():
                check_player(act.defender, "TRACK_RUNNER.defender", i)
                check_player(act.runner, "TRACK_RUNNER.runner", i)
                if act.defender in atk_ids:
                    err(
                        f"Event[{i}] TRACK_RUNNER defender '{act.defender}' should belong to defending_team",
                    )
                if act.runner in def_ids:
                    err(
                        f"Event[{i}] TRACK_RUNNER runner '{act.runner}' should belong to attacking_team",
                    )
                # Continuous behavior; register interval for concurrency checks
                reg(act.defender, "TRACK_RUNNER", start, end)

            case DropAction():
                check_player(act.player, "DROP.player", i)
                # DROP is "defensive retreat toward defending team's own goal"
                # Enforce that the player belongs to defending team, and movement goes deeper toward y=1.
                if act.player not in def_ids:
                    err(
                        f"Event[{i}] DROP player '{act.player}' should belong to defending_team",
                    )
                from_z = player_zone.get(act.player)
                if from_z and not is_forward_progress(act.to_zone, from_z):
                    err(
                        f"Event[{i}] DROP.to_zone must move toward defending team's own goal (attacking perspective: forward)",
                    )
                start_pt = player_pos[act.player]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.player,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="DROP",
                    idx=i,
                )
                reg(act.player, "DROP", start, end)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case ShiftAction():
                # Rigid movement of defending outfield block (GK excluded)
                shift_intervals.append((start, end))
                for s_rng in shift_intervals[:-1]:
                    if overlaps((start, end), s_rng):
                        err(
                            f"Event[{i}] SHIFT overlaps another SHIFT; defensive block translation should be singular",
                        )
                        break
                dist_norm = act.distance
                speed = dist_norm / ev.duration if ev.duration > 0 else 0.0
                if speed > _MAX_SHIFT_SPEED_NORM:
                    err(
                        f"Event[{i}] SHIFT unrealistic speed {speed:.3f} > {_MAX_SHIFT_SPEED_NORM:.3f}",
                    )
                # Deformation: overlapping individual movements for defenders during SHIFT
                for pid, intervals in active_intervals.items():
                    if pid in def_ids:
                        for rng in intervals:
                            if overlaps((start, end), (rng[0], rng[1])) and rng[2] in (
                                "MOVE",
                                "RUN",
                                "DRIBBLE",
                                "DROP",
                            ):
                                err(
                                    f"Event[{i}] SHIFT overlaps {rng[2]} for defender '{pid}', breaking rigid block semantics",
                                )
                                break
                # Apply translation to defenders except GK
                dx, dy = 0.0, 0.0
                if act.direction.name == "LEFT":
                    dx = -dist_norm
                elif act.direction.name == "RIGHT":
                    dx = dist_norm
                elif act.direction.name == "FORWARD":
                    dy = dist_norm
                elif act.direction.name == "BACKWARD":
                    dy = -dist_norm
                for p in data.defending_team.players:
                    if p.role == Role.GK:
                        continue  # GK excluded
                    x, y = player_pos[p.id]  # pyright: ignore[reportUnknownMemberType]
                    x_new = min(1.0, max(0.0, x + dx))
                    y_new = min(1.0, max(0.0, y + dy))
                    player_pos[p.id] = (x_new, y_new)  # pyright: ignore[reportUnknownMemberType]
                # Register a synthetic interval for each defender (optional, for overlap visibility)
                for p in data.defending_team.players:
                    if p.role != Role.GK:
                        reg(p.id, "SHIFT", start, end)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]

            case TurnoverAction():
                if act.winner is not None:
                    check_player(act.winner, "TURNOVER.winner", i)
                    if (
                        act.winning_team == TeamType.ATTACK
                        and act.winner not in atk_ids
                    ):
                        err(
                            f"Event[{i}] TURNOVER.winner must belong to attacking_team when winning_team=ATTACK",
                        )
                    if (
                        act.winning_team == TeamType.DEFEND
                        and act.winner not in def_ids
                    ):
                        err(
                            f"Event[{i}] TURNOVER.winner must belong to defending_team when winning_team=DEFEND",
                        )
                ball_zone = act.zone
                if act.winner is not None:
                    ball_owner = act.winner
                    ball_state = BallState.CONTROLLED
                else:
                    ball_owner = None
                    ball_state = BallState.LOOSE

        # Controlled ball invariant at event completion
        if (
            ball_state == BallState.CONTROLLED
            and ball_owner in player_zone
            and player_zone[ball_owner] != ball_zone
        ):
            err(
                f"Event[{i}] completion: ball_zone must equal ball owner's current zone when controlled",
            )

    # --- Expected outcomes terminality guard ---
    last_action = data.events[-1].action.root
    if (
        isinstance(last_action, ShotAction)
        and last_action.result.name
        in (
            "GOAL",
            "OUT_OF_PLAY",
        )
        and len(data.expected_outcomes) > 0
    ):
        err(
            "Expected outcomes present after a terminal SHOT result; scenario should end without further guaranteed states",
        )

    return errors
