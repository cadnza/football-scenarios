# scenario.json — Outstanding Interpretation Questions

## Purpose of this document

`scenario.json` is a JSON Schema describing a single association-football
tactical scenario. It is intended to be the **single source of truth** for the
scenario type: consuming applications generate their formal types directly from
it, never duplicate its type information elsewhere, and never read scenario
files as dynamic hash maps.

A schema that fully does its job would let any consumer read it and know
exactly how every part is meant to be semantically interpreted, without
guessing. This document collects the places where that is not yet true.

Each question below should be resolved **inside the schema itself** — via
`title` / `description` text, added fields, tightened constraints, or clearer
structure — rather than in external prose. Once resolved, downstream design
documents will simply say "see `scenario.json`."

## Consuming context (why these questions matter)

The primary consumer is an iOS application that teaches football pattern
recognition. It renders each scenario as a short animated sequence — a
top-down pitch with players and the ball as moving markers — and asks the user
to identify which tactic was demonstrated.

To animate a scenario, the application must derive two things the schema does
not currently express:

1. **Geometry** — where on the pitch each named zone is, in continuous
   coordinates.
2. **Time** — when each event starts, how long it takes, and what happens
   simultaneously.

The application is also required to be renderer-agnostic: a 2D top-down
renderer, a 3D renderer, and an isometric renderer must all be able to convey
the *same* semantic content from the *same* scenario file. That raises the bar
on the schema: the meaning of an action must be recoverable from the schema
alone, not from a convention baked into one particular renderer.

---

## 1. Canonical serialization format

**Current state.** `scenario.json` is a JSON Schema (draft 2020-12). The actual
scenario corpus is authored as YAML files (a few thousand of them, most a few
hundred lines, some up to roughly a thousand).

**The ambiguity.** The schema does not state what serialization the instance
documents use. JSON Schema validates an abstract data model, so YAML instances
are legitimate — but only for the subset of YAML that maps cleanly onto JSON's
model. Several YAML features have no JSON equivalent and would silently break a
strict consumer: anchors and aliases (`&ref` / `*ref`), merge keys (`<<:`),
non-string mapping keys, explicit tags (`!!str`), multiple documents per file
(`---` separators), and `.inf` / `.nan` numerics.

**Why it matters.** The consuming application intends to convert the corpus to a
compact binary pack at build time. Whether it needs a full YAML 1.2 parser or
can rely on a restricted subset determines whether a third-party YAML
dependency enters the build toolchain at all.

**Resolution should specify:** the canonical on-disk format; whether YAML
anchors/aliases/merge-keys are permitted in the corpus; whether one file always
contains exactly one scenario document; and whether the schema is intended to
validate the YAML directly or only a JSON projection of it.

---

## 2. Zone geometry and the zone grid *(added — extends question 2 below)*

**Current state.** The `zone` enum has 38 values. Thirty-three of them
decompose into an apparently regular 11-column × 3-band grid:

- **DEF third:** `DEF_LEFT_CORNER`, `DEF_LEFT_WING`, `DEF_LEFT_HALFSPACE`,
  `DEF_LEFT_CHANNEL`, `DEF_CENTER_LEFT`, `DEF_CENTER`, `DEF_CENTER_RIGHT`,
  `DEF_RIGHT_CHANNEL`, `DEF_RIGHT_HALFSPACE`, `DEF_RIGHT_WING`,
  `DEF_RIGHT_CORNER`
- **MID third:** same eleven lanes, except the outermost lane is
  `MID_LEFT_TOUCHLINE` / `MID_RIGHT_TOUCHLINE` rather than `CORNER`
- **ATT third:** same eleven lanes, with `ATT_ZONE14_LEFT` / `ATT_ZONE14` /
  `ATT_ZONE14_RIGHT` occupying the three central lanes

The remaining five — `LEFT_BOX`, `CENTER_BOX`, `RIGHT_BOX`, `PENALTY_SPOT`,
`SIX_YARD_BOX` — carry no third prefix.

**The ambiguity.**

(a) *Is the 11 × 3 grid interpretation correct and intentional?* If so, the
    schema should say so, because every consumer must independently rediscover
    it otherwise.

(b) *Are the eleven lanes of equal width?* A real pitch's halfspaces and
    channels are not typically the same width as the central lane, and a
    consumer has no way to know the intended proportions.

(c) *Are the three bands of equal depth?*

(d) *`CORNER` vs `TOUCHLINE`.* The outermost lane is named `CORNER` in the DEF
    and ATT thirds but `TOUCHLINE` in MID. Does `CORNER` denote an area extreme
    in *both* axes (a genuine pitch corner, hard against the goal line), while
    `TOUCHLINE` denotes merely the outermost lane at normal band depth? Or are
    all eleven lanes uniform in every band and the naming is purely
    conventional?

(e) *The five box zones.* These plainly overlap the ATT-third zones
    geometrically. Are they intended as a finer-grained overlay usable
    interchangeably with the ATT lanes — such that a player could be described
    as being in either `ATT_ZONE14` or `CENTER_BOX` for the same physical
    position — or do they denote areas that the ATT lanes do not cover?
    Specifically: does `CENTER_BOX` sit *inside* the penalty area, whereas
    `ATT_ZONE14` sits outside it?

(f) *Is `PENALTY_SPOT` a zone or a point?* It is the only enum value that reads
    as a location rather than a region.

(g) *Is there a defensive-third equivalent of the box zones?* There is no
    `DEF_CENTER_BOX` or equivalent, which implies the box zones are only ever
    used in the attacking third. Confirm.

**Why it matters.** The consuming application must build a zone-to-coordinate
table. If the proportions are left to the consumer, two different renderers will
place the same scenario differently, and a scenario authored with a particular
spatial relationship in mind may not display that relationship.

**Resolution should specify:** either explicit normalized geometry per zone in
the schema (e.g. a documented rect in a 0–1 pitch space), or an unambiguous
prose specification of the grid and its proportions in the `zone` enum's
`description`.

---

## 3. `play_direction` and the perspective of zone names *(added)*

**Current state.** `metadata.play_direction` has four values:
`BOTTOM_TO_TOP`, `TOP_TO_BOTTOM`, `LEFT_TO_RIGHT`, `RIGHT_TO_LEFT`. Zones are
prefixed `DEF_` / `MID_` / `ATT_` and contain `LEFT` / `RIGHT` components.

**The ambiguity.**

(a) Are `DEF` / `MID` / `ATT` always relative to the **attacking** team — so
    `DEF_CENTER` is the attacking team's own defensive third, i.e. the area in
    front of the attacking team's own goal?

(b) Are `LEFT` and `RIGHT` relative to the attacking team's direction of play
    (a player's own left as they face the goal they are attacking), or relative
    to a fixed viewer?

(c) Is `play_direction` purely a **presentation hint** telling a renderer which
    way to orient the pitch on screen — with the zone semantics unaffected — or
    does it change how zone names should be interpreted?

(d) May a renderer freely normalize all scenarios to a single canonical screen
    orientation and ignore `play_direction`? If not, what does
    `play_direction` convey that would be lost?

(e) Does `play_direction` interact with `zone_position.lane_offset`? That field
    is documented as "negative values move toward the left side of the zone" —
    left from whose perspective?

**Why it matters.** Getting this wrong mirrors every scenario, turning every
overlap into an underlap.

---

## 4. Event concurrency and the meaning of `sequence`

**Current state.** Each event has an integer `sequence`. The events array is
described as "Ordered football actions." Nothing constrains `sequence` to be
unique, contiguous, or to start at any particular value.

**The ambiguity.**

(a) Is `sequence` guaranteed unique within a scenario?

(b) If two events share a `sequence` value, does that mean they occur
    **simultaneously**?

(c) If `sequence` is always unique, is the intent that every action in a
    scenario is strictly serial — that nothing ever overlaps in time?

(d) Must `sequence` values be contiguous and start at a fixed value, or are
    gaps permitted (e.g. 10, 20, 30 to allow later insertion)?

(e) Is `sequence` guaranteed to agree with array order, or may the array be
    unordered with `sequence` as the authority?

**Why it matters.** This is the most consequential open question for animation
fidelity. Football is fundamentally concurrent: a defensive block shifts *while*
a pass travels; an overlapping run begins *before* the pass that releases it. If
every event must play strictly one after another, every scenario will animate as
a turn-based sequence, which misrepresents the sport and undermines an app whose
entire purpose is training real-time pattern recognition.

**Resolution should specify:** whether concurrency is expressible at all, and if
so, the exact mechanism (shared `sequence` values, an explicit grouping field,
an explicit start-offset field, or something else).

---

## 5. Event duration and timing

**Current state.** No field anywhere in the schema carries a duration, a
timestamp, a velocity, or a tempo.

**The ambiguity.** How long does each event take? A 40-metre switch of play
and a 5-metre lay-off are both a single `PASS` event.

**Sub-questions.**

(a) Should duration be derived by the consumer from the geometric distance
    between `from_zone` and `to_zone`, combined with a per-action-type notion
    of speed?

(b) Actions with no zones at all (`CHECK_TO_BALL`, `DROP`, `THIRD_MAN_RUN`,
    `SHIFT`, and others — see question 6) offer no distance to derive from.
    How should those be timed?

(c) Is there an intended notion of **tempo** — is a scenario meant to convey
    that a particular sequence is played quickly under pressure versus
    patiently in build-up? `defensive_block.pressure_level` hints at this but
    does not express it.

(d) Should there be a pause between events, and is any such pause
    tactically meaningful (e.g. a player holding the ball to attract pressure)
    or purely a presentational choice?

**Why it matters.** Recognition of several tactics — `COUNTER_ATTACK`,
`COUNTER_PRESS`, `SWITCH_PLAY` — depends materially on tempo. If timing is
entirely at the consumer's discretion, a counter-attack may animate at the same
speed as a patient build-up, erasing the distinguishing cue.

**Resolution should specify:** either explicit optional timing fields on
`event`, or an explicit statement that timing is consumer-derived along with
the rule for deriving it.

---

## 6. Actions with no destination

**Current state.** Of the fifteen action types, six carry both a `from_zone` and
a `to_zone` (`PASS`, `DRIBBLE`, `MOVE`, `RUN`) or a target zone (`CROSS`,
`SHOT`). The remaining nine carry **no spatial information at all**:

| Action | Fields |
| --- | --- |
| `OVERLAP` | `runner`, `outside_player` |
| `UNDERLAP` | `runner`, `outside_player` |
| `CHECK_TO_BALL` | `player` |
| `THIRD_MAN_RUN` | `runner` |
| `PRESS` | `player`, `target_player` |
| `MARK` | `defender`, `attacker` |
| `TRACK_RUNNER` | `defender`, `runner` |
| `DROP` | `player` |
| `SHIFT` | `direction` only |

**The ambiguity.** Where does each of these players end up? Any renderer must
invent a destination, and two renderers will invent different ones — violating
the requirement that all renderers convey the same semantic content.

**Sub-questions.**

(a) **`OVERLAP(runner, outside_player)`** — does the runner end in the lane
    *outside* `outside_player`, and how far forward? Is `outside_player`
    stationary, or does the pair exchange positions?

(b) **`UNDERLAP(runner, outside_player)`** — symmetric question for the lane
    *inside* (the halfspace). How far forward?

(c) **`CHECK_TO_BALL(player)`** — does the player move toward the current ball
    position, and by how much? Does "checking to the ball" here imply the
    characteristic move-away-then-come-short double movement, or a simple
    approach?

(d) **`THIRD_MAN_RUN(runner)`** — where does the runner start and end? A third-man
    run is defined by its relationship to two passes; does the schema intend
    that relationship to be recoverable from surrounding events, or should the
    action itself carry the destination?

(e) **`PRESS(player, target_player)`** — does the presser arrive at the target,
    or stop at a pressing distance? Does the target's own position update?

(f) **`MARK(defender, attacker)`** — does the defender take a goal-side
    position? Which goal — the defending team's own?

(g) **`TRACK_RUNNER(defender, runner)`** — is this a continuous behavior spanning
    subsequent events, or a discrete movement completed within one event?

(h) **`DROP(player)`** — drop toward which goal, and how far? One band? To a
    specific zone?

(i) **`SHIFT(direction)`** — see question 7.

**Why it matters.** Nine of fifteen action types is a majority of the vocabulary.
`OVERLAP`, `UNDERLAP`, and `THIRD_MAN_RUN` are also three of the twelve tactics
the user is asked to identify — so the exact geometry of those runs is precisely
what the app is teaching.

**Resolution should specify, for each action:** either explicit destination
fields (which may be optional, with a documented default), or an unambiguous
derivation rule in the action's `description`, expressed in terms of the zone
grid rather than in loose prose.

---

## 7. `SHIFT` — who shifts, and how far?

**Current state.** `shift_action` requires only `action_type` and `direction`
(`LEFT` / `RIGHT` / `FORWARD` / `BACKWARD`). It is the only action with no
player reference of any kind.

**The ambiguity.**

(a) **Who shifts?** The entire defending team? Only the defensive line? Only
    outfield players? The presumption is that this is a collective defensive
    movement, but the schema does not say so, and nothing structurally prevents
    it describing an attacking team's collective movement.

(b) **How far?** A full lane? Half a lane? "Until compact relative to the ball"?

(c) **Is the shift rigid?** Do all shifting players translate by the same
    vector, or does the block deform (near-side players shifting further than
    far-side)?

(d) **Do `LEFT` / `RIGHT` refer to the same frame of reference as zone names?**
    (See question 3.)

(e) **Is `FORWARD` relative to the attacking team's direction of play** — so
    `FORWARD` means the defensive block steps up toward the attacking team's own
    goal?

(f) Does a `SHIFT` interact with `defensive_block.compactness` and `height` —
    i.e. does a `FORWARD` shift change the block height from `MID_BLOCK` to
    `HIGH_PRESS`, and should a consumer model that state change?

---

## 8. Ball trajectory and terminal actions

**Current state.** `cross_action` has `from_player` and `target_zone` but no
receiver. `shot_action` has `player` and `shot_zone`.

**The ambiguity.**

(a) **`CROSS`** — is the cross intended to find a specific player? If a teammate
    is in or arriving at `target_zone`, should a consumer infer that they receive
    it? Is the cross always successful?

(b) **`SHOT`** — is `shot_zone` the zone the shot is *taken from*, or the zone it
    is aimed at? The field name suggests the former, which would make it
    redundant with the shooter's current position — unless the shooter is
    expected to have moved.

(c) **Outcome.** Is a shot a goal? Saved? Off target? The schema has a
    `SHOT_CREATED` outcome type but nothing describing what happens to the ball.

(d) **Ball possession as derived state.** `initial_state.ball_owner` establishes
    who starts with the ball. Is possession thereafter fully derivable from the
    event stream (`PASS` transfers to `to_player`, `DRIBBLE` retains,
    `CROSS`/`SHOT` release), or can possession change without an explicit event?

(e) **Loose ball.** After a `CROSS` or `SHOT`, is the ball considered unowned?
    Is there any way to express a turnover, an interception, or a second ball?
    `COUNTER_ATTACK` and `COUNTER_PRESS` are both in the tactic enum, and both
    conventionally begin with a change of possession — can a scenario
    representing either actually express the turnover that defines it?

(f) **Trajectory.** Is a pass along the ground or in the air? Does the schema
    intend to distinguish a driven pass, a lofted switch, and a chip? Ball flight
    is a strong visual cue in a switch of play.

**Why it matters.** Item (e) is the most serious: two of the twelve tactics the
user must identify appear to be inexpressible in the current event vocabulary.

---

## 9. Player state continuity across events *(added)*

**Current state.** Players have a `starting_zone`. Movement actions carry
`from_zone` and `to_zone`. There is no explicit per-event world state.

**The ambiguity.**

(a) Is a player's position after an event **persistent** — so that a player who
    `MOVE`s to `MID_CENTER` in event 3 is in `MID_CENTER` for all subsequent
    events until they move again?

(b) Is the corpus guaranteed **self-consistent** — i.e. will an event's
    `from_zone` always equal the zone the player currently occupies according to
    the preceding events and their `starting_zone`? If a consumer encounters a
    contradiction, is that a corpus bug (fail loudly) or a legitimate
    abbreviation (teleport silently)?

(c) Do the zoneless actions in question 6 update player position persistently?
    If a `DROP` moves a player and a later event gives that player a `from_zone`,
    those two must agree — which is only possible if the `DROP` destination is
    precisely specified.

(d) Does `PASS` move the passer? A `from_player` passing from `from_zone`
    presumably stays put, but the schema does not say so.

(e) Are players not named in any event guaranteed stationary for the entire
    scenario? A renderer must decide whether to animate them at all.

**Why it matters.** This determines whether the animation layer can maintain a
running world-state model and assert against it, or must treat each event as
independent and self-describing.

---

## 10. Multiple players in one zone, and `zone_position` defaults

**Current state.** `zone_position` is an optional refinement on `player` with
optional `lane_offset` and `depth_offset` in the range −1.0 to 1.0, documented as
"used to establish spacing within the zone rather than to specify exact pitch
coordinates."

**The ambiguity.**

(a) **When `zone_position` is absent**, what position within the zone is meant?
    The exact center? Unspecified, at the consumer's discretion?

(b) **When two or more players share a starting zone and neither specifies a
    `zone_position`**, are they intended to be co-located? A renderer drawing
    both at the zone center draws one marker on top of another.

(c) **Is the offset space square?** An offset of 1.0 on each axis presumably
    means the corner of the zone — but if zones are not square (see question 2),
    a `lane_offset` of 0.5 and a `depth_offset` of 0.5 represent different
    physical distances. Is that intended?

(d) **Is `zone_position` ever tactically meaningful**, or purely cosmetic
    spacing? For example, does a striker with `depth_offset: 0.9` in
    `ATT_ZONE14` mean something specific about being on the shoulder of the last
    defender?

(e) **Does `zone_position` persist through movement?** A player with
    `lane_offset: -0.8` who `MOVE`s to a new zone — do they retain that offset
    in the destination zone, reset to center, or is it undefined?

(f) **Is there a maximum sensible occupancy per zone?** Should a consumer treat
    five players in one zone as a corpus error?

---

## 11. `initial_state.ball_zone` versus the ball owner's `starting_zone` *(added)*

**Current state.** `game_state` requires `ball_owner` (a player id) and
`ball_zone`. Separately, each player has a `starting_zone`.

**The ambiguity.** These two can disagree. If `ball_owner` is `left-back`, whose
`starting_zone` is `DEF_LEFT_WING`, but `initial_state.ball_zone` is
`MID_LEFT_WING`, which is authoritative?

**Sub-questions.**

(a) Is `ball_zone` guaranteed to equal the ball owner's `starting_zone`? If so,
    it is redundant and should be documented as such (or removed).

(b) If they may legitimately differ, what does that represent — a ball in flight
    at scenario start? A player about to receive?

(c) Can `ball_owner` be absent or reference a non-player (e.g. a scenario
    beginning with a loose ball, a throw-in, or a goal kick)? The field is a
    required plain string with no pattern constraint, unlike `player.id` which
    is constrained to `^[a-z]+(-[a-z]+)*$`.

---

## 12. `player.team` versus the containing team object *(added)*

**Current state.** The root has `attacking_team` and `defending_team`, each with
a `players` array. Each `player` additionally carries a required `team` field of
type `team_type` (`ATTACK` / `DEFEND`).

**The ambiguity.** A player inside `attacking_team.players` could carry
`team: "DEFEND"`. Nothing in the schema prevents it.

**Sub-questions.**

(a) Which is authoritative if they disagree — the containing array or the field?

(b) Is `player.team` intended purely as a convenience for consumers that flatten
    both arrays into one collection?

(c) Could the field ever legitimately differ from its container (for instance,
    to express a player switching sides — which does not occur in football)?

(d) If it is pure redundancy, should it be removed? Redundant fields that can
    contradict are a standing source of consumer bugs, and the schema's stated
    philosophy is that type information should never be duplicated.

**Related:** are player `id` values guaranteed unique across *both* teams, or
only within a team? The `pattern` constraint does not imply uniqueness, and
actions reference players by bare id with no team qualifier — so cross-team
uniqueness appears to be required for actions like `MARK` and `PRESS` to resolve
unambiguously.

---

## 13. Defensive movement: explicit events versus `expected_defensive_response` *(added)*

**Current state.** `phase` has an optional `expected_defensive_response` with
values like `SHIFT_LEFT`, `DROP_DEEPER`, `DOUBLE_TEAM`, `TRACK_RUNNER`,
`PRESS_BALL`, `PROTECT_CENTER`. Separately, the action vocabulary includes
defensive actions (`PRESS`, `SHIFT`, `MARK`, `TRACK_RUNNER`, `DROP`) that can
appear as events.

**The ambiguity.**

(a) Is `expected_defensive_response` **descriptive metadata** (explaining to a
    coach what the defense is expected to do) or **prescriptive** (an instruction
    that a consumer should render as actual defensive movement)?

(b) If prescriptive, how does it compose with explicit defensive events? If a
    phase declares `SHIFT_LEFT` *and* contains an explicit `SHIFT` event with
    `direction: LEFT`, is that the same shift described twice, or two shifts?

(c) Is defensive movement in the corpus guaranteed to be expressed explicitly as
    events wherever it is meant to be visible? A renderer that only animates
    explicit events will show a completely static defense in any scenario where
    the movement is only implied — which would make a switch of play, whose entire
    point is that the block shifts and cannot recover, look like nothing happened.

(d) Does `defensive_block` (height, compactness, pressure level) evolve over the
    course of a scenario, or is it strictly an initial condition? It appears only
    in `initial_state`.

---

## 14. Is `metadata.tactic` the single correct answer? *(added)*

**Current state.** `metadata.tactic` is a single required value from a
twelve-value enum. Separately, each event carries a required `tactical_purpose`
from a twelve-value enum that partially overlaps it (`CREATE_WIDTH`,
`SWITCH_PLAY`, `BREAK_LINE` appear in both), and `player.tactical_instructions`
draws from a third overlapping enum.

**The ambiguity.**

(a) Is `metadata.tactic` intended to be the **single, unambiguous, correct**
    classification of the scenario as a whole — such that an application can
    quiz a user on it and mark any other answer wrong?

(b) Can a scenario legitimately demonstrate more than one tactic? An overlap that
    creates width and then switches play is plausibly all three of `OVERLAP`,
    `CREATE_WIDTH`, and `SWITCH_PLAY`. If so, should `tactic` become an array,
    or should there be a primary tactic plus secondary tactics?

(c) What is the intended relationship between `metadata.tactic` and the
    `tactical_purpose` values of the events? Is the tactic meant to be the
    emergent consequence of the purposes, or an independent label?

(d) `tactic` and `tactical_purpose` share names but are different enums. Is the
    overlap intentional, and do the shared names mean the same thing in both
    contexts? Should the two enums be unified, or renamed to avoid the collision?

**Why it matters.** The application asks the user to select the demonstrated
tactic from the full enum. If `metadata.tactic` is not a defensible single
answer, the app is marking correct answers wrong.

---

## 15. `difficulty` — semantics and ordering *(added)*

**Current state.** `difficulty` is an enum: `LEVEL1_NOVICE`, `LEVEL2_BEGINNER`,
`LEVEL3_INTERMEDIATE`, `LEVEL4_ADVANCED`, `LEVEL5_EXPERT`.

**The ambiguity.**

(a) **Is enum declaration order authoritative for ordering?** The application
    needs a total order on difficulty (to drive a two-sided range filter, and to
    reason about a user's progression) and must derive it from the schema without
    duplicating it in code. Declaration order is the only available source. Is it
    safe to rely on — i.e. is it a schema-authoring commitment that ordered
    enums are always declared in order?

(b) **What makes a scenario harder?** Is difficulty a property of how subtle the
    *recognition* is (the same tactic disguised), how *complex* the execution is
    (more players, more phases), or how advanced the *concept* is? These imply
    different things about what a Level 5 `OVERLAP` looks like.

(c) **Is difficulty comparable across tactics?** Is a Level 3 `WALL_PASS`
    intended to be about as hard to recognize as a Level 3 `PRESSING_TRAP`?
    The application aggregates accuracy across tactics at a given level, which is
    only meaningful if levels are calibrated consistently.

(d) **Is every (tactic, difficulty) pair populated?** Do Level 1 examples exist
    for every tactic, and Level 5 for every tactic? The application surfaces
    coverage gaps to the user and would otherwise report the user as having a
    gap where the corpus simply has none.

---

## 16. Intent of the descriptive fields *(added)*

**Current state.** Several fields carry prose or classification intended for a
human reader, with no stated audience or timing:

- `event.tactical_explanation` (string)
- `event.advantages_created` (array of `advantage`, each with a type and
  optional zone, player, and description)
- `phase.attacking_goal`, `phase.success_condition` (strings)
- `expected_outcomes` (array of `outcome`)
- `coaching_notes` (array of strings)

**The ambiguity.**

(a) **`expected_outcomes`** — are these assertions about the **end state** of the
    scenario, or things that may become true at any point during it? Are they
    guaranteed to actually occur, or are they the *intended* outcomes that may or
    may not be realized?

(b) **`advantage.zone` is optional.** When omitted, what does the advantage apply
    to — the whole pitch, the current ball zone, the named player's zone? A
    renderer that highlights the zone where space was created needs to know.

(c) **`advantage.player` is optional.** Same question: who benefits when it is
    omitted?

(d) **`coaching_notes` audience.** Are these written for a coach running a
    session, or for a learner studying alone? The distinction affects whether an
    app should surface them to an end user.

(e) **Spoiler safety.** The application hides all explanatory text until after
    the user has answered. Is any of this prose guaranteed *not* to name the
    tactic outright? Conversely, is `phase.name` safe to display during playback,
    or might a phase named "Switch to the weak side" give the answer away?

(f) **Are the prose fields ever load-bearing?** Is any of this text ever the only
    place a piece of tactical information appears, or is the prose always
    redundant with the structured event data?

---

## Summary of what a resolved schema would need

1. A stated canonical serialization and permitted YAML subset.
2. Explicit or precisely specified zone geometry, including lane and band
   proportions, corner semantics, and the relationship of the five box zones to
   the attacking-third lanes.
3. A stated frame of reference for `LEFT` / `RIGHT` / `FORWARD` and the role of
   `play_direction`.
4. A stated concurrency model for `sequence`.
5. A stated timing model (explicit fields or a precise derivation rule).
6. For each of the nine zoneless actions, either destination fields or a precise
   destination rule expressed in zone-grid terms.
7. A specified actor, magnitude, and rigidity for `SHIFT`.
8. Ball-trajectory and terminal-action semantics, including whether turnovers are
   expressible at all.
9. A stated player-state continuity model and self-consistency guarantee.
10. `zone_position` defaults, persistence, and collision rules.
11. Resolution of the `ball_zone` / `starting_zone` and `player.team` /
    containing-array redundancies.
12. A stated rule for whether defensive movement is always explicit.
13. A statement that `metadata.tactic` is (or is not) a single defensible answer.
14. A commitment on enum declaration order for ordered enums, and a definition of
    what difficulty measures.
15. Audience, timing, and spoiler-safety guarantees for the prose fields.
