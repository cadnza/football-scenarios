# Armchair FC — Implementation Design Document

**Bundle identifier:** `com.by-sbs.armchairfc`
**Deployment target:** iOS 27.0
**Language mode:** Swift 6, full strict concurrency
**Schema source of truth:** `scenario_new.json`

---

## 0. How to read this document

This document is the complete implementation plan for Armchair FC. It is written for an
LLM-powered coding agent working in a blank Xcode project. It is intended to contain no
open questions. Where a decision could reasonably have gone more than one way, the decision
is stated, and the reasoning is recorded in **Appendix B — Interpretation Register** so a
human can audit it later.

Read sections 1–9 before writing any code. Then implement the milestones in section 10 in
order. Each milestone is independently completable and carries explicit acceptance criteria.
Do not begin a milestone until the previous milestone's acceptance criteria pass.

Three rules govern the entire codebase and are repeated throughout because violating them
silently is the primary failure mode of this project:

1. **`scenario_new.json` is the only source of truth for the scenario type.** No Swift type,
   enum, constant, string table, or switch default may restate information that the schema
   already carries.
2. **Scenario data is never handled as a dynamic dictionary.** Not at load time, not in
   tests, not in a helper. It is always a generated formal type.
3. **Every mapping keyed by a schema enum is an exhaustive `switch` with no `default:` clause.**
   A dictionary literal keyed by a schema enum silently returns `nil` when the schema gains a
   case. An exhaustive switch fails to compile. Always choose the compile error.

---

## 1. What the app is

Armchair FC teaches association-football pattern recognition to someone with no playing or
spectating background. It presents short, animated tactical scenarios — a top-down pitch with
players and the ball as moving markers — and asks the user to identify the tactic being
demonstrated.

**Learn Mode** walks the user through scenarios of a chosen tactic and difficulty, with a
written concept primer and a step-by-step explanation synchronized to the animation.

**Play Mode** shows a scenario with no explanation and asks the user to name the tactic, with
three attempts. Results feed a time-aware statistics and recommendation engine.

The scenario corpus is a few thousand YAML files, fixed at ship time, each conforming to
`scenario_new.json`. Scenarios are semantically pre-validated by the author; the app's job is
to verify structural and referential integrity **at build time** and then trust the data at
runtime.

---

## 2. Non-goals

Do not implement, scaffold, or leave TODOs for any of the following. They are deliberately out
of scope.

- Widgets, Live Activities, Control Center controls
- Push or local notifications
- App Intents, Shortcuts, Siri
- Game Center, leaderboards, achievements
- Sharing, social features, user-generated content
- watchOS, macOS, tvOS, or visionOS targets
- In-app purchase, subscriptions, paywalls
- Third-party analytics, crash reporting, or telemetry SDKs
- **Any networking whatsoever.** The app makes no outbound connections. The only network
  activity in the product is CloudKit sync performed by the system on the app's behalf.

---

## 3. Architecture

### 3.1 Project layout

A single Xcode project containing one app target and one local Swift package.

```
ArmchairFC/
├── ArmchairFC.xcodeproj
├── ArmchairFC/                      # App target — thin SwiftUI wrapper
│   ├── ArmchairFCApp.swift
│   ├── Navigation/
│   ├── Screens/
│   ├── Resources/
│   │   └── Assets.xcassets
│   └── ArmchairFC.entitlements
├── ArmchairFCKit/                   # Local Swift package — all logic
│   ├── Package.swift
│   ├── Sources/
│   │   ├── SchemaGen/               # executable (tool)
│   │   ├── ScenarioPacker/          # executable (tool)
│   │   ├── ScenarioSchema/          # GENERATED — do not hand-edit
│   │   ├── ScenarioPack/
│   │   ├── PitchGeometry/
│   │   ├── ScenarioEngine/
│   │   ├── ScenarioRendering/       # the only target that imports SwiftUI
│   │   ├── TrainerCore/
│   │   ├── TrainerStats/
│   │   ├── Persistence/
│   │   └── Primers/
│   └── Tests/                       # one test target per source target
├── Corpus/                          # YAML scenario files, not bundled directly
├── Schema/
│   └── scenario_new.json
└── Tools/
    └── generate.sh
```

### 3.2 Target responsibilities and dependency graph

```
ScenarioSchema      (no dependencies — generated types only)
        ↑
PitchGeometry       → ScenarioSchema
ScenarioPack        → ScenarioSchema
        ↑
ScenarioEngine      → ScenarioSchema, PitchGeometry, ScenarioPack
        ↑
TrainerCore         → ScenarioEngine, Persistence
TrainerStats        → ScenarioSchema, Persistence
Primers             → ScenarioSchema
Persistence         → (SwiftData only; stores raw strings, not schema enums)
        ↑
ScenarioRendering   → ScenarioEngine, PitchGeometry  [imports SwiftUI]
        ↑
ArmchairFC (app)    → all of the above
```

Tools (`SchemaGen`, `ScenarioPacker`) are executable targets that are **never linked into the
app binary**. They exist to be run from the command line during development.

### 3.3 The UI boundary

No app logic lives in the app target. The app target contains only: the `App` struct, the
navigation structure, screen composition, and the wiring of package-provided view models to
SwiftUI views.

`ScenarioRendering` is the single package target permitted to import SwiftUI. This is
deliberate and is not a compromise: the renderer protocol's entire purpose is to produce
views, and placing it in the app target would make renderers untestable and would prevent
shipping alternative renderers as package products later. Every other package target must
compile without SwiftUI, UIKit, or any UI framework.

### 3.4 Concurrency

Swift 6 language mode with `SwiftSettings.swiftLanguageMode(.v6)` and strict concurrency
checking on every target. Consequences to honor:

- All generated schema types are `Sendable` (they are value types of `Sendable` members).
- `ScenarioLibrary`, the pack reader, is an `actor`.
- `PlaybackController` and all view models are `@MainActor @Observable`.
- The renderer protocol is `Sendable`; the view-producing method is `@MainActor`.
- SwiftData `ModelContext` work happens on a `@ModelActor` for writes; reads for UI use the
  main-actor context.

---

## 4. Schema code generation

### 4.1 Approach

Types are generated ahead of time by a Swift executable, checked into the repository, and
protected from drift by a unit test. The generated sources live in `Sources/ScenarioSchema/`
and carry a header marking them generated.

This is chosen over an SPM build-tool plugin because the generated code stays readable and
greppable by the implementing agent and by Xcode's indexer, and because build-tool plugins
introduce trust prompts and rebuild cost on every compile. The drift test provides the same
practical guarantee: it is impossible to commit or ship code whose types disagree with the
schema.

### 4.2 `SchemaGen` — the generator

An executable target that reads a JSON Schema file and writes Swift sources.

```
swift run --package-path ArmchairFCKit SchemaGen \
    --schema Schema/scenario_new.json \
    --output ArmchairFCKit/Sources/ScenarioSchema
```

**Supported JSON Schema constructs.** The generator handles exactly the subset below. On
encountering anything else, it must print a precise diagnostic naming the offending JSON
pointer and exit non-zero. **It must never emit `[String: Any]`, `AnyCodable`, or any dynamic
container as a fallback.**

| Construct | Handling |
|---|---|
| `$defs/<name>` | One Swift type per definition |
| `$ref` (local only) | Reference to the generated type |
| `type: object` + `required` + `additionalProperties: false` | `struct` |
| `type: string` + `enum` | `enum … : String` |
| `oneOf` of objects each with a `const` discriminator property | `enum` with associated values |
| `const` | Discriminator; not emitted as a stored property |
| `type: [ "string", "null" ]` | `String?` |
| `type: array` + `items` (+ `minItems`) | `[Element]` |
| `type: number` / `integer` / `boolean` | `Double` / `Int` / `Bool` |
| `pattern`, `minimum`, `maximum`, `exclusiveMinimum` | Emitted as documentation only |
| `title`, `description` | Emitted as `///` doc comments |

**Naming.** JSON `snake_case` becomes Swift `lowerCamelCase` for properties and
`UpperCamelCase` for types, with explicit `CodingKeys` preserving the wire names. Enum cases
convert `SCREAMING_SNAKE_CASE` to `lowerCamelCase` with an explicit raw value
(`case thirdManRun = "THIRD_MAN_RUN"`). The root schema generates `public struct Scenario`.

**Conformances.** Every generated type: `public`, `Codable`, `Hashable`, `Sendable`. Every
generated string enum additionally: `CaseIterable`.

**Ordered enums.** Every generated string enum gets:

```swift
public var declarationIndex: Int { Self.allCases.firstIndex(of: self)! }
```

`Difficulty` is made `Comparable` by a single hand-written extension in `ScenarioEngine`:

```swift
extension Difficulty: Comparable {
    public static func < (lhs: Self, rhs: Self) -> Bool {
        lhs.declarationIndex < rhs.declarationIndex
    }
}
```

This is the only permitted statement of difficulty ordering anywhere in the codebase. It
duplicates no type information: if a level is added, removed, or reordered in the schema, the
ordering follows automatically. Do not write a `rank`, `level`, or `sortOrder` property.
`Tactic` must **not** be made `Comparable` — the schema states its declaration order is not
semantic.

**Discriminated union.** `action` becomes:

```swift
public enum Action: Codable, Hashable, Sendable {
    case pass(PassAction)
    case dribble(DribbleAction)
    // … one case per oneOf branch, in schema order
    case turnover(TurnoverAction)
}
```

decoded by reading `action_type` and dispatching. Decoding an unrecognized `action_type`
throws `DecodingError.dataCorrupted`. **Every `switch` over `Action` in the codebase omits
`default:`** so that adding an action type to the schema produces compile errors at every site
that must handle it.

**Schema fingerprint.** The generator emits:

```swift
public enum SchemaFingerprint {
    public static let sha256 = "…"   // SHA-256 of the schema file's bytes
}
```

### 4.3 Drift protection

`ScenarioSchemaTests` contains a test that:

1. Locates `Schema/scenario_new.json` via a package resource path.
2. Runs the generator's library entry point in memory.
3. Asserts the produced sources are byte-identical to the checked-in files.

Failure message must read: *"Generated schema types are stale. Run `Tools/generate.sh`."*

`Tools/generate.sh` runs `SchemaGen` and then `ScenarioPacker` in sequence. It is the single
documented command a developer runs after editing the schema.

### 4.4 The anti-duplication discipline

Beyond exhaustive switches, `ScenarioSchemaTests` must contain **coverage tests** that iterate
`allCases` and assert total coverage of every hand-maintained table:

- Every `Zone` has a geometry entry.
- Every `Tactic` has a display name and a primer file.
- Every `Difficulty` has a display name.
- Every `Role` has an abbreviation and a display name.
- Every `Action` case is handled by the timeline builder (asserted by constructing an
  in-memory value of each generated case — not a YAML file — and checking no `unsupported`
  path is taken).

These tests assert coverage by enumeration, never by comparing against a hardcoded count.
Do not write `XCTAssertEqual(Tactic.allCases.count, 12)`.

---

## 5. Corpus pipeline

### 5.1 Format and the Yams dependency

The corpus is YAML 1.2 restricted to the JSON data model, one document per file, per the
schema's own description. `ScenarioPacker` depends on **Yams** (`github.com/jpsim/Yams`),
pinned to the current 5.x release; resolve the exact version and commit `Package.resolved`.

This is the only third-party dependency in the project, and it is a **tool-only** dependency.
It must not appear in the dependency list of any target that the app links. Add a test in
`ScenarioPackTests` that reads the package manifest and asserts no app-linked target depends
on Yams.

`ScenarioPacker` must reject any file using YAML features outside the JSON data model —
anchors, aliases, merge keys, explicit tags, non-string mapping keys, multiple documents, or
`.inf`/`.nan` — with a diagnostic naming the file and line.

### 5.2 Scenario identity

The **filename stem is the canonical scenario ID.** `switch-play-0421.yaml` yields ID
`switch-play-0421`. The packer fails the build on any duplicate stem across the corpus.
`metadata.title` is display text only and is never used as a key.

### 5.3 The packer

```
swift run --package-path ArmchairFCKit ScenarioPacker \
    --corpus Corpus \
    --schema Schema/scenario_new.json \
    --output ArmchairFC/Resources/scenarios.afcpack
```

For every file the packer:

1. Parses YAML into a JSON-model value and rejects out-of-subset YAML.
2. Re-encodes to canonical JSON and decodes into the generated `Scenario` type. A decode
   failure fails the build with the file path and the decoding error path.
3. Runs the **build-time validator** (5.4). Any violation fails the build.
4. Records an index entry and appends the zlib-compressed JSON payload.

The packer prints a summary: scenario count, total and per-tactic/per-difficulty counts,
uncompressed and compressed byte totals, and the list of empty `(tactic, difficulty)` cells.

### 5.4 Build-time validator

The corpus is semantically pre-validated by its author, so this validator checks structural
and referential integrity only. It is the gate that lets the runtime carry no defensive code.

Each check fails the build with the scenario ID and a precise message:

1. Every player `id` is unique across **both** teams.
2. Every player reference in every action, and `initial_state.ball_owner`, resolves to a
   declared player.
3. `event.phase_id` resolves to a `plan.phases[].id`.
4. `event.sequence` equals the event's array index plus one, for every event.
5. `event_id` values are unique within the scenario.
6. `initial_state.ball_owner` is non-null when `ball_state` is `CONTROLLED`, and null when it
   is `LOOSE`.
7. When `ball_state` is `CONTROLLED`, `ball_zone` equals the owner's `starting_zone`.
8. Every `PASS`'s `from_zone` equals the passer's position at the event's `start_time`, as
   computed by the world-state model (6.2).
9. Every zoned action's `from_zone` (where present) agrees with the actor's position at
   `start_time`.
10. `CHECK_TO_BALL.to_zone` equals the ball's zone at the event's `start_time`.
11. `CROSS` with `result: RECEIVED` has a `target_player`.
12. A `SHOT` with `result: GOAL` or `OUT_OF_PLAY` is the final event in the array.
13. A `CROSS` with `result: OUT_OF_PLAY` is the final event in the array.
14. No two events with overlapping time intervals move the same player. (Two events may
    overlap in time; they may not contradict each other about one player's position.)
15. `OVERLAP.to_zone` is in a lane strictly outside `outside_player`'s lane at `start_time`;
    `UNDERLAP.to_zone` is in a lane strictly inside it.
16. Every action that requires possession — `PASS`, `DRIBBLE`, `CROSS`, `SHOT` — is performed
    by the current ball owner at `start_time`.
17. `SHIFT` appears only where the defending team has at least one non-GK player.
18. A `TURNOVER` carrying a `winner` has a `zone` equal to that player's zone at the event's
    completion, per the schema's agreement requirement.
19. A `TURNOVER` whose `winning_team` is `ATTACK` has a `winner` (when present) drawn from
    `attacking_team.players`, and likewise for `DEFEND`.
20. No `CROSS` or `SHOT` carrying a non-terminal `result` is followed by an event that assumes
    a controlled ball without an intervening `TURNOVER` or reception.

These twenty checks correspond one-to-one with guarantees the schema asserts. Where the schema
states a consistency constraint, the packer enforces it; the runtime then performs none of
these checks and carries no defensive branches for them.

### 5.5 Pack file format

A single binary resource, `scenarios.afcpack`, memory-mapped at runtime.

```
Offset  Size  Field
0       4     magic = "AFCP" (ASCII)
4       4     formatVersion : UInt32 little-endian, currently 1
8       32    schemaFingerprint : SHA-256 of the schema file bytes
40      8     indexOffset : UInt64 LE
48      8     indexLength : UInt64 LE
56      8     payloadOffset : UInt64 LE
64      8     payloadLength : UInt64 LE
72      …     reserved, zero-filled to 128
128     …     index blob (zlib-compressed JSON array of ScenarioIndexEntry)
…       …     payload region (concatenated zlib-compressed JSON documents)
```

```swift
public struct ScenarioIndexEntry: Codable, Hashable, Sendable {
    public let id: String
    public let title: String
    public let tactic: Tactic
    public let difficulty: Difficulty
    public let attackingPlayerCount: Int
    public let defendingPlayerCount: Int
    public let eventCount: Int
    public let phaseCount: Int
    public let durationSeconds: Double
    public let payloadOffset: UInt64
    public let compressedLength: UInt64
    public let uncompressedLength: UInt64
}
```

Compression uses Apple's `Compression` framework (`COMPRESSION_ZLIB`), a system framework.

### 5.6 Runtime library

```swift
public actor ScenarioLibrary {
    public init(packURL: URL) throws
    public nonisolated var index: [ScenarioIndexEntry] { get }
    public func scenario(id: String) throws -> Scenario
}
```

- At init, verify magic and `formatVersion`, then assert
  `schemaFingerprint == SchemaFingerprint.sha256`. A mismatch throws — it means the pack and
  the generated types were built from different schema revisions.
- The index decodes fully at init (a few thousand small entries; target under 50 ms).
- Payloads decompress and decode lazily, backed by an LRU cache of 32 decoded `Scenario`
  values.
- All filtering, counting, and statistics run against the index. **Never decode a payload to
  answer a filtering or statistics question.**

### 5.7 Test fixtures

Scenario fixtures are supplied by the project owner in `Tests/Fixtures/` and are real corpus
files. They are inputs to this project, not artifacts of it. The agent does not write them,
does not edit them, and does not substitute generated files when they are missing or failing.

The corpus should ideally exercise every `Action` case including `TURNOVER`, every `result` and
`trajectory` value, both `ball_state` values, and at least a few scenarios with genuinely
overlapping event intervals, since those are what prove the concurrency model. **If the supplied
fixtures leave any of that uncovered, report the gap and continue** — state plainly which cases
are untested and let the owner decide whether to supply more. Do not close a coverage gap by
inventing a scenario, and do not weaken a test so that an uncovered case appears to pass.

The same applies to failures. A fixture that will not decode, or that trips a validator check,
is a finding: it means the schema, the packer, or that file is wrong, and which one it is
matters. Report it with the file name and the specific check, and stop. Never resolve it by
editing the fixture.

---

## 6. Scenario semantics

This section defines exactly how a `Scenario` becomes motion. It is derived from
`scenario_new.json` and adds no tactical judgment; where the schema leaves a residual degree
of freedom, the choice is recorded in Appendix B.

### 6.1 Coordinate spaces

**Normalized space.** `x ∈ [0, 1]` from the attacking team's left touchline to its right
touchline. `y ∈ [0, 1]` from the attacking team's own goal line to the goal it attacks.
Increasing `y` is always FORWARD. This is the space in which zones are defined.

**Metric space.** The schema defines the canonical pitch as **105 length units long by 68 wide**
and mandates that all distance, direction, and interpolation computation happen there rather
than in normalized space, which is anisotropic. Convert with:

```swift
func metric(_ p: NormalizedPoint) -> MetricPoint { MetricPoint(x: p.x * 68, y: p.y * 105) }
```

Computing a distance directly in normalized coordinates is a bug, not a shortcut.

Schema fields expressed as "normalized pitch-distance where 1.0 equals the full pitch length"
(`pressing_distance`, `goal_side_distance`, `tracking_distance`) convert to metric units as
`d × 105`.

`SHIFT.distance` is the one exception and is applied directly in normalized space, because each
axis is already normalized against the dimension it uses: for `LEFT`/`RIGHT`, 1.0 is the full
pitch **width**, so `Δx = ∓distance`; for `FORWARD`/`BACKWARD`, 1.0 is the full pitch **length**,
so `Δy = ±distance`. Translated positions are clamped to the pitch.

**Goal geometry**, per the schema. The attacking team's own goal centre is `(0.5, 0.0)`. The
goal it attacks — the defending team's own goal — is `(0.5, 1.0)`. Each goal mouth is 7.32
length units wide, so its posts sit at `x = 0.5 ± 3.66/68`.

### 6.2 Zone geometry and position resolution

Zone rectangles are given in full in **Appendix A**. They are implemented in `PitchGeometry`
as one exhaustive `switch` over `Zone` with no `default:`.

Resolving a player's point within a zone:

```
rect   = geometry(for: zone)
centre = rect.midpoint
point  = (centre.x + lane_offset  * rect.width  / 2,
          centre.y + depth_offset * rect.height / 2)
```

Absent offsets are `0.0`. `PENALTY_SPOT` is a zero-area anchor at `(0.5, 94/105)`; offsets on
it are ignored.

Per the schema, **moving into a new zone resets unspecified offsets to `0.0`**. A movement
action carrying `to_position` uses those offsets in the destination zone; one without lands at
the destination zone's centre.

Because the schema makes offsets explicit and load-bearing, the renderer performs **no
collision avoidance and no automatic fan-out**. If two markers coincide, the corpus says they
coincide.

### 6.3 World state

`ScenarioEngine` maintains a `WorldState` that can be evaluated at any time `t`:

- Each player's position, initialized from `starting_zone` + `starting_position`.
- Ball state: `CONTROLLED(by:)` or `LOOSE(at:)`, initialized from `initial_state`.

Positions persist. A player who is moved by an event remains at that destination until another
event moves them. A player named in no event never moves.

Timing is fully explicit: an event occupies `[start_time, start_time + duration)`. Scenario
duration is `max(start_time + duration)` across all events. Events whose intervals overlap are
concurrent and are evaluated independently. Gaps between events are exactly that — nothing
happens. Do not insert an implicit pause, hold, or settle.

Movement interpolates **linearly at constant speed in metric space** over the interval, per
the schema. There is no easing. Do not add easing curves; they would misrepresent the timing
the corpus author encoded.

### 6.4 Action kinematics

Each action resolves to zero or more `PlayerTrack`s (a player, a start point, an end point,
and an interval) plus ball behavior. Defined exhaustively:

| Action | Player motion | Ball behavior |
|---|---|---|
| `PASS` | None. The passer does not move. | Ball interpolates from the passer's position at `start_time` to the receiver's position at `start_time + duration`. Possession transfers to `to_player` at completion. `trajectory` is a semantic property the renderer depicts. |
| `DRIBBLE` | Actor moves to `to_zone`/`to_position`. | Ball travels with the actor; possession retained. |
| `MOVE` | Actor moves to `to_zone`/`to_position`. | Unchanged. |
| `RUN` | Actor moves to `to_zone`/`to_position`. | Unchanged. |
| `OVERLAP` | Runner moves to `to_zone`/`to_position`. `outside_player` does not move. | Unchanged. |
| `UNDERLAP` | Runner moves to `to_zone`/`to_position`. `outside_player` does not move. | Unchanged. |
| `CHECK_TO_BALL` | Actor moves to `to_zone`/`to_position`. Single movement only. | Unchanged. |
| `THIRD_MAN_RUN` | Runner moves to `to_zone`/`to_position`. | Unchanged. |
| `CROSS` | None. The crosser does not move. | Ball interpolates from the crosser's position to the target point (6.5). Result determines the end state. |
| `SHOT` | None. | Ball interpolates from `shot_zone` toward the goal (6.5). Result determines the end state. |
| `PRESS` | Presser moves to a point `pressing_distance × 105` metric units short of the target, along the line from the presser's position at `start_time` toward the target's position at `start_time`. **If `pressing_distance` is greater than or equal to the initial separation, the presser does not move at all.** Single movement, not a following behavior. Target does not move. | Unchanged. |
| `SHIFT` | **Every non-GK player of `defending_team`** translates by the same vector (6.1), clamped to the pitch. The goalkeeper is excluded, and no attacking player is ever moved. Positions only; `defensive_block` is not modified. | Unchanged. |
| `MARK` | Defender moves to a point `goal_side_distance × 105` metric units from the attacker's position at `start_time`, along the unit vector from the attacker toward the goal centre `(0.5, 1.0)`. Single movement, not a following behavior. Attacker does not move. | Unchanged. |
| `TRACK_RUNNER` | Continuous, not a one-time move. At each instant in the interval the defender sits `tracking_distance × 105` metric units from the runner's interpolated position, along the unit vector from the runner toward `(0.5, 1.0)` — the same goal-side convention `MARK` uses. **The defender occupies the tracking position from the first instant of the interval**; do not ease or interpolate into it from wherever the defender previously stood. If the runner is stationary, the defender holds position. Never moves the runner. | Unchanged. |
| `DROP` | Actor moves to `to_zone`/`to_position`. | Unchanged. |
| `TURNOVER` | No player motion. | If `winner` is present, possession transfers to that player at completion and the ball's position is that player's position. If absent, the ball becomes `LOOSE` at `zone`'s centre. |

The goal-side unit vector used by `MARK` and `TRACK_RUNNER` points at the goal *centre*, not
straight down the pitch, so a defender marking a wide attacker finishes both deeper and more
central. This is the schema's rule, not a rendering choice.

Degenerate cases, all specified by the schema: if a `PRESS` presser and target occupy the same
point, or a `MARK`/`TRACK_RUNNER` attacker occupies the goal centre exactly, the direction is
taken as increasing `y`.

### 6.5 Ball terminal behavior

Both tables below are transcribed from the schema's `cross_result` and `shot_result`
descriptions. **The ball's destination is never invented by the renderer**; it is a function of
`result` alone.

**`CROSS`** — the ball's origin is the crosser's position at `start_time`.

| `result` | Destination | End state |
|---|---|---|
| `RECEIVED` | `target_player`'s position at `start_time + duration` | `CONTROLLED(by: target_player)` |
| `DEFENDED` | centre of `target_zone` | `LOOSE` |
| `LOOSE` | centre of `target_zone` | `LOOSE` |
| `OUT_OF_PLAY` | centre of `target_zone`, then leaves play | scenario ends; final event |

**`SHOT`** — the ball's origin is the shooter's position `S` at `start_time`. Let `G` be the
goal centre `(0.5, 1.0)` and `P` the nearer post, at `x = 0.5 ∓ 3.66/68` on the side closer to
the shooter.

| `result` | Destination | End state |
|---|---|---|
| `GOAL` | `G` | scenario ends; final event |
| `OUT_OF_PLAY` | `G`, then leaves play | scenario ends; final event |
| `SAVED` | `G` | `LOOSE` |
| `DEFLECTED` | `G` | `LOOSE` |
| `LOOSE` | `G` | `LOOSE` |
| `POST` | `P` | `LOOSE` |
| `BLOCKED` | midpoint of `S` and `G` | `LOOSE` |
| `OFF_TARGET` | on the goal line at `y = 1`, with `x` displaced `4/68` beyond the nearer post, away from the goal | `LOOSE` |

A later `TURNOVER` may establish possession of a loose ball.

### 6.6 `play_direction`

Presentation orientation only. It does not affect any semantics defined above.

**The default 2D renderer normalizes every scenario to a single canonical screen orientation:
the attacking team plays bottom-to-top.** `play_direction` is ignored by the default renderer.
The schema states explicitly that a normalizing renderer is not required to expose, record, or
honor the authored orientation, and that discarding it loses no tactical information. It is
nevertheless carried on `ScenarioTimeline` so that an alternative renderer may honor it.

### 6.7 The timeline

`ScenarioEngine` produces a **coordinate-free** `ScenarioTimeline`:

```swift
public struct ScenarioTimeline: Sendable, Hashable {
    public let scenarioID: String
    public let duration: Double
    public let playDirection: PlayDirection
    public let participants: [Participant]        // id, role, side, displayLabel
    public let beats: [Beat]
    public let breakpoints: [Double]              // sorted unique start_times, plus duration
}

public struct Beat: Sendable, Hashable {
    public let eventID: String
    public let phaseID: String
    public let startTime: Double
    public let duration: Double
    public let action: Action                     // the generated schema type, verbatim
    public let tacticalPurpose: TacticalPurpose
    public let advantages: [Advantage]
    public let explanation: String?               // spoiler-bearing; gated by the UI
    public let accessibilityDescription: String   // generated, spoiler-free
}
```

The timeline is the semantic contract every renderer must honor. It carries no coordinates.

Alongside it, `PitchGeometry` provides `KinematicSolver`, which resolves a `ScenarioTimeline`
into normalized 2D coordinates using the rules in 6.2–6.5:

```swift
public struct ResolvedFrame: Sendable {
    public let time: Double
    public let players: [String: NormalizedPoint]
    public let ball: BallFrame                    // point + CONTROLLED/LOOSE/inFlight
}

public struct KinematicSolver: Sendable {
    public init(scenario: Scenario, timeline: ScenarioTimeline) throws
    public func frame(at time: Double) -> ResolvedFrame
    public func trail(for playerID: String, endingAt time: Double, length: Double) -> [NormalizedPoint]
}
```

`KinematicSolver` is offered to renderers, not imposed on them. A 2D top-down renderer uses it
directly. A 3D or isometric renderer may use it as a planar base and add its own elevation, or
ignore it entirely and resolve the timeline its own way. It exists so that alternative
renderers do not have to re-derive `MARK` or `TRACK_RUNNER` semantics and risk diverging from
the schema.

`frame(at:)` must be pure and deterministic. Given the same scenario and time it returns the
same result, always. No randomness anywhere in the engine or any renderer.

---

## 7. The renderer protocol

### 7.1 Purpose

The animation layer is swappable. Implementations may use entirely different backends, be 2D
or 3D, and adopt any viewpoint. The only thing preserved across implementations is **what the
play means**: given any conforming renderer, a user must be able to tell that a specific
midfielder passed to a specific winger.

### 7.2 The protocol

Defined in `ScenarioRendering`:

```swift
public struct RendererCapabilities: OptionSet, Sendable {
    public static let scrubbing        = RendererCapabilities(rawValue: 1 << 0)
    public static let stepping         = RendererCapabilities(rawValue: 1 << 1)
    public static let variableRate     = RendererCapabilities(rawValue: 1 << 2)
    public static let reducedMotion    = RendererCapabilities(rawValue: 1 << 3)
    public static let alternatePalettes = RendererCapabilities(rawValue: 1 << 4)
}

public struct RenderOptions: Sendable, Hashable {
    public var palette: MarkerPalette
    public var showGhostStartPositions: Bool     // Learn Mode
    public var showTrails: Bool
    public var showAdvantageHighlights: Bool
    public var reduceMotion: Bool
    public var showRoleLabels: Bool
}

@MainActor
public protocol ScenarioRenderer: Sendable {
    associatedtype Body: View

    static var identifier: String { get }         // stable, e.g. "topdown2d"
    static var displayName: String { get }
    static var capabilities: RendererCapabilities { get }

    init()

    func makeView(
        scenario: Scenario,
        timeline: ScenarioTimeline,
        controller: PlaybackController,
        options: RenderOptions
    ) -> Body
}
```

with a type-erased `AnyScenarioRenderer` wrapper and a `RendererRegistry` holding the
available implementations. Ship one implementation in v1; the registry and the settings
plumbing exist from the start, and the settings picker is hidden while the registry holds a
single entry.

`PlaybackController` is the shared clock and is renderer-agnostic:

```swift
@MainActor @Observable
public final class PlaybackController {
    public private(set) var currentTime: Double
    public private(set) var isPlaying: Bool
    public var rate: Double                       // 0.25 … 2.0, default 1.0
    public let breakpoints: [Double]
    public let duration: Double
    public private(set) var replayCount: Int

    public func play()
    public func pause()
    public func seek(to time: Double)
    public func stepForward()                     // play to next breakpoint, then pause
    public func stepBackward()                    // seek to previous breakpoint
    public func restart()                         // increments replayCount
    public var currentStepIndex: Int { get }
}
```

### 7.3 Semantic fidelity contract

Every conforming renderer must convey, unambiguously, at every moment:

1. Which markers are attacking-team players and which are defending-team players.
2. Which individual player each marker is (role label, number, or equivalent persistent
   identity).
3. Where the ball is, and whether it is controlled or loose.
4. Which player controls the ball, when one does.
5. Each player's movement between their encoded start and end positions, over the encoded
   interval.
6. The source and destination of every pass, cross, and shot.
7. The relative timing of concurrent events — that two things happened at once.

`ScenarioRenderingTests` contains a **conformance suite** parameterized over the registry.
Every registered renderer must pass it. It verifies that the renderer consumes the timeline
without crashing across the supplied fixture corpus, respects
`PlaybackController` state transitions, honors `reduceMotion`, and produces the same output
for the same inputs on repeated invocation.

### 7.4 The default 2D renderer

`TopDownRenderer`, `identifier: "topdown2d"`, all capabilities.

Implemented as a SwiftUI `Canvas` inside `TimelineView(.animation)`, sampling
`KinematicSolver.frame(at:)` at the controller's current time. Twenty-two markers at 60 fps in
`Canvas` is trivial; do not reach for SpriteKit.

Visual conventions:

- **Pitch:** attacking team plays bottom-to-top. Dark surface, thin light line work: touchlines,
  halfway line, centre circle, both penalty areas, both six-yard boxes, penalty spots. No
  zone grid by default; a debug overlay may draw it.
- **Attackers:** filled circles. **Defenders:** circles with a heavy stroke and a hollow or
  strongly desaturated fill. The fill/stroke distinction is load-bearing: it must read
  correctly with color removed entirely.
- **Role labels** (`LB`, `CAM`, `ST`) inside each marker, from `Role` — never from `player.id`,
  which the schema marks spoiler-bearing. This teaches positional vocabulary as a side effect.
  Hidden below a marker size threshold and controlled by `showRoleLabels`.
- **Ball:** a smaller light circle with a dark ring, always drawn above all markers.
- **Ball carrier:** a ring around the controlling player's marker. Removed when the ball is
  loose.
- **Ball flight:** `GROUND` / `DRIVEN` draw straight; `LOFTED`, `LOFTED_CROSS`, `LOW_AERIAL`,
  `HIGH_AERIAL` draw along an arc whose apex height scales with the trajectory type, with a
  shadow ellipse tracking the ground position.
- **Trails:** a fading dashed trail behind moving markers, ~1.2 s of history, via
  `KinematicSolver.trail(for:endingAt:length:)`.
- **Pass lines:** a line drawn progressively along the ball's path, fading ~0.6 s after arrival.
- **Advantage highlights:** when a beat declares `advantages_created` with a `zone`, fill that
  zone faintly for the beat's duration. **When `advantage.zone` is absent, render no spatial
  highlight** — the schema forbids attributing it to the ball zone or any player's zone.
- **Ghost start positions:** in Learn Mode, hollow outlines at each player's `starting_zone`.

Palettes: `MarkerPalette` ships with `.classic` (attack red / defend blue), `.highContrast`,
and `.monochrome` (differentiation by fill and stroke only). Selection lives in Settings.

---

## 8. Persistence

### 8.1 Stack

SwiftData with CloudKit via `ModelConfiguration(cloudKitDatabase: .automatic)`, container
`iCloud.com.by-sbs.armchairfc`. Entitlements: iCloud with CloudKit, plus the remote
notifications background mode. No account creation, no sign-in UI.

CloudKit-backed SwiftData imposes constraints that shape the model layer:

- Every property has a default value or is optional.
- No `@Attribute(.unique)`. Uniqueness is enforced in application code.
- Relationships must be optional — so **the model avoids relationships entirely**. All records
  are flat.

### 8.2 Models

```swift
@Model public final class AttemptRecord {
    public var id: UUID = UUID()
    public var sessionID: UUID = UUID()
    public var scenarioID: String = ""
    public var tacticRaw: String = ""          // Tactic.rawValue at time of attempt
    public var difficultyRaw: String = ""      // Difficulty.rawValue at time of attempt
    public var guessesRaw: [String] = []       // ordered, wrong guesses then correct if any
    public var wasCorrect: Bool = false
    public var attemptsUsed: Int = 0
    public var score: Double = 0
    public var presentedAt: Date = Date()
    public var answeredAt: Date = Date()
    public var timeToFirstAnswer: Double = 0
    public var replayCount: Int = 0
}

@Model public final class StudyRecord {
    public var id: UUID = UUID()
    public var scenarioID: String = ""
    public var tacticRaw: String = ""
    public var difficultyRaw: String = ""
    public var studiedAt: Date = Date()
    public var completedAllSteps: Bool = false
}
```

**Schema enums are stored as raw strings, never as enum-typed properties.** This is
deliberate: the schema may change, and the attempt history must survive a tactic being renamed
or removed. Accessors convert on read and tolerate failure:

```swift
public var tactic: Tactic? { Tactic(rawValue: tacticRaw) }
```

Records whose raw values no longer resolve are excluded from statistics and are never
deleted.

The attempt log is **append-only**. Records are never edited, merged, or deduplicated.
Client-generated UUIDs make cross-device CloudKit merges naturally idempotent.

Device-local preferences (playback rate, palette, renderer identifier, onboarding completion)
live in `UserDefaults` via `@AppStorage` and are not synced.

### 8.3 Data export

Settings → Export Data produces a single JSON file via `ShareLink`, containing every
`AttemptRecord` and `StudyRecord` with all fields, an export timestamp, the app version, and
the schema fingerprint. A CSV variant of the attempt log is offered alongside it. Export
performs no aggregation — it emits the raw log so downstream analysis is unconstrained.

Settings → Erase All Progress deletes every record after a destructive confirmation dialog.

---

## 9. Modes, statistics, and recommendations

### 9.1 Spoiler policy

**The schema classifies every field as LEARNER-SAFE or SPOILER-BEARING in that field's own
description, and states that anything not explicitly marked LEARNER-SAFE is spoiler-bearing.
Do not maintain a second copy of this classification in Swift.** Read each field's marking from
`scenario_new.json` and encode the policy as one exhaustive function over the fields Play Mode
can display, so that a reclassification in the schema is a single-site change.

The LEARNER-SAFE set, as the schema currently marks it: `team.name`, `team.formation`,
`player.role`, `phase.name`, `metadata.difficulty`, `metadata.play_direction`, and
`initial_state.defensive_block` with its `height`, `compactness`, and `pressure_level`.

Everything else is hidden in Play Mode until the attempt concludes — notably `metadata.title`,
`metadata.objective`, `metadata.tactic`, `event.tactical_purpose`, `event.tactical_explanation`,
`advantages_created`, `phase.attacking_goal`, `phase.success_condition`, `expected_outcomes`,
`coaching_notes`, and `player.tactical_instructions`.

**`player.id` is spoiler-bearing.** The schema notes that identifiers are authoring
conveniences that may carry tactical hints, and directs consumers quizzing a learner to display
`role` instead. No player ID is ever rendered on screen, in a label, or in an accessibility
string — in either mode.

Generated accessibility descriptions are built from structured action data and role names
only — never from `tactical_purpose`, `tactical_explanation`, `tactic`, or any player ID.

### 9.2 Play Mode

**Filters.** Tactic: multi-select over `Tactic.allCases`; selecting none means all. Difficulty:
a two-sided range over `Difficulty.allCases` ordered by `declarationIndex`, so a
non-contiguous selection is structurally impossible. Filter state persists across launches.
Cells with no scenarios in the corpus are shown disabled with a count of zero.

**Answer grid.** Buttons for `Tactic.allCases`, in declaration order. **The grid's shape is
derived, never hardcoded** — use `LazyVGrid` with `GridItem(.adaptive(minimum:))` so that
adding a tactic to the schema adapts the layout with no code change. Do not write `12`
anywhere.

**Attempts.** `PlayModeConfiguration.maxAttempts = 3`, a compile-time constant in
`TrainerCore`. A wrong selection is marked and permanently disabled for that card. No hints.

**Scoring.** First attempt 1.0, second 0.5, third 0.25, exhausted 0.0. Every guess is recorded
in order, so downstream analysis can see exactly what was confused for what.

**Replays.** Unlimited before and between attempts. `replayCount` is recorded and surfaced as
a recognition-difficulty signal; it never affects score.

**Timing.** No timer and no time pressure. `timeToFirstAnswer` is recorded.

**Session shape.** Default ten cards, then a summary screen. An endless option is available.
No scenario repeats within a session.

**Card selection.** Weighted random from the filtered index, deterministic given a seed for
testability:

```
weight(s) = masteryWeight(cell(s)) × recencyWeight(s)

masteryWeight = 1.0 + 2.0 × (1 − ewma(cell))        // unseen cells use ewma = 0.5
recencyWeight = 1.0                if never seen
              = 0.25               if seen in the last 20 attempts
              = 0.5                if seen in the last 100 attempts
              = 1.0                otherwise
```

**Summary screen.** Cards attempted, score, per-card result with the correct tactic revealed,
a tap-through to each card's full explanation, and any recommendation triggered by the session.

### 9.3 Learn Mode

**Selection.** Pick a tactic, then a difficulty range. The screen shows the tactic's **concept
primer** (section 9.5) and a list of matching scenarios with studied/unstudied state.

**Walkthrough.** A scenario walkthrough presents the animation plus an explanation panel.

A **step** is the interval between consecutive `ScenarioTimeline.breakpoints` — the sorted
unique set of event `start_time` values, plus the scenario duration. This definition handles
concurrent events correctly: stepping forward plays from the current breakpoint to the next at
normal rate and pauses; several concurrent events advance together, as they should.

Controls, all available from the first moment the screen appears:

- **Watch at full speed** — plays the whole scenario from the beginning without stopping.
- **Step forward / step backward** — moves between breakpoints in either direction.
- **Play from here** — begins continuous playback at the current step.
- **Scrub bar** with tick marks at each breakpoint and phase-boundary labels.

The explanation panel shows, for the current step: the phase name and `attacking_goal`, the
`tactical_explanation` of every event active in that step, and the `advantages_created` for
those events. Learn Mode reveals everything; there is nothing to hide.

At the end: `expected_outcomes`, `coaching_notes`, and a prompt to study another scenario or
switch to Play Mode with this tactic pre-filtered.

**Progress.** A `StudyRecord` is written when a scenario is opened, and updated to
`completedAllSteps` when the user reaches the final step. Learn Mode contributes studied-count
and coverage data; it never contributes accuracy data.

### 9.4 Statistics

All statistics derive from the raw attempt log on read. Nothing is stored pre-aggregated, so
the definition of a window can change without a migration.

**Cell.** A `(tactic, difficulty)` pair. Cells are enumerated as the cross product of
`Tactic.allCases` and `Difficulty.allCases`, intersected with cells the corpus actually
contains — a cell with no scenarios is never reported as a user gap.

**Mastery (recency-weighted).** Per cell, process that cell's attempts oldest to newest:

```
α = 1 − 2^(−1/15)        ≈ 0.04516        (half-life of 15 attempts)
m₀ = score of first attempt
mᵢ = mᵢ₋₁ + α × (scoreᵢ − mᵢ₋₁)
```

`ewma(cell)` is the final value. Cells with fewer than `minimumConfidentSample = 5` attempts
are reported as `.insufficientData` and never generate a weakness claim.

**Windows.** Both time-based and count-based, because a user who plays in bursts needs one and
a daily user needs the other:

- Date windows: last 7, 30, and 90 days
- Count windows: last 20, 50, and 100 attempts

Each window reports attempt count, mean score, and first-attempt accuracy.

**Confusion pairs.** From `guessesRaw`, count `(trueTactic, wrongGuess)` occurrences over the
last 100 attempts. Report pairs with at least 3 occurrences, sorted by count, with each pair's
share of that tactic's total errors.

**Recognition speed.** Median `timeToFirstAnswer` per cell, compared against the median across
all cells.

### 9.5 Recommendations

All thresholds live in a single `RecommendationTuning` struct with the values below. Rules
evaluate deterministically; the top three by priority are shown, deduplicated by target cell,
ties broken by cell enumeration order.

| Kind | Trigger | Priority |
|---|---|---|
| `weakness` | `n ≥ 5` and `ewma < 0.5` | `0.9 × (1 − ewma)` |
| `regression` | `n ≥ 10` and mean of last 10 is more than `0.15` below mean of the prior 10 | `0.85` |
| `confusionPair` | A pair occurs ≥ 3 times in the last 100 attempts and is ≥ 40% of that tactic's errors | `0.80` |
| `coverageGap` | Corpus has scenarios for the cell and the user has 0 attempts there | `0.60` |
| `readyToAdvance` | `ewma ≥ 0.8` with `n ≥ 8`, and the next difficulty level up has `< 3` attempts and non-empty corpus coverage | `0.55` |
| `slowRecognition` | `ewma ≥ 0.7` and median `timeToFirstAnswer` is at least 1.5× the all-cell median, `n ≥ 5` | `0.40` |
| `consistency` | No attempts in ≥ 7 days and at least one attempt ever | `0.30` |

Each recommendation carries a title, a plain-language rationale naming the specific cell or
pair, and a deep link that opens either Learn Mode or Play Mode pre-filtered to the target.
`confusionPair` links to Learn Mode for the *confused-with* tactic, since the fix is
understanding the distinction.

Recommendation copy must never scold. `consistency` reads as an invitation, not a streak-loss
warning.

### 9.6 Statistics UI

Swift Charts. Three components on one screen:

1. **Mastery heatmap** — `Tactic.allCases` × `Difficulty.allCases`, cell fill by `ewma`, cells
   with no corpus coverage rendered as unavailable, cells below the confidence threshold
   hatched. Grid dimensions derived from `allCases.count`, never hardcoded. Tapping a cell
   opens a sheet with that cell's detail and a jump into a filtered session.
2. **Trend chart** — mean score across the selected window series, with a window-type toggle
   (by date / by attempt count).
3. **Confusion list** — "You most often read X as Y," with the count, the share, and a link
   into the relevant primer.

---

## 10. Milestones

Complete in order. Do not proceed past a milestone whose acceptance criteria fail.

### M0 — Project skeleton

Create the Xcode project and the local package with every target and test target from 3.1,
each compiling empty. Swift 6 language mode and strict concurrency on all targets. Deployment
target iOS 27.0. Bundle identifier `com.by-sbs.armchairfc`. Add the iCloud/CloudKit
entitlement and the remote-notifications background mode. Commit `scenario_new.json` to
`Schema/`.

*Acceptance:* the project builds for simulator and device with zero warnings; every test
target runs and passes with zero tests; `swift build --package-path ArmchairFCKit` succeeds.

### M1 — Schema code generation

Implement `SchemaGen` per section 4, run it, and commit the generated `ScenarioSchema`
sources. Implement the drift test and the `allCases` coverage test scaffolding. Write
`Tools/generate.sh`.

*Acceptance:* generated types decode every supplied fixture scenario (see M2). The drift test
passes. Deliberately editing the schema and re-running tests produces the "stale" failure.
`Difficulty` sorts correctly; `Tactic` does not conform to `Comparable`. No file in
`ScenarioSchema` is hand-edited.

### M2 — Corpus pipeline

Implement `ScenarioPacker` with Yams, the build-time validator (5.4), the pack format (5.5),
and the `ScenarioLibrary` reader (5.6).

**Fixtures are supplied, not authored.** The project owner provides the fixture corpus in
`Tests/Fixtures/` as real YAML scenario files. **Do not write, invent, synthesize, or
"temporarily" stub scenario files to make a test pass, and do not edit a supplied fixture to
make it validate.** A fixture that fails to decode or fails a validator check is evidence about
the schema, the packer, or the corpus — report it and stop rather than adjusting the data to
fit the code. If no fixtures are present, say so and wait; do not proceed by generating
substitutes.

Two exceptions, both narrow. First, the deliberately-broken inputs used to prove each validator
check fires: derive each by mutating a copy of a supplied fixture minimally, one violation per
copy, under `Tests/Fixtures/Invalid/`. Second, the synthetic pack used for the index-load
performance measurement, which needs volume rather than realism and may be produced by
replicating supplied fixtures under generated IDs.

*Acceptance:* the packer produces a pack from the supplied fixture corpus with no file skipped;
the reader round-trips every scenario byte-identically through decode; a broken copy for each of
the 20 validator checks fails the build with the expected message; a pack built from a modified
schema fails the fingerprint assertion at load; index load from a 3,000-entry synthetic pack
completes in under 50 ms on device; the no-Yams-in-app-targets test passes; no scenario file
outside `Tests/Fixtures/Invalid/` was created or modified by the agent.

### M3 — Pitch geometry

Implement `PitchGeometry`: the exhaustive `Zone` → rect switch from Appendix A, normalized and
metric spaces, and zone-position resolution.

*Acceptance:* every zone has geometry (coverage test); the eleven lanes of each band tile
`[0,1]` in x with no gap or overlap; the three bands tile `[0,1]` in y; box-zone rectangles
match Appendix A to within 1e-9; the three box zones tile the penalty area with no gap or
overlap; `CENTER_BOX` and `SIX_YARD_BOX` have identical x ranges; the flanking boxes are each
exactly 11 metric units wide and `CENTER_BOX` exactly 18.32; the penalty area measures 40.32 by
16.5 metric units and the six-yard box 18.32 by 5.5, matching the Laws of the Game;
`CENTER_BOX` lies inside the penalty area; `PENALTY_SPOT` resolves to `(0.5, 94/105)` — 11
units from the goal line — with offsets ignored; goal posts resolve to `x = 0.5 ± 3.66/68`.

### M4 — Engine

Implement `WorldState`, `ScenarioTimeline` construction, the ball state machine, and
`KinematicSolver` per section 6.

*Acceptance:* for every fixture scenario, `frame(at:)` is deterministic across repeated calls;
`frame(at: 0)` matches declared starting positions exactly; `frame(at: duration)` matches the
positions implied by the final event of each moving player; possession at every instant matches
a hand-computed expectation for at least ten fixtures; concurrent-event fixtures show both
events progressing simultaneously; `SHIFT` translates every non-GK defender by an identical
vector and leaves the goalkeeper untouched; `TRACK_RUNNER` maintains its distance continuously
across the interval rather than moving once; a pass to a receiver who moves during the pass
delivers the ball to the receiver's end position.

### M5 — Rendering

Implement `ScenarioRendering`: the protocol, `AnyScenarioRenderer`, `RendererRegistry`,
`PlaybackController`, `MarkerPalette`, `TopDownRenderer`, and the conformance suite.

*Acceptance:* every fixture scenario renders start to finish without crashing; the conformance
suite passes for `TopDownRenderer`; step forward and backward land exactly on breakpoints;
`restart()` increments `replayCount`; `reduceMotion` produces discrete step transitions with no
continuous interpolation; sustained 60 fps with 22 markers on device; the `monochrome` palette
still distinguishes teams.

### M6 — Persistence

Implement `Persistence` per section 8: models, the `@ModelActor` writer, the CloudKit
configuration, and the erase-all operation.

*Acceptance:* records persist across launches; CloudKit sync between two simulators
converges without duplicates; records with unresolvable raw enum values load without error and
are excluded from statistics; no model property lacks a default; no `@Attribute(.unique)`
appears anywhere; the store opens successfully with CloudKit unavailable.

### M7 — Trainer core

Implement `TrainerCore`: filter model, weighted selection, session state machine, scoring, and
the attempt-record writer.

*Acceptance:* the difficulty filter cannot express a non-contiguous range; an empty tactic
selection means all tactics; selection with a fixed seed is reproducible; no scenario repeats
within a session; scores map 1.0/0.5/0.25/0.0 correctly; every guess is recorded in order;
a session that is abandoned mid-card writes no partial record.

### M8 — Play Mode UI

Build the filter screen, the card screen, and the summary screen in the app target.

*Acceptance:* the answer grid derives its shape from `Tactic.allCases` and adapts when a
tactic is added to the schema, with no code change; no spoiler-bearing field per 9.1 appears
before the attempt concludes; wrong answers are marked and disabled; replays work at every
point; the summary lists every card with its correct answer and a link to its explanation.

### M9 — Primers and Learn Mode

Write the twelve primers per Appendix C, then build the primer screen and the scenario
walkthrough.

*Acceptance:* a primer file exists for every `Tactic` case (coverage test); "watch at full
speed" is available from the first frame; stepping moves between breakpoints in both
directions; "play from here" starts at the current step; the explanation panel shows every
event active in the current step, not just one; `StudyRecord` is written on open and updated on
completion; per-scenario explanation content is displayed in full and is not abridged by the
presence of the primer.

### M10 — Statistics engine

Implement `TrainerStats`: EWMA, windows, confusion pairs, recognition speed, and the
recommendation rules.

*Acceptance:* EWMA matches a hand-computed sequence to 1e-9; cells below the confidence
threshold report `.insufficientData` and generate no weakness recommendation; empty corpus
cells never appear as coverage gaps; each of the seven recommendation rules fires on a
synthetic log built to trigger it and stays silent on one built not to; output is
deterministic for a given log.

### M11 — Statistics UI

Build the heatmap, trend chart, confusion list, and recommendation cards.

*Acceptance:* heatmap dimensions derive from `allCases`; every recommendation's deep link
opens the correct pre-filtered mode; the screen renders correctly with an empty log, with a
single attempt, and with 5,000 attempts; rendering 5,000 attempts stays under 200 ms.

### M12 — Settings and export

Build Settings: playback rate, palette, renderer picker (hidden with one renderer),
role-label toggle, iCloud sync explanation, data export, erase all progress, and an About
screen showing app version and schema fingerprint.

*Acceptance:* JSON and CSV exports contain every record with every field and open correctly in
a spreadsheet; erase-all requires destructive confirmation and leaves the store empty and
functional; the iCloud explanation directs the user to the system Settings path rather than
offering an in-app toggle.

### M13 — Accessibility and onboarding

VoiceOver over the animation reading generated per-step descriptions; Dynamic Type through
`AX5` on every screen; Reduce Motion honored; Increase Contrast honored; all palettes verified
for team distinguishability without color; haptics on answer feedback; a three-screen
onboarding flow ending in a guided first Learn session.

*Acceptance:* full VoiceOver navigation of Play and Learn Mode without a trap or an unlabeled
control; no clipped or truncated text at `AX5`; no accessibility description contains the
tactic name or any spoiler-bearing field; onboarding shows once and can be replayed from
Settings.

### M14 — Hardening

*Acceptance:* cold launch to interactive under 1.0 s on device with a full-size pack; steady
memory under 150 MB with a 3,000-scenario pack; sustained 60 fps during playback; zero
compiler warnings; zero strict-concurrency diagnostics; no networking code anywhere in the
project; no third-party dependency linked into the app binary; all non-goals from section 2
absent.

---

## Appendix A — Canonical zone geometry

Normalized space: `x` from the attacking team's left touchline (0) to its right touchline (1);
`y` from the attacking team's own goal line (0) to the goal it attacks (1).

**Bands.** DEF `y ∈ [0, 1/3]`, MID `y ∈ [1/3, 2/3]`, ATT `y ∈ [2/3, 1]`.

**Lanes.** Eleven equal lanes of width `1/11`, indexed left to right:

| Lane | x range | DEF | MID | ATT |
|---|---|---|---|---|
| 0 | [0/11, 1/11] | `DEF_LEFT_CORNER` | `MID_LEFT_TOUCHLINE` | `ATT_LEFT_CORNER` |
| 1 | [1/11, 2/11] | `DEF_LEFT_WING` | `MID_LEFT_WING` | `ATT_LEFT_WING` |
| 2 | [2/11, 3/11] | `DEF_LEFT_HALFSPACE` | `MID_LEFT_HALFSPACE` | `ATT_LEFT_HALFSPACE` |
| 3 | [3/11, 4/11] | `DEF_LEFT_CHANNEL` | `MID_LEFT_CHANNEL` | `ATT_LEFT_CHANNEL` |
| 4 | [4/11, 5/11] | `DEF_CENTER_LEFT` | `MID_CENTER_LEFT` | `ATT_ZONE14_LEFT` |
| 5 | [5/11, 6/11] | `DEF_CENTER` | `MID_CENTER` | `ATT_ZONE14` |
| 6 | [6/11, 7/11] | `DEF_CENTER_RIGHT` | `MID_CENTER_RIGHT` | `ATT_ZONE14_RIGHT` |
| 7 | [7/11, 8/11] | `DEF_RIGHT_CHANNEL` | `MID_RIGHT_CHANNEL` | `ATT_RIGHT_CHANNEL` |
| 8 | [8/11, 9/11] | `DEF_RIGHT_HALFSPACE` | `MID_RIGHT_HALFSPACE` | `ATT_RIGHT_HALFSPACE` |
| 9 | [9/11, 10/11] | `DEF_RIGHT_WING` | `MID_RIGHT_WING` | `ATT_RIGHT_WING` |
| 10 | [10/11, 1] | `DEF_RIGHT_CORNER` | `MID_RIGHT_TOUCHLINE` | `ATT_RIGHT_CORNER` |

`CORNER` denotes the outermost lane of its third — a full-depth rectangle, not a special
corner-shaped region.

**Box overlay** (attacking third only; overlays the ATT lanes rather than replacing them).
Unlike the lane grid, these follow the Laws of the Game, because the penalty area and six-yard
box are fixed real dimensions that do not scale with pitch size.

| Zone | x range | y range | Decimal x | Decimal y |
|---|---|---|---|---|
| `LEFT_BOX` | [173/850, 621/1700] | [59/70, 1] | [0.2035294, 0.3652941] | [0.8428571, 1.0] |
| `CENTER_BOX` | [621/1700, 1079/1700] | [59/70, 1] | [0.3652941, 0.6347059] | [0.8428571, 1.0] |
| `RIGHT_BOX` | [1079/1700, 677/850] | [59/70, 1] | [0.6347059, 0.7964706] | [0.8428571, 1.0] |
| `SIX_YARD_BOX` | [621/1700, 1079/1700] | [199/210, 1] | [0.3652941, 0.6347059] | [0.9476190, 1.0] |
| `PENALTY_SPOT` | point x = 1/2 | point y = 94/105 | 0.5 | 0.8952381 |

The penalty area is `x ∈ [173/850, 677/850]`, `y ∈ [59/70, 1]` — 40.32 wide by 16.5 deep. The
three lateral box zones follow the standard **near-post / central / far-post** division: the
central zone is the six-yard-box channel projected out to the penalty-area line, and the
flanking zones are what remains. They partition the penalty area with no gap and no overlap,
and they are **not equal thirds** — flanking zones are 11 wide, the central zone 18.32, a ratio
of roughly **1 : 1.67 : 1**.

`CENTER_BOX` and `SIX_YARD_BOX` deliberately share lateral bounds and differ only in depth:
the six-yard box is the near portion of the same central channel. Implement `SIX_YARD_BOX` by
reusing `CENTER_BOX`'s x range so the two cannot drift apart.

There is no defensive-third box overlay.

**Metric conversion.** Canonical pitch 105 length units (y) × 68 (x). Distances expressed as a
fraction of pitch length convert as `d × 105`. Goal mouths are 7.32 wide, centred at `x = 0.5`,
posts at `x = 0.5 ± 3.66/68`.

This appendix is a transcription of the `zone` enum's description in `scenario_new.json` for
convenience while implementing `PitchGeometry`. **The schema is authoritative.** If the two ever
disagree, the schema wins and this appendix is the thing to correct.

---

## Appendix B — Interpretation Register

Every scenario-semantic question this project once had to decide for itself is now answered
normatively in `scenario_new.json`: goal-side direction for `MARK` and `TRACK_RUNNER`, the ball's
destination for each `shot_result` and `cross_result`, pass aiming when the receiver moves,
metric space and goal geometry, the permission to discard `play_direction`, the prohibition on
collision avoidance, and the spoiler classification of every field including `metadata.title`.
Section 6 restates those rules for the implementer's convenience; **the schema is authoritative
in every case**, and a disagreement between section 6 and the schema is a bug in section 6.

Two decisions remain genuinely outside the schema's scope, because they are product judgments
rather than facts about a scenario. Both live in one place in the code and are expected to be
tuned.

1. **Learn Mode step definition.** A step is the interval between consecutive unique
   `start_time` values across the scenario's events. The schema defines timing exactly but has
   no opinion on stepping granularity, since that is a property of a study interface rather
   than of the play. Defined in `ScenarioTimeline.breakpoints` and used identically by the
   scrub bar, the step controls, and the explanation panel.
2. **Statistical tuning constants.** The EWMA half-life of 15 attempts, the confidence
   threshold of 5, and every recommendation threshold in section 9.5 are judgments about
   pedagogy, not schema facts. They live in `RecommendationTuning` and nowhere else.

**One schema correction was made while writing this document**, and it is recorded here so it
is not silently re-introduced. The box-overlay geometry was internally inconsistent: the prose
claimed three equal thirds while the arithmetic produced a 1:2:1 ratio, and the underlying
penalty-area and six-yard-box dimensions were yards-treated-as-metres approximations that made
the six-yard box implausibly wide relative to the penalty area.

The resolution was to take the geometry from the Laws of the Game — penalty area 40.32 × 16.5,
six-yard box 18.32 × 5.5, on the canonical 105 × 68 pitch — and to divide the box laterally the
way football actually does, near post / central / far post, with the central zone being the
six-yard-box channel projected out to the penalty-area line. The goal mouth and penalty spot
were already real and are unchanged. Appendix A and the M3 acceptance criteria assert these
dimensions, so a regression fails the build.

**One naming caveat left deliberately unresolved.** In football analysis, "Zone 14" means
specifically the central area *immediately outside* the penalty area. The schema's
`ATT_ZONE14` is a full-depth lane of the attacking third, so as a rectangle it extends into the
box. This is a naming mismatch, not a geometric ambiguity — the schema states the resolution
rule, and an author who means inside the box says `CENTER_BOX`. Raise it as a schema question
only if corpus authoring proves it confusing; fixing it would require splitting the lane, which
is a structural change.

---

## Appendix C — Instructions for writing the tactic primers

Write one primer per case of the schema's `tactic` enum. Read the enum from
`scenario_new.json` and write exactly one file per case — do not work from a hardcoded list,
and do not assume the count.

**Location and naming.** `ArmchairFCKit/Sources/Primers/Resources/<RAW_VALUE>.md`, where
`<RAW_VALUE>` is the enum's raw value verbatim — for example `THIRD_MAN_RUN.md`. The loader
resolves a primer by raw value, and a coverage test asserts one exists for every case. Declare
the directory as a package resource.

**Audience.** Someone with essentially no football background who may never have watched a
full match. Assume no vocabulary. Introduce any term you use — halfspace, overload, weak side,
line of engagement — in plain language the first time it appears.

**Length.** Four to six paragraphs, roughly 400–700 words. Long enough to actually teach;
short enough to read before a study session.

**Structure.** Use these five headings in this order, identically in every file:

```markdown
# <Human-readable tactic name>

## What it is
## Why it works
## What to watch for
## What it is not
## How it gets harder
```

- **What it is** — a plain description of the pattern. One concrete mental picture.
- **Why it works** — the underlying principle. What problem it creates for the defense.
- **What to watch for** — the specific visual cues that identify it. This is the most important
  section; it is what the user carries into Play Mode. Frame cues as things to look at, in the
  order they become visible.
- **What it is not** — the tactics it is most often confused with, and the precise distinction.
  Name them. This section directly serves the confusion-pair recommendations.
- **How it gets harder** — how the pattern presents at higher difficulty levels: disguised,
  partial, embedded in a longer sequence, or executed by unexpected players.

**Constraints.**

- Plain Markdown. Headings, paragraphs, bold, and bullet lists only. No images, no HTML, no
  front matter, no links.
- Describe patterns using the schema's own spatial vocabulary — halfspace, channel, wing,
  zone 14 — since that is the vocabulary the animations render and the user will see.
- Do not reference specific real players, clubs, or matches.
- Do not reference specific scenario files or IDs. Primers are about the concept; per-scenario
  explanations cover the instances.
- Keep the tone instructive and plain. No exclamation marks, no motivational filler.

**Relationship to per-scenario content.** Primers supplement per-scenario explanations and
never replace or abbreviate them. Every `tactical_explanation`, `advantages_created` entry,
`attacking_goal`, `success_condition`, `expected_outcomes` entry, and `coaching_notes` entry in
a scenario is displayed in full in Learn Mode regardless of the primer. If the primers were
removed entirely, no per-scenario content would be lost.

---

## Appendix D — Conventions

- **Access control.** Package APIs are `public` only where crossed by another target; `internal`
  otherwise. Nothing is `open`.
- **Errors.** Each target defines one `Error` enum with `LocalizedError`. No `fatalError` in
  shipping code paths; `preconditionFailure` is acceptable only for invariants the build-time
  validator already guarantees.
- **Force unwrapping.** Permitted only in `declarationIndex` (where `allCases` membership is
  guaranteed) and in tests.
- **Logging.** `os.Logger` with subsystem `com.by-sbs.armchairfc` and one category per target.
  No `print` outside tool executables.
- **Strings.** Every user-facing string in a String Catalog from the first screen. English only.
- **Tests.** Swift Testing (`import Testing`) for new tests. Every package target has a test
  target. Scenario fixtures live in `Tests/Fixtures/` as YAML, are **supplied by the project
  owner**, and are packed by a test helper. The agent never authors or edits them; see M2.
- **Generated files.** Every file in `ScenarioSchema` begins with
  `// Generated by SchemaGen from scenario_new.json. Do not edit.` and is excluded from
  formatting and linting.
- **Documentation.** Every `public` symbol carries a doc comment. Generated types inherit their
  comments from the schema's `title` and `description`.

---

## Appendix E — Definition of done

The project is complete when all of the following hold:

1. Every milestone's acceptance criteria pass.
2. `Tools/generate.sh` regenerates types and pack, and the drift test passes immediately after.
3. Deliberately renaming one enum case in the schema and regenerating produces compile errors
   at every dependent site and **no silent behavior change anywhere**. This is the single most
   important verification in the project; perform it explicitly before declaring completion.
4. No scenario data is read as a dictionary anywhere in the codebase.
5. No `switch` over a schema enum contains a `default:` clause.
6. Yams is not linked into the app binary.
7. The app contains no networking code.
8. Cold launch is under one second with a full-size pack.
