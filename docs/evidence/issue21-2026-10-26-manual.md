# Issue #21: manual dashboard observations

Source: the user's manual observations from 26 October 2026, supplied during
commit preparation. The [dashboard screenshot](issue21_after_R1_openning_failure.png)
records the failed-opening state. The subsequent command results below are
user-reported observations, separate from the earlier automated MQTT/historian
trials in [the evidence archive](issue21-2026-10-26.zip).

- Failed-opening test: R1 was CLOSED/tripped, F1 was OPEN/tripped, downstream
  equipment was de-energized, and Plant showed ONLINE.
- R1 feedback was `2026-10-26T21:02:17.008Z`; F1 feedback was
  `2026-10-26T21:02:17.165Z`. These timestamps do not independently establish
  protection delays.
- Selecting NORMAL changed neither breaker positions nor trip latches.
- RESET cleared each latch without moving either breaker: R1 remained CLOSED
  and F1 remained OPEN.
- Closing F1 restored supply and valid measurements, with both breakers CLOSED
  and clear.

The implementation and regression-test files still match the hashes of the
recorded passing run. Reused results: 4 new regression cases passed after
initially failing, 23 focused tests passed, the full Python suite passed
81 tests, and Compose validation/build and three regular-simulator trials
passed without restart. The historian comparison matched all 76 observed
IED events. That run used the working tree containing the uncommitted #18 view;
its identity and results are retained in the archive.

These observations supply the manual dashboard evidence for this correction.
They do not accept #18 or its remaining checks. General solver convergence and
truthful failure/restart recovery remain unresolved under
[#20](https://github.com/leomedeles/jspX/issues/20).
