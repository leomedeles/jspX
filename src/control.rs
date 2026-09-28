//! Transport-independent scan, protection, and physical operation feedback.
use crate::plant::{Plant, Scenario, Telemetry};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const SCAN_MS: u64 = 50;
pub const BREAKERS: [&str; 2] = ["BRK_F1", "BRK_R1"];

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Action {
    Open,
    Close,
    Reset,
}

#[derive(Clone, Debug)]
pub enum Intent {
    Breaker {
        breaker: String,
        action: Action,
        request_id: String,
    },
    Scenario {
        scenario: Scenario,
        request_id: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BreakerStatus {
    pub breaker: String,
    pub state: String,
    pub tripped: bool,
    pub undervoltage_alarm: bool,
    pub trip_reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Event {
    pub ts: String,
    pub event_id: String,
    pub run_id: String,
    pub event: String,
    pub ied: Option<String>,
    pub breaker: Option<String>,
    pub scan_monotonic_s: f64,
    pub position: Option<String>,
    pub tripped: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub requested_state: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub actual_state: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub success: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cause: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scenario: Option<Scenario>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Snapshot {
    pub run_id: String,
    pub seq: u64,
    pub ts: String,
    pub scenario: Scenario,
    pub breakers: Vec<BreakerStatus>,
    pub telemetry: Telemetry,
}

#[derive(Clone, Debug)]
pub struct ScanResult {
    pub snapshot: Snapshot,
    pub events: Vec<Event>,
    pub statuses_changed: bool,
    pub telemetry_due: bool,
}

#[derive(Clone, Debug, Default)]
struct Controller {
    tripped: bool,
    trip_reason: Option<String>,
    undervoltage_alarm: bool,
    started_at_ms: Option<u64>,
}

#[derive(Clone, Debug)]
struct EventDraft {
    breaker: Option<usize>,
    kind: &'static str,
    requested: Option<&'static str>,
    actual: Option<&'static str>,
    success: Option<bool>,
    cause: Option<&'static str>,
    request_id: Option<String>,
    scenario: Option<Scenario>,
}

impl EventDraft {
    fn simple(breaker: usize, kind: &'static str) -> Self {
        Self {
            breaker: Some(breaker),
            kind,
            requested: None,
            actual: None,
            success: None,
            cause: None,
            request_id: None,
            scenario: None,
        }
    }
}

pub struct Simulator {
    pub plant: Plant,
    controllers: [Controller; 2],
    pub run_id: String,
    pub sequence: u64,
    pub scan_seq: u64,
    pub latest: Option<Snapshot>,
}

impl Default for Simulator {
    fn default() -> Self {
        Self {
            plant: Plant::default(),
            controllers: [Controller::default(), Controller::default()],
            run_id: Uuid::new_v4().to_string(),
            sequence: 0,
            scan_seq: 0,
            latest: None,
        }
    }
}

impl Simulator {
    pub fn status(&self, i: usize) -> BreakerStatus {
        let closed = self.plant.position(BREAKERS[i]).unwrap();
        BreakerStatus {
            breaker: BREAKERS[i].into(),
            state: if closed { "CLOSED" } else { "OPEN" }.into(),
            tripped: self.controllers[i].tripped,
            undervoltage_alarm: self.controllers[i].undervoltage_alarm,
            trip_reason: self.controllers[i].trip_reason.clone(),
        }
    }
    fn draft_request(
        i: usize,
        state: &'static str,
        cause: &'static str,
        request_id: Option<String>,
    ) -> EventDraft {
        EventDraft {
            breaker: Some(i),
            kind: "OPERATION_REQUEST",
            requested: Some(state),
            actual: None,
            success: None,
            cause: Some(cause),
            request_id,
            scenario: None,
        }
    }
    fn attempt(
        &mut self,
        i: usize,
        closed: bool,
        cause: &'static str,
        request_id: Option<String>,
        events: &mut Vec<EventDraft>,
    ) {
        let actual = self.plant.attempt(BREAKERS[i], closed).unwrap();
        events.push(EventDraft {
            breaker: Some(i),
            kind: "POSITION_FEEDBACK",
            requested: Some(if closed { "CLOSED" } else { "OPEN" }),
            actual: Some(if actual { "CLOSED" } else { "OPEN" }),
            success: Some(actual == closed),
            cause: Some(cause),
            request_id,
            scenario: None,
        });
    }
    fn current(telemetry: &Telemetry, line_name: &str) -> Option<f64> {
        telemetry
            .lines
            .iter()
            .filter(|l| l.name == line_name)
            .filter_map(|l| l.i_ka)
            .reduce(f64::max)
    }
    fn voltage(telemetry: &Telemetry, bus_name: &str) -> Option<f64> {
        telemetry
            .buses
            .iter()
            .find(|b| b.name == bus_name)
            .and_then(|b| b.vm_pu)
    }

    pub fn scan(
        &mut self,
        now_ms: u64,
        ts: String,
        intent: Option<Intent>,
        telemetry_due: bool,
    ) -> ScanResult {
        let previous = [self.status(0), self.status(1)];
        let mut drafts = Vec::new();
        if self.scan_seq == 0 {
            drafts.push(EventDraft {
                breaker: None,
                kind: "RUN_STARTED",
                requested: None,
                actual: None,
                success: None,
                cause: None,
                request_id: None,
                scenario: Some(Scenario::Normal),
            });
        }
        if let Some(intent) = intent {
            match intent {
                Intent::Scenario {
                    scenario,
                    request_id,
                } => {
                    self.plant.set_scenario(scenario);
                    drafts.push(EventDraft {
                        breaker: None,
                        kind: "SCENARIO_SET",
                        requested: None,
                        actual: None,
                        success: Some(true),
                        cause: Some("test_harness"),
                        request_id: Some(request_id),
                        scenario: Some(scenario),
                    });
                }
                Intent::Breaker {
                    breaker,
                    action,
                    request_id,
                } => {
                    if let Some(i) = BREAKERS.iter().position(|x| *x == breaker) {
                        match action {
                            Action::Open => {
                                if self.controllers[i].started_at_ms.take().is_some() {
                                    drafts.push(EventDraft::simple(i, "TIMING_CANCELLED"));
                                }
                                drafts.push(Self::draft_request(
                                    i,
                                    "OPEN",
                                    "operator",
                                    Some(request_id.clone()),
                                ));
                                self.attempt(i, false, "operator", Some(request_id), &mut drafts);
                            }
                            Action::Close => {
                                if self.controllers[i].tripped {
                                    let mut e = EventDraft::simple(i, "CLOSE_REJECTED");
                                    e.cause = Some("trip_latch");
                                    e.request_id = Some(request_id);
                                    drafts.push(e);
                                } else {
                                    drafts.push(Self::draft_request(
                                        i,
                                        "CLOSED",
                                        "operator",
                                        Some(request_id.clone()),
                                    ));
                                    self.attempt(
                                        i,
                                        true,
                                        "operator",
                                        Some(request_id),
                                        &mut drafts,
                                    );
                                }
                            }
                            Action::Reset => {
                                self.controllers[i].tripped = false;
                                self.controllers[i].trip_reason = None;
                                self.controllers[i].started_at_ms = None;
                                let mut e = EventDraft::simple(i, "RESET");
                                e.request_id = Some(request_id);
                                drafts.push(e);
                            }
                        }
                    }
                }
            }
        }
        if telemetry_due {
            self.plant.vary_load();
        }
        let mut telemetry = self
            .plant
            .solve()
            .unwrap_or_else(|_| self.plant.unknown_telemetry());
        if telemetry
            .buses
            .iter()
            .all(|b| b.quality != crate::plant::Quality::Unknown)
        {
            let mut trip_indices = Vec::new();
            for (i, breaker) in BREAKERS.iter().enumerate() {
                let voltage = if i == 0 {
                    Self::voltage(&telemetry, "BUS_MV_SOURCE")
                } else {
                    None
                };
                if let Some(voltage) = voltage {
                    if !self.controllers[i].undervoltage_alarm && voltage < 0.92 {
                        self.controllers[i].undervoltage_alarm = true;
                        drafts.push(EventDraft::simple(i, "ALARM_ASSERTED"));
                    } else if self.controllers[i].undervoltage_alarm && voltage >= 0.94 {
                        self.controllers[i].undervoltage_alarm = false;
                        drafts.push(EventDraft::simple(i, "ALARM_CLEARED"));
                    }
                }
                let current = Self::current(
                    &telemetry,
                    if i == 0 {
                        "L1_FEEDER_HEAD"
                    } else {
                        "L2_FEEDER_TAIL"
                    },
                );
                let enabled = self.plant.position(breaker).unwrap() && !self.controllers[i].tripped;
                if !enabled || current.is_none_or(|v| v < 0.20) {
                    if self.controllers[i].started_at_ms.take().is_some() {
                        drafts.push(EventDraft::simple(i, "TIMING_CANCELLED"));
                    }
                    continue;
                }
                if self.controllers[i].started_at_ms.is_none() {
                    self.controllers[i].started_at_ms = Some(now_ms);
                    drafts.push(EventDraft::simple(i, "PICKUP"));
                    drafts.push(EventDraft::simple(i, "TIMING_STARTED"));
                }
                let delay = if i == 0 { 300 } else { 100 };
                if now_ms.saturating_sub(self.controllers[i].started_at_ms.unwrap()) >= delay {
                    self.controllers[i].tripped = true;
                    self.controllers[i].trip_reason = Some("overcurrent".into());
                    self.controllers[i].started_at_ms = None;
                    drafts.push(EventDraft::simple(i, "TRIP_REQUEST"));
                    trip_indices.push(i);
                }
            }
            if !trip_indices.is_empty() {
                for i in trip_indices {
                    self.attempt(i, false, "protection", None, &mut drafts);
                }
                telemetry = self
                    .plant
                    .solve()
                    .unwrap_or_else(|_| self.plant.unknown_telemetry());
            }
        }
        telemetry.ts = ts.clone();
        self.scan_seq += 1;
        let breakers = vec![self.status(0), self.status(1)];
        let statuses_changed =
            breakers[0] != previous[0] || breakers[1] != previous[1] || self.scan_seq == 1;
        let events = drafts
            .into_iter()
            .map(|d| {
                self.sequence += 1;
                let i = d.breaker;
                Event {
                    ts: ts.clone(),
                    event_id: format!("{}:{}", self.run_id, self.sequence),
                    run_id: self.run_id.clone(),
                    event: d.kind.into(),
                    ied: i.map(|i| if i == 0 { "IED_F1" } else { "IED_R1" }.into()),
                    breaker: i.map(|i| BREAKERS[i].into()),
                    scan_monotonic_s: now_ms as f64 / 1000.0,
                    position: i.map(|i| self.status(i).state),
                    tripped: i.map(|i| self.controllers[i].tripped),
                    requested_state: d.requested.map(str::to_string),
                    actual_state: d.actual.map(str::to_string),
                    success: d.success,
                    cause: d.cause.map(str::to_string),
                    request_id: d.request_id,
                    scenario: d.scenario,
                }
            })
            .collect();
        let snapshot = Snapshot {
            run_id: self.run_id.clone(),
            seq: self.scan_seq,
            ts,
            scenario: self.plant.scenario,
            breakers,
            telemetry,
        };
        self.latest = Some(snapshot.clone());
        ScanResult {
            snapshot,
            events,
            statuses_changed,
            telemetry_due,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn scan(sim: &mut Simulator, ms: u64, intent: Option<Intent>) -> ScanResult {
        sim.scan(ms, format!("2026-01-01T00:00:00.{ms:03}Z"), intent, false)
    }
    fn scenario(s: Scenario) -> Option<Intent> {
        Some(Intent::Scenario {
            scenario: s,
            request_id: "test".into(),
        })
    }
    fn command(b: &str, a: Action) -> Option<Intent> {
        Some(Intent::Breaker {
            breaker: b.into(),
            action: a,
            request_id: "test".into(),
        })
    }
    #[test]
    fn selective_trip_and_reset() {
        let mut sim = Simulator::default();
        scan(&mut sim, 0, scenario(Scenario::TailOvercurrentTest));
        scan(&mut sim, 50, None);
        let trip = scan(&mut sim, 100, None);
        assert_eq!(trip.snapshot.breakers[1].state, "OPEN");
        assert!(trip.snapshot.breakers[1].tripped);
        assert_eq!(trip.snapshot.breakers[0].state, "CLOSED");
        assert!(
            trip.events
                .iter()
                .any(|e| e.event == "TRIP_REQUEST" && e.breaker.as_deref() == Some("BRK_R1"))
        );
        let cancel = scan(&mut sim, 150, None);
        assert!(
            cancel
                .events
                .iter()
                .any(|e| e.event == "TIMING_CANCELLED" && e.breaker.as_deref() == Some("BRK_F1"))
        );
        let reject = scan(&mut sim, 200, command("BRK_R1", Action::Close));
        assert!(reject.events.iter().any(|e| e.event == "CLOSE_REJECTED"));
        scan(&mut sim, 250, scenario(Scenario::Normal));
        let reset = scan(&mut sim, 300, command("BRK_R1", Action::Reset));
        assert_eq!(reset.snapshot.breakers[1].state, "OPEN");
        assert!(!reset.snapshot.breakers[1].tripped);
        let close = scan(&mut sim, 350, command("BRK_R1", Action::Close));
        assert_eq!(close.snapshot.breakers[1].state, "CLOSED");
    }
    #[test]
    fn failed_r1_operation_has_closed_feedback_then_f1_backup() {
        let mut sim = Simulator::default();
        scan(&mut sim, 0, scenario(Scenario::R1OpeningFailureTest));
        scan(&mut sim, 50, None);
        let primary = scan(&mut sim, 100, None);
        assert_eq!(primary.snapshot.breakers[1].state, "CLOSED");
        assert!(primary.snapshot.breakers[1].tripped);
        assert!(primary.events.iter().any(|e| e.event == "POSITION_FEEDBACK"
            && e.breaker.as_deref() == Some("BRK_R1")
            && e.success == Some(false)
            && e.actual_state.as_deref() == Some("CLOSED")));
        for ms in [150, 200, 250] {
            scan(&mut sim, ms, None);
        }
        let backup = scan(&mut sim, 300, None);
        assert_eq!(backup.snapshot.breakers[0].state, "OPEN");
        assert!(backup.snapshot.breakers[0].tripped);
        assert_eq!(backup.snapshot.breakers[1].state, "CLOSED");
        scan(&mut sim, 350, scenario(Scenario::Normal));
        assert!(sim.controllers[1].tripped);
        assert!(!sim.plant.f1_closed);
    }
    #[test]
    fn f1_and_r1_isolation_and_low_voltage_alarm() {
        let mut sim = Simulator::default();
        let r1 = scan(&mut sim, 0, command("BRK_R1", Action::Open));
        assert!(r1.snapshot.telemetry.buses[2].energized);
        assert!(!r1.snapshot.telemetry.buses[3].energized);
        scan(&mut sim, 50, command("BRK_R1", Action::Close));
        let f1 = scan(&mut sim, 100, command("BRK_F1", Action::Open));
        assert!(!f1.snapshot.telemetry.buses[2].energized);
        scan(&mut sim, 150, command("BRK_F1", Action::Close));
        let low = scan(&mut sim, 200, scenario(Scenario::LowSourceVoltage));
        assert!(low.snapshot.breakers[0].undervoltage_alarm);
        assert!(!low.snapshot.breakers[0].tripped);
        let normal = scan(&mut sim, 250, scenario(Scenario::Normal));
        assert!(!normal.snapshot.breakers[0].undervoltage_alarm);
    }
}
