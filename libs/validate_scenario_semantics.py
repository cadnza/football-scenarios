import sys
from pathlib import Path
from typing import Any, Optional, TypedDict, cast

from libs.scenario_g import (
    BallState,
    CheckToBallAction,
    CrossAction,
    DribbleAction,
    DropAction,
    Event,
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
from collections import Counter

# === Realism configuration (normalized units per second over a 1x1 pitch) ===
_MAX_SPEED_NORM = 0.25  # threshold for individual movement realism (tune to taste)
_MAX_SHIFT_SPEED_NORM = 0.20  # threshold for rigid defensive block SHIFT realism


class _ErrCtx(TypedDict, total=False):
    """A context object for error messages."""

    event_index: int
    event_id: str
    phase_id: str
    action: str | Any
    start: float
    end: float
    duration: float


def validate_scenario_semantics(data: "FootballTacticalScenario", path: Path, /) -> int:  # noqa: C901, PLR0912, PLR0915
    """Semantically validate a scenario with context-rich, actionable error messages."""
    errors = 0

    def err(msg: str, *, ctx: _ErrCtx | None = None) -> None:
        """Emit a structured error message with optional event context."""
        nonlocal errors
        errors += 1
        title = getattr(getattr(data, "metadata", None), "title", "UNKNOWN")
        sys.stderr.write(f"VALUE ERR {path} (Scenario='{title}'):\n")
        if ctx is not None:
            # Expected keys in ctx: event_index, event_id, phase_id, action, start, end, duration
            ei = ctx.get("event_index", "?")
            eid = ctx.get("event_id", "?")
            ph = ctx.get("phase_id", "?")
            act = ctx.get("action", "?")
            st = ctx.get("start", "?")
            en = ctx.get("end", "?")
            du = ctx.get("duration", "?")
            sys.stderr.write(
                f"   [Event #{ei} id='{eid}' phase='{ph}' action='{act}' t={st}–{en} dur={du}s]\n",
            )
        sys.stderr.write(f"   - {msg}\n")

    def fmt_zone(z: Optional["Zone"]) -> str:
        return z.name if isinstance(z, Zone) else str(z)

    # --- Build team/player indices ---
    atk_ids_list: list[str] = [p.id for p in data.attacking_team.players]  # pyright: ignore[reportUnknownMemberType]
    def_ids_list: list[str] = [p.id for p in data.defending_team.players]  # pyright: ignore[reportUnknownMemberType]
    atk_ids: set[str] = set(atk_ids_list)
    def_ids: set[str] = set(def_ids_list)
    all_ids: set[str] = atk_ids | def_ids

    # Per-team duplicate checks
    atk_dups = [pid for pid, c in Counter(atk_ids_list).items() if c > 1]
    def_dups = [pid for pid, c in Counter(def_ids_list).items() if c > 1]
    if atk_dups:
        err(
            "Attacking team has duplicate player IDs: "
            + ", ".join(sorted(atk_dups))
            + ". Suggested fix: ensure each Player.id in attacking_team.players is unique (e.g., append role or shirt number).",
        )
    if def_dups:
        err(
            "Defending team has duplicate player IDs: "
            + ", ".join(sorted(def_dups))
            + ". Suggested fix: ensure each Player.id in defending_team.players is unique (e.g., append role or shirt number).",
        )

    # Cross-team global uniqueness
    cross_dups = atk_ids & def_ids
    if cross_dups:
        err(
            "Player IDs must be globally unique across both teams; duplicates found across teams: "
            + ", ".join(sorted(cross_dups))
            + ". Suggested fix: rename one side's duplicate IDs.",
        )

    # GK presence advisory (keep or remove based on policy)
    atk_has_gk = any(p.role == Role.GK for p in data.attacking_team.players)
    def_has_gk = any(p.role == Role.GK for p in data.defending_team.players)
    if not atk_has_gk:
        err(
            f"Attacking team has no GK; ensure this is intentional for a training scenario (team='{data.attacking_team.name}'). "
            "Suggested fix: add a Player with role=GK to attacking_team.players, or acknowledge omission in docs.",
        )
    if not def_has_gk:
        err(
            f"Defending team has no GK; ensure this is intentional for a training scenario (team='{data.defending_team.name}'). "
            "Suggested fix: add a Player with role=GK to defending_team.players, or acknowledge omission in docs.",
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
        lane_offset = cast("float | None", pos.lane_offset)  # pyright: ignore[reportUnknownMemberType]
        depth_offset = cast("float | None", pos.depth_offset)  # pyright: ignore[reportUnknownMemberType]
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
            err(
                "Ball owner must be present when ball_state=CONTROLLED (found ball_owner=None). Suggested fix: set initial_state.ball_owner to the controlling player's ID.",
            )
        elif ball_owner not in all_ids:
            err(
                f"Ball owner must be a known player ID on either team (found '{ball_owner}'). Known IDs={sorted(all_ids)}. "
                "Suggested fix: change initial_state.ball_owner to a valid Player.id.",
            )
        elif player_zone.get(ball_owner) != ball_zone:
            err(
                "Initial ball_zone must equal ball owner's current zone when ball_state=CONTROLLED "
                f"(owner='{ball_owner}', owner_zone='{fmt_zone(player_zone.get(ball_owner))}', ball_zone='{ball_zone.name}'). "
                "Suggested fix: set initial_state.ball_zone to the owner's current zone, or adjust the owner's starting_zone.",
            )
    elif ball_owner is not None:
        err(
            f"Ball owner must be null when ball_state=LOOSE (found ball_owner='{ball_owner}'). "
            "Suggested fix: set initial_state.ball_owner=None or set ball_state=CONTROLLED.",
        )

    # --- Phases & timeline ---
    phase_ids: set[str] = {ph.id for ph in data.plan.phases}  # pyright: ignore[reportUnknownMemberType]
    for i, ev in enumerate(data.events):
        ev_start = float(ev.start_time)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        ev_end = ev_start + float(ev.duration)
        act = ev.action.root
        act_label = getattr(act, "action_type", type(act).__name__)
        ctx_base: _ErrCtx = {
            "event_index": i,
            "event_id": ev.event_id,
            "phase_id": ev.phase_id,
            "action": act_label,
            "start": ev_start,
            "end": ev_end,
            "duration": float(ev.duration),
        }
        if ev.sequence != (i + 1):  # pyright: ignore[reportUnknownMemberType]
            err(
                f"event.sequence must equal its 1-based array position (expected {i + 1}, found {ev.sequence}) for event_id='{ev.event_id}'. "  # pyright: ignore[reportUnknownMemberType]
                f"Suggested fix: set event.sequence={i + 1}.",
                ctx=ctx_base,
            )
        if ev.phase_id not in phase_ids:
            err(
                f"event.phase_id must reference an existing plan.phases.id (found '{ev.phase_id}'; known={sorted(phase_ids)}). "
                f"Suggested fix: change event.phase_id to one of {sorted(phase_ids)}.",
                ctx=ctx_base,
            )

    # --- Concurrency checks ---
    active_intervals: dict[str, list[tuple[float, float, str]]] = {
        pid: [] for pid in all_ids
    }
    shift_intervals: list[tuple[float, float]] = []

    def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
        # half-open [start, end)
        return (a[0] < b[1]) and (b[0] < a[1])

    def reg(
        pid: str,
        action_type: str,
        start: float,
        end: float,
        *,
        ev: Optional["Event"] = None,
        idx: int | None = None,
    ) -> None:
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
                # Suggest moving this start to the end of the overlapping interval
                suggested_start = max(start, other[1])
                suggested_duration = max(0.01, end - suggested_start)
                err(
                    f"Action overlap for player '{pid}': '{action_type}' interval [{start:.3f}, {end:.3f}) "
                    f"overlaps '{other[2]}' interval [{other:.3f}, {other:.3f}). Players cannot perform overlapping movement/pressure/marking actions. "
                    f"Suggested fix: set start_time to ≥ {other:.3f} (e.g., {suggested_start:.3f}) or reduce duration; "
                    f"if moved, new duration could be ≈ {suggested_duration:.3f}s.",
                    ctx=None
                    if ev is None or idx is None
                    else {
                        "event_index": idx,
                        "event_id": ev.event_id,
                        "phase_id": ev.phase_id,
                        "action": action_type,
                        "start": float(start),
                        "end": float(end),
                        "duration": float(end - start),
                    },
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
        ev: "Event",
    ) -> None:
        if duration <= 0:
            return
        dx = end_pt[0] - start_pt[0]
        dy = end_pt[1] - start_pt[1]
        dist = math.hypot(dx, dy)  # normalized units over 1x1 pitch
        speed = dist / duration
        if speed > _MAX_SPEED_NORM:
            min_duration = dist / _MAX_SPEED_NORM if _MAX_SPEED_NORM > 0 else duration
            err(
                f"Unrealistic {label} speed for player '{pid}': distance={dist:.3f}, duration={duration:.3f}s, "
                f"speed={speed:.3f} > threshold= {_MAX_SPEED_NORM:.3f}. "
                f"Start=({start_pt:.3f},{start_pt:.3f}) -> End=({end_pt:.3f},{end_pt:.3f}). "
                f"Suggested fix: increase duration to ≥ {min_duration:.3f}s or reduce the travel distance.",
                ctx={
                    "event_index": idx,
                    "event_id": ev.event_id,
                    "phase_id": ev.phase_id,
                    "action": label,
                    "start": float(ev.start_time),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    "end": float(ev.start_time + ev.duration),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    "duration": float(ev.duration),
                },
            )

    def check_player(pid: str, label: str, i: int, ev: "Event") -> None:
        if pid not in all_ids:
            err(
                f"{label}: unknown player id '{pid}'. Known attacking={sorted(atk_ids)}; defending={sorted(def_ids)}. "
                "Suggested fix: change the field to a valid Player.id or add the player to the appropriate team.",
                ctx={
                    "event_index": i,
                    "event_id": ev.event_id,
                    "phase_id": ev.phase_id,
                    "action": getattr(
                        ev.action.root,
                        "action_type",
                        type(ev.action.root).__name__,
                    ),
                    "start": float(ev.start_time),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    "end": float(ev.start_time + ev.duration),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    "duration": float(ev.duration),
                },
            )

    # --- Event loop ---
    for i, ev in enumerate(data.events):
        start = float(ev.start_time)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        end = start + float(ev.duration)
        act = ev.action.root
        act_label = getattr(act, "action_type", type(act).__name__)

        ctx_base = {
            "event_index": i,
            "event_id": ev.event_id,
            "phase_id": ev.phase_id,
            "action": act_label,
            "start": start,
            "end": end,
            "duration": float(ev.duration),
        }

        match act:
            # Action handlers (semantic + realism)
            case PassAction():
                check_player(act.from_player, "PASS.from_player", i, ev)
                check_player(act.to_player, "PASS.to_player", i, ev)
                if ball_state != BallState.CONTROLLED or ball_owner != act.from_player:
                    err(
                        "PASS requires the ball to be controlled by the passer at event start. "
                        f"Found ball_state='{ball_state.name}', ball_owner='{ball_owner}', expected owner='{act.from_player}'. "
                        "Suggested fix: add/adjust prior events so the passer controls the ball at this start_time.",
                        ctx=ctx_base,
                    )
                if player_zone.get(act.from_player) != act.from_zone:
                    err(
                        "PASS.from_zone must equal passer's current zone at start. "
                        f"Passer='{act.from_player}', from_zone='{act.from_zone.name}', current_zone='{fmt_zone(player_zone.get(act.from_player))}'. "
                        "Suggested fix: set PASS.from_zone to the passer's current zone or add a preceding MOVE/DRIBBLE to place the passer there.",
                        ctx=ctx_base,
                    )
                # PASS does not move players
                ball_owner = act.to_player
                ball_zone = act.to_zone
                ball_state = BallState.CONTROLLED

            case DribbleAction():
                check_player(act.player, "DRIBBLE.player", i, ev)
                if ball_state != BallState.CONTROLLED or ball_owner != act.player:
                    err(
                        "DRIBBLE requires the ball to be controlled by the dribbler at event start. "
                        f"Found ball_state='{ball_state.name}', ball_owner='{ball_owner}', expected owner='{act.player}'. "
                        "Suggested fix: add/adjust prior events so this player controls the ball at start_time.",
                        ctx=ctx_base,
                    )
                if player_zone.get(act.player) != act.from_zone:
                    err(
                        "DRIBBLE.from_zone must equal player's current zone at start. "
                        f"Player='{act.player}', from_zone='{act.from_zone.name}', current_zone='{fmt_zone(player_zone.get(act.player))}'. "
                        "Suggested fix: set DRIBBLE.from_zone to the player's current zone or add a preceding MOVE to put them in from_zone.",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.player, "DRIBBLE", start, end, ev=ev, idx=i)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt
                ball_owner = act.player
                ball_zone = act.to_zone
                ball_state = BallState.CONTROLLED

            case MoveAction():
                check_player(act.player, "MOVE.player", i, ev)
                if player_zone.get(act.player) != act.from_zone:
                    err(
                        "MOVE.from_zone must equal player's current zone at start. "
                        f"Player='{act.player}', from_zone='{act.from_zone.name}', current_zone='{fmt_zone(player_zone.get(act.player))}'. "
                        "Suggested fix: set MOVE.from_zone to the player's current zone or adjust prior events accordingly.",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.player, "MOVE", start, end, ev=ev, idx=i)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case RunAction():
                check_player(act.player, "RUN.player", i, ev)
                if player_zone.get(act.player) != act.from_zone:
                    err(
                        "RUN.from_zone must equal player's current zone at start. "
                        f"Player='{act.player}', from_zone='{act.from_zone.name}', current_zone='{fmt_zone(player_zone.get(act.player))}'. "
                        "Suggested fix: set RUN.from_zone to the player's current zone or add a preceding MOVE to place them there.",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.player, "RUN", start, end, ev=ev, idx=i)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case OverlapAction():
                check_player(act.runner, "OVERLAP.runner", i, ev)
                check_player(act.outside_player, "OVERLAP.outside_player", i, ev)
                ref_zone = player_zone.get(act.outside_player)
                if ref_zone is None:
                    err(
                        f"OVERLAP requires outside_player '{act.outside_player}' to have a known zone at event start. "
                        "Suggested fix: ensure outside_player has been positioned in a prior event.",
                        ctx=ctx_base,
                    )
                else:
                    if not is_outside_relative(act.to_zone, ref_zone):
                        err(
                            "OVERLAP.to_zone must be laterally outside relative to outside_player's lane. "
                            f"outside_player='{act.outside_player}', outside_lane={lane_index.get(ref_zone, center_lane)}, "
                            f"to_zone='{act.to_zone.name}', to_lane={lane_index.get(act.to_zone, center_lane)}. "
                            "Suggested fix: choose a wider lane for to_zone than the outside_player's lane (relative to center).",
                            ctx=ctx_base,
                        )
                    runner_from = player_zone.get(act.runner)
                    if runner_from and not is_forward_progress(
                        act.to_zone,
                        runner_from,
                    ):
                        err(
                            "OVERLAP.to_zone should represent forward progression. "
                            f"runner='{act.runner}', from_zone='{runner_from.name}', to_zone='{act.to_zone.name}'. "
                            "Suggested fix: select an attacking-depth zone (MID/ATT) ahead of the runner's current band.",
                            ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.runner, "OVERLAP", start, end, ev=ev, idx=i)
                player_zone[act.runner] = act.to_zone
                player_pos[act.runner] = end_pt

            case UnderlapAction():
                check_player(act.runner, "UNDERLAP.runner", i, ev)
                check_player(act.outside_player, "UNDERLAP.outside_player", i, ev)
                ref_zone = player_zone.get(act.outside_player)
                if ref_zone is None:
                    err(
                        f"UNDERLAP requires outside_player '{act.outside_player}' to have a known zone at event start. "
                        "Suggested fix: ensure outside_player has been positioned in a prior event.",
                        ctx=ctx_base,
                    )
                else:
                    if not is_inside_relative(act.to_zone, ref_zone):
                        err(
                            "UNDERLAP.to_zone must be laterally inside relative to outside_player's lane. "
                            f"outside_player='{act.outside_player}', outside_lane={lane_index.get(ref_zone, center_lane)}, "
                            f"to_zone='{act.to_zone.name}', to_lane={lane_index.get(act.to_zone, center_lane)}. "
                            "Suggested fix: choose a lane closer to center than the outside_player's lane.",
                            ctx=ctx_base,
                        )
                    runner_from = player_zone.get(act.runner)
                    if runner_from and not is_forward_progress(
                        act.to_zone,
                        runner_from,
                    ):
                        err(
                            "UNDERLAP.to_zone should represent forward progression. "
                            f"runner='{act.runner}', from_zone='{runner_from.name}', to_zone='{act.to_zone.name}'. "
                            "Suggested fix: select an attacking-depth zone (MID/ATT) ahead of the runner's current band.",
                            ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.runner, "UNDERLAP", start, end, ev=ev, idx=i)
                player_zone[act.runner] = act.to_zone
                player_pos[act.runner] = end_pt

            case CheckToBallAction():
                check_player(act.player, "CHECK_TO_BALL.player", i, ev)
                if act.to_zone != ball_zone:
                    err(
                        "CHECK_TO_BALL.to_zone must equal the ball's zone at event start. "
                        f"Player='{act.player}', to_zone='{act.to_zone.name}', ball_zone='{ball_zone.name}'. "
                        "Suggested fix: set to_zone to the current ball_zone or retime this event to when the ball is in the desired zone.",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.player, "CHECK_TO_BALL", start, end, ev=ev, idx=i)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case ThirdManRunAction():
                check_player(act.runner, "THIRD_MAN_RUN.runner", i, ev)
                start_pt = player_pos[act.runner]
                end_pt = apply_offsets(act.to_zone, act.to_position)
                speed_check(
                    pid=act.runner,
                    start_pt=start_pt,
                    end_pt=end_pt,
                    duration=ev.duration,
                    label="THIRD_MAN_RUN",
                    idx=i,
                    ev=ev,
                )
                reg(act.runner, "THIRD_MAN_RUN", start, end, ev=ev, idx=i)
                player_zone[act.runner] = act.to_zone
                player_pos[act.runner] = end_pt

            case CrossAction():
                check_player(act.from_player, "CROSS.from_player", i, ev)
                if ball_state != BallState.CONTROLLED or ball_owner != act.from_player:
                    err(
                        "CROSS requires the ball to be controlled by the crosser at event start. "
                        f"Found ball_state='{ball_state.name}', ball_owner='{ball_owner}', expected owner='{act.from_player}'. "
                        "Suggested fix: add a prior PASS/DRIBBLE so the crosser owns the ball at this start_time.",
                        ctx=ctx_base,
                    )
                if act.result.name == "RECEIVED":
                    if act.target_player is None:
                        err(
                            "CROSS.result=RECEIVED requires target_player to be set. "
                            "Suggested fix: set CrossAction.target_player to the intended receiver's Player.id.",
                            ctx=ctx_base,
                        )
                    else:
                        check_player(act.target_player, "CROSS.target_player", i, ev)
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
                            "CROSS.result=OUT_OF_PLAY must be the final event in the scenario timeline. "
                            f"Events remaining after this cross: {len(data.events) - 1 - i}. "
                            "Suggested fix: remove subsequent events or change CrossAction.result to a non-terminal value.",
                            ctx=ctx_base,
                        )

            case ShotAction():
                check_player(act.player, "SHOT.player", i, ev)
                if ball_state != BallState.CONTROLLED or ball_owner != act.player:
                    err(
                        "SHOT requires the ball to be controlled by the shooter at event start. "
                        f"Found ball_state='{ball_state.name}', ball_owner='{ball_owner}', expected owner='{act.player}'. "
                        "Suggested fix: add a prior PASS/DRIBBLE so the shooter owns the ball at this start_time.",
                        ctx=ctx_base,
                    )
                if player_zone.get(act.player) != act.shot_zone:
                    err(
                        "SHOT.shot_zone must equal shooter's current zone at start. "
                        f"Shooter='{act.player}', shot_zone='{act.shot_zone.name}', current_zone='{fmt_zone(player_zone.get(act.player))}'. "
                        "Suggested fix: set shot_zone to the current zone or add a preceding MOVE/DRIBBLE to place the shooter there.",
                        ctx=ctx_base,
                    )
                if act.result.name in ("GOAL", "OUT_OF_PLAY"):
                    if i != len(data.events) - 1:
                        err(
                            f"SHOT.result={act.result.name} must be the final event in the scenario timeline. "
                            f"Events remaining after this shot: {len(data.events) - 1 - i}. "
                            "Suggested fix: remove subsequent events or change ShotAction.result to a non-terminal value.",
                            ctx=ctx_base,
                        )
                else:
                    ball_owner = None
                    ball_state = BallState.LOOSE
                    ball_zone = act.shot_zone

            case PressAction():
                check_player(act.player, "PRESS.player", i, ev)
                check_player(act.target_player, "PRESS.target_player", i, ev)
                if act.player in atk_ids:
                    err(
                        f"PRESS presser should belong to defending_team (found presser='{act.player}' on attacking_team). "
                        "Suggested fix: assign the presser to defending_team or change the action to a defensive player.",
                        ctx=ctx_base,
                    )
                if act.target_player in def_ids:
                    err(
                        f"PRESS target should belong to attacking_team (found target='{act.target_player}' on defending_team). "
                        "Suggested fix: select an attacking-team player as target or correct roster assignments.",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.player, "PRESS", start, end, ev=ev, idx=i)
                player_pos[act.player] = end_pt

            case MarkAction():
                check_player(act.defender, "MARK.defender", i, ev)
                check_player(act.attacker, "MARK.attacker", i, ev)
                if act.defender in atk_ids:
                    err(
                        f"MARK defender should belong to defending_team (found defender='{act.defender}' on attacking_team). "
                        "Suggested fix: assign this player to defending_team or swap the roles.",
                        ctx=ctx_base,
                    )
                if act.attacker in def_ids:
                    err(
                        f"MARK attacker should belong to attacking_team (found attacker='{act.attacker}' on defending_team). "
                        "Suggested fix: assign the attacker to attacking_team or change the attacker ID.",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.defender, "MARK", start, end, ev=ev, idx=i)
                player_pos[act.defender] = end_pt

            case TrackRunnerAction():
                check_player(act.defender, "TRACK_RUNNER.defender", i, ev)
                check_player(act.runner, "TRACK_RUNNER.runner", i, ev)
                if act.defender in atk_ids:
                    err(
                        f"TRACK_RUNNER defender should belong to defending_team (found defender='{act.defender}' on attacking_team). "
                        "Suggested fix: assign the defender to defending_team.",
                        ctx=ctx_base,
                    )
                if act.runner in def_ids:
                    err(
                        f"TRACK_RUNNER runner should belong to attacking_team (found runner='{act.runner}' on defending_team). "
                        "Suggested fix: assign the runner to attacking_team.",
                        ctx=ctx_base,
                    )
                # Continuous behavior; register interval for concurrency checks
                reg(act.defender, "TRACK_RUNNER", start, end, ev=ev, idx=i)

            case DropAction():
                check_player(act.player, "DROP.player", i, ev)
                # DROP is "defensive retreat toward defending team's own goal"
                if act.player not in def_ids:
                    err(
                        f"DROP player should belong to defending_team (found '{act.player}' on attacking_team). "
                        "Suggested fix: move this player to defending_team or change the action to a defender.",
                        ctx=ctx_base,
                    )
                from_z = player_zone.get(act.player)
                if from_z and not is_forward_progress(act.to_zone, from_z):
                    err(
                        "DROP.to_zone must move toward defending team's own goal (attacking perspective: forward). "
                        f"Player='{act.player}', from_zone='{from_z.name}', to_zone='{act.to_zone.name}'. "
                        "Suggested fix: choose a deeper zone (toward y=1.0 from attacking perspective).",
                        ctx=ctx_base,
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
                    ev=ev,
                )
                reg(act.player, "DROP", start, end, ev=ev, idx=i)
                player_zone[act.player] = act.to_zone
                player_pos[act.player] = end_pt

            case ShiftAction():
                # Rigid movement of defending outfield block (GK excluded)
                # Check overlaps with other SHIFTs
                for s_rng in shift_intervals:
                    if overlaps((start, end), s_rng):
                        err(
                            f"SHIFT overlaps another SHIFT; defensive block translation should be singular. "
                            f"Current SHIFT [{start:.3f}, {end:.3f}) overlaps [{s_rng:.3f}, {s_rng:.3f}). "
                            f"Suggested fix: schedule this SHIFT to start at ≥ {s_rng:.3f} or retime the prior SHIFT.",
                            ctx=ctx_base,
                        )
                        break
                shift_intervals.append((start, end))
                dist_norm = act.distance
                speed = dist_norm / ev.duration if ev.duration > 0 else 0.0
                if speed > _MAX_SHIFT_SPEED_NORM:
                    min_duration = (
                        dist_norm / _MAX_SHIFT_SPEED_NORM
                        if _MAX_SHIFT_SPEED_NORM > 0
                        else ev.duration
                    )
                    err(
                        f"SHIFT unrealistic speed: distance={dist_norm:.3f}, duration={ev.duration:.3f}s, "
                        f"speed={speed:.3f} > threshold={_MAX_SHIFT_SPEED_NORM:.3f}. "
                        f"Suggested fix: increase duration to ≥ {min_duration:.3f}s or reduce act.distance.",
                        ctx=ctx_base,
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
                                    f"SHIFT overlaps '{rng[2]}' for defender '{pid}' "
                                    f"(SHIFT [{start:.3f}, {end:.3f}) vs {rng[2]} [{rng:.3f}, {rng:.3f}]); "
                                    "rigid block semantics prohibit concurrent individual movement. "
                                    f"Suggested fix: retime the individual action to end by {start:.3f} or delay SHIFT to start at ≥ {rng:.3f}.",
                                    ctx=ctx_base,
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
                        reg(p.id, "SHIFT", start, end, ev=ev, idx=i)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]

            case TurnoverAction():
                if act.winner is not None:
                    check_player(act.winner, "TURNOVER.winner", i, ev)
                    if (
                        act.winning_team == TeamType.ATTACK
                        and act.winner not in atk_ids
                    ):
                        err(
                            f"TURNOVER.winner must belong to attacking_team when winning_team=ATTACK "
                            f"(winner='{act.winner}' is not on attacking_team). "
                            "Suggested fix: change 'winning_team' to DEFEND or select an attacking-team winner.",
                            ctx=ctx_base,
                        )
                    if (
                        act.winning_team == TeamType.DEFEND
                        and act.winner not in def_ids
                    ):
                        err(
                            f"TURNOVER.winner must belong to defending_team when winning_team=DEFEND "
                            f"(winner='{act.winner}' is not on defending_team). "
                            "Suggested fix: change 'winning_team' to ATTACK or select a defending-team winner.",
                            ctx=ctx_base,
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
                "At event completion, ball_zone must equal ball owner's current zone when ball_state=CONTROLLED. "
                f"owner='{ball_owner}', owner_zone='{fmt_zone(player_zone.get(ball_owner))}', ball_zone='{ball_zone.name}'. "
                "Suggested fix: set ball_zone to the owner's zone after the event, or ensure the owner moves into ball_zone within the event.",
                ctx=ctx_base,
            )

    # --- Expected outcomes terminality guard ---
    last_action = data.events[-1].action.root
    if (
        isinstance(last_action, ShotAction)
        and last_action.result.name in ("GOAL", "OUT_OF_PLAY")
        and len(data.expected_outcomes) > 0
    ):
        err(
            "Expected outcomes present after a terminal SHOT result; scenario should end without further guaranteed states. "
            f"Terminal result='{last_action.result.name}', expected_outcomes count={len(data.expected_outcomes)}. "
            "Suggested fix: remove expected_outcomes or make the final SHOT non-terminal (e.g., SAVED/BLOCKED/OUT_OF_PLAY already terminal).",
        )

    return errors
