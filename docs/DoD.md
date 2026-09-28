# Definition of Done

This is the shared completion standard for a selected backlog item or a coherent requested change. It does not apply separately to every commit. The backlog holds feature-specific acceptance criteria and sprint evidence.

A change is done when all applicable conditions below are met. If required verification could not be performed, record the gap and leave the change awaiting verification.

## Behavior and scope

- The requested behavior and any item-specific acceptance criteria have been demonstrated, not merely implemented.
- Existing control behavior is preserved. Where affected, breaker commands and protection decisions agree with physical switch state, solved topology, telemetry, and operator status.
- The change contains no unrelated feature or unapproved scope expansion.

## Verification

- For Python behavior changes, relevant deterministic tests cover the changed behavior and important failure or interlock cases; `python -m pytest -q` passes locally.
- For Compose or service-configuration changes, `docker compose config --quiet` passes.
- For changes to an interaction across MQTT, Node-RED, InfluxDB, or Grafana, the affected path has been checked in the running stack. Confirm the observable result, not only that containers started.
- Record the commands run, results observed, and any checks that could not be performed. Do not claim a check passed from an unobserved result.

## Documentation and safety

- Update the README when current behavior, interfaces, or operating steps change. Update the backlog item and its acceptance evidence when planned work is completed. Update the changelog when preparing a release.
- Do not commit secrets or accidentally widen development service exposure. Preserve named-volume data during verification.
- For documentation-only changes, check the affected statements against their sources and inspect the diff. Runtime tests are not required when behavior and configuration are unchanged.

Release closeout—including integration checks, release notes, tag, and publication—is a separate decision, not a condition for every change.
