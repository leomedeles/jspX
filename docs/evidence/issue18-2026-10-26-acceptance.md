# Issue #18 acceptance record

Recorded 26 October 2026 for [#18](https://github.com/leomedeles/jspX/issues/18)
on `feat/operator-feeder-view`, with #21 committed as
`edf1d68103946f15c6534b06d9fede2c3619b5fa` and the tested #18 changes still
uncommitted when inspected. The commit containing this record includes those
flow/test contents. [The identity manifest](issue18-2026-10-26-identity.json)
records their SHA-256 hashes, Git blob identities, and preserved screenshot hashes.

## Evidence and attribution

The manual results below are **user-reported observations of the regular
dashboard and regular Compose simulator**. They are not an automated browser
run. The three available #18 screenshots were inspected and are preserved
without alteration. Results without a screenshot remain user-reported; no
additional screenshots, exact command times, measured timeout interval, or
protection delays are claimed.

The [#21 manual record](issue21-2026-10-26-manual.md) and
[failed-opening screenshot](issue21_after_R1_openning_failure.png) already
establish the failed-opening dashboard result, NORMAL without movement/latch
clearing, RESET without movement, and restoration by closing F1. They are reused.
The feedback timestamps in that record do not independently establish
protection delays.

The [#21 archive](issue21-2026-10-26.zip) contains the prior 81-test passing run,
Compose validation/build and service observations, three regular-simulator
failed-opening MQTT trials without restart, and the comparison matching all
76 observed IED events to historian records. Its `verification.json` hashes
match the current flow, affected tests, recorded Python runtime sources, and
recorded Compose/dependency files. Those checks are reused, not rerun.

The display tests execute real solved plant cases in process and isolated
Node-RED functions/component logic. They support UNKNOWN, missing/null/zero,
freshness, command intent, and feedback formatting behavior. They are not
regular-dashboard end-to-end runs or evidence from a replacement simulator
operating the regular control path. No replacement-runtime result substitutes
for the regular workflows in the acceptance table.

## Reproducible starting states and reported results

For reproduction, start the electrical exercises with NORMAL inputs, F1/R1
CLOSED and clear, Plant ONLINE, and fresh valid measurements. These are
reproduction conditions, not a separately captured session log. Use the
dashboard's breaker controls and the existing `cmd/sim/scenario/set` interface;
scenario injection remains outside the HMI.

- **R1 isolation/restoration:** OPEN R1 from normal supply, then CLOSE it. The
  user confirmed that the remote source-side bus stayed energized while SS1
  lost and then recovered supply. The
  [R1-open screenshot](issue18_R1_Open.png) shows F1 CLOSED/clear, R1 OPEN/clear,
  the energized remote bus, and downstream de-energization/unavailable voltages.
- **Selective trip and interlock:** Select TAIL_OVERCURRENT_TEST from normal
  supply. The user confirmed R1 OPEN/tripped, F1 CLOSED, and SS1 de-energized;
  the [selective-trip screenshot](issue18_TAIL_OVERCURRENT_TEST.png) supports
  that state. The user reported that R1 CLOSE was rejected while latched.
  After NORMAL and RESET, R1 remained OPEN, its latch cleared, and the
  overcurrent reason disappeared. Explicit CLOSE restored supply.
- **Low source voltage:** Select LOW_SOURCE_VOLTAGE from normal supply. The
  user reported F1 UV ALARM without a trip or opening; NORMAL cleared the alarm.
- **Telemetry loss/recovery:** Pause `sim` from normal supply. The user reported
  OFFLINE, suppressed stale measurements, Last known breaker feedback, and
  disabled controls. The [OFFLINE screenshot](issue18_stopped_sim.png) supports
  those display states. Unpausing restored ONLINE, fresh measurements, and
  controls without changing positions/latches; F1 showed UV NORMAL.

No new MQTT/database capture establishes a `CLOSE_REJECTED` event for the user's
latest dashboard click. This record claims the user-observed rejection only.
Separately, #21's earlier regular-runtime archive contains 12 CLOSE_REJECTED
events among the 76 historian-matched events; those are existing backend
evidence and are not attributed to this later manual exercise.

## Acceptance coverage

Criterion numbers follow the Acceptance section of issue #18.

| Criterion | Supporting evidence and execution mode | Remaining gap |
| --- | --- | --- |
| 1. Normal supply, both breakers closed, path to SS1 | #21 regular-dashboard manual restoration: both CLOSED/clear, supply and valid measurements restored; normal solved-display test | None |
| 2. R1 isolation preserves its source-side connection; closing restores SS1 | User-reported regular-dashboard isolation/restoration and preserved R1-open screenshot; solved-display test | None |
| 3. F1 isolation preserves upstream supply and isolates remote/SS1 | #21 regular-dashboard failed-opening screenshot shows Grid/T1/MV source energized with F1 OPEN and remote/SS1 de-energized; solved-display test | None |
| 4. Selective trip: R1 OPEN/tripped, F1 CLOSED | User-reported regular-dashboard result and preserved selective-trip screenshot; #21 regular MQTT result and solved-display test | None |
| 5. Failed R1 opening: R1 CLOSED/tripped, F1 OPEN/tripped, downstream lost | #21 regular-dashboard manual record/screenshot and three regular Compose/MQTT/historian trials | None |
| 6. CLOSE rejection/RESET preserve actual positions; cleared reasons disappear | User-reported regular-dashboard rejected CLOSE, RESET leaving R1 OPEN/clear, removed overcurrent reason, and explicit restoration; #21 RESET evidence and earlier captured rejection events; isolated component tests | None; no new event capture is claimed |
| 7. UV alarm distinct from trip; UNKNOWN/OFFLINE cannot look healthy | User-reported regular-dashboard UV assert/clear without trip/opening, pause/unpause observations and OFFLINE screenshot; isolated UNKNOWN/status-validity/freshness tests | None; malformed-input UNKNOWN behavior is isolated test evidence |
| 8. Unavailable is not fabricated zero; stale values not current | R1-open and #21 failed-opening screenshots distinguish unavailable quantities from finite zero; #21 strict-JSON/quality evidence; user-reported pause/recovery and OFFLINE screenshot; isolated null/nonfinite/zero tests | None |
| 9. Relevant checks/DoD, reproducible starts and tested identity | Reused 81-test pass, Compose and regular MQTT/historian evidence; starting conditions above, current content-hash match and identity manifest; README operation/interface updates | None for this item |

## Scope and limitations

Issue #18's acceptance coverage is complete on the evidence above. The manual
observations complement the earlier automated/integration evidence; they do not
provide measured protection delays or exact telemetry-loss timing. The nominal
five-second freshness policy is covered by the existing isolated tests.

The active flow remains `nodered/data/flows.json`; canonical MQTT intent and
authoritative physical feedback are preserved. Protection interlocks remain
in the IED/controller. The change adds no plant/solver/protection settings,
dependency, restart policy, or #19 equipment panels. Documentation and evidence
are the only additions made during this acceptance preparation.

[#20](https://github.com/leomedeles/jspX/issues/20) remains unresolved: this
acceptance does not establish general solver convergence or truthful numerical
failure/restart recovery. Sprint 8 combined acceptance, #19, issue checkbox/board
updates, pushing, merging, and release work are separate; none is claimed here.
