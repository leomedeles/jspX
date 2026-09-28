//! Fixed, balanced five-bus reference feeder. The branch equivalents below are
//! pandapower 3.1.2's T-model conversions on a 100 MVA base. Their source
//! parameters are documented in README and frozen in fixtures/.
use nalgebra::{DMatrix, DVector};
use num_complex::Complex64;
use serde::{Deserialize, Serialize};

pub const BUS_NAMES: [&str; 5] = [
    "GRID_110KV",
    "BUS_MV_SOURCE",
    "BUS_R1_REMOTE",
    "BUS_SS1_MV",
    "BUS_SS1_LV",
];
pub const NOMINAL_KV: [f64; 5] = [110.0, 20.0, 20.0, 20.0, 0.4];
pub const LINE_NAMES: [&str; 2] = ["L1_FEEDER_HEAD", "L2_FEEDER_TAIL"];
pub const TRAFO_NAMES: [&str; 2] = ["T1_PRIMARY", "T2_SS1"];
const BASE_MVA: f64 = 100.0;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Quality {
    Good,
    NotEnergized,
    #[default]
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Scenario {
    Normal,
    TailOvercurrentTest,
    R1OpeningFailureTest,
    LowSourceVoltage,
}

impl Scenario {
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "NORMAL" => Some(Self::Normal),
            "TAIL_OVERCURRENT_TEST" => Some(Self::TailOvercurrentTest),
            "R1_OPENING_FAILURE_TEST" => Some(Self::R1OpeningFailureTest),
            "LOW_SOURCE_VOLTAGE" => Some(Self::LowSourceVoltage),
            _ => None,
        }
    }

    fn source_pu(self) -> f64 {
        if self == Self::LowSourceVoltage {
            0.9
        } else {
            1.0
        }
    }

    fn load_multiplier(self) -> f64 {
        if matches!(self, Self::TailOvercurrentTest | Self::R1OpeningFailureTest) {
            5.0
        } else {
            1.0
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BusMeasurement {
    pub bus_idx: usize,
    pub name: String,
    pub nominal_kv: f64,
    pub vm_pu: Option<f64>,
    pub vm_kv: Option<f64>,
    pub va_degree: Option<f64>,
    pub p_mw: Option<f64>,
    pub q_mvar: Option<f64>,
    pub energized: bool,
    pub quality: Quality,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineMeasurement {
    pub line_idx: usize,
    pub name: String,
    pub end: String,
    pub from_bus: usize,
    pub to_bus: usize,
    pub p_mw: Option<f64>,
    pub q_mvar: Option<f64>,
    pub pl_mw: Option<f64>,
    pub ql_mvar: Option<f64>,
    pub i_ka: Option<f64>,
    /// A topological deduction, never passed off as a measured current.
    pub inferred_through_current_ka: Option<f64>,
    pub vm_pu: Option<f64>,
    pub va_degree: Option<f64>,
    pub loading_percent: Option<f64>,
    pub energized: bool,
    pub quality: Quality,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TransformerMeasurement {
    pub transformer_idx: usize,
    pub name: String,
    pub hv_bus: usize,
    pub lv_bus: usize,
    pub p_hv_mw: Option<f64>,
    pub q_hv_mvar: Option<f64>,
    pub p_lv_mw: Option<f64>,
    pub q_lv_mvar: Option<f64>,
    pub i_hv_ka: Option<f64>,
    pub i_lv_ka: Option<f64>,
    pub vm_hv_pu: Option<f64>,
    pub vm_lv_pu: Option<f64>,
    pub va_hv_degree: Option<f64>,
    pub va_lv_degree: Option<f64>,
    pub loading_percent: Option<f64>,
    pub energized: bool,
    pub quality: Quality,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExtGridMeasurement {
    pub grid_idx: usize,
    pub name: String,
    pub bus: usize,
    pub p_mw: Option<f64>,
    pub q_mvar: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Telemetry {
    pub ts: String,
    pub buses: Vec<BusMeasurement>,
    pub lines: Vec<LineMeasurement>,
    pub transformers: Vec<TransformerMeasurement>,
    pub ext_grid: ExtGridMeasurement,
}

#[derive(Clone, Copy)]
struct Branch {
    from: usize,
    to: usize,
    r: f64,
    x: f64,
    b: f64,
    shift_degree: f64,
}

impl Branch {
    fn admittance(self) -> (Complex64, Complex64, Complex64, Complex64) {
        let y = Complex64::new(1.0, 0.0) / Complex64::new(self.r, self.x);
        let shunt = Complex64::new(0.0, self.b / 2.0);
        let tap = Complex64::from_polar(1.0, self.shift_degree.to_radians());
        (y + shunt, -y / tap.conj(), -y / tap, y + shunt)
    }
}

const BRANCHES: [Branch; 4] = [
    // T1: 25 MVA 110/20 kV, vk 12%, vkr 0.41%, pfe 14 kW, i0 0.07%, shift 150°.
    Branch {
        from: 0,
        to: 1,
        r: 0.0163923679,
        x: 0.479726336,
        b: -0.000105000908,
        shift_degree: 150.0,
    },
    // L1: 5 km, 0.5939 Ω/km, 0.372 Ω/km, 9.5 nF/km at 50 Hz.
    Branch {
        from: 1,
        to: 2,
        r: 0.742375,
        x: 0.465,
        b: 0.0000596902604,
        shift_degree: 0.0,
    },
    // L2: 3 km of the same conductor.
    Branch {
        from: 2,
        to: 3,
        r: 0.445425,
        x: 0.279,
        b: 0.0000358141563,
        shift_degree: 0.0,
    },
    // T2: 2.5 MVA 20/0.4 kV, vk 6%, vkr 1%, pfe 6 kW, i0 0.25%, shift 150°.
    Branch {
        from: 3,
        to: 4,
        r: 0.399926683,
        x: 2.36648411,
        b: -0.0000175017385,
        shift_degree: 150.0,
    },
];

#[derive(Clone, Debug)]
pub struct Plant {
    pub f1_closed: bool,
    pub r1_closed: bool,
    pub scenario: Scenario,
    tick: u64,
    variation: f64,
    pub latest: Option<Telemetry>,
}

impl Default for Plant {
    fn default() -> Self {
        Self {
            f1_closed: true,
            r1_closed: true,
            scenario: Scenario::Normal,
            tick: 0,
            variation: 1.0,
            latest: None,
        }
    }
}

impl Plant {
    pub fn set_scenario(&mut self, scenario: Scenario) {
        self.scenario = scenario;
        self.variation = 1.0;
    }
    pub fn position(&self, breaker: &str) -> Option<bool> {
        match breaker {
            "BRK_F1" => Some(self.f1_closed),
            "BRK_R1" => Some(self.r1_closed),
            _ => None,
        }
    }
    /// Returns the actual post-attempt position. Failure injection lives here only.
    pub fn attempt(&mut self, breaker: &str, closed: bool) -> Option<bool> {
        match breaker {
            "BRK_F1" => self.f1_closed = closed,
            "BRK_R1" => {
                if !(self.scenario == Scenario::R1OpeningFailureTest && !closed) {
                    self.r1_closed = closed;
                }
            }
            _ => return None,
        }
        self.position(breaker)
    }
    pub fn vary_load(&mut self) {
        self.tick += 1;
        self.variation = if self.scenario == Scenario::Normal {
            1.0 + 0.05 * (std::f64::consts::TAU * ((self.tick % 120) as f64) / 120.0).sin()
        } else {
            1.0
        };
    }

    fn active(&self) -> [bool; 4] {
        [
            true,
            self.f1_closed,
            self.r1_closed && self.f1_closed,
            self.r1_closed && self.f1_closed,
        ]
    }
    fn energized(&self) -> [bool; 5] {
        [
            true,
            true,
            self.f1_closed,
            self.f1_closed && self.r1_closed,
            self.f1_closed && self.r1_closed,
        ]
    }

    fn ybus(&self) -> [[Complex64; 5]; 5] {
        let mut y = [[Complex64::new(0.0, 0.0); 5]; 5];
        for (branch, on) in BRANCHES.iter().zip(self.active()) {
            if !on {
                continue;
            }
            let (ff, ft, tf, tt) = branch.admittance();
            y[branch.from][branch.from] += ff;
            y[branch.from][branch.to] += ft;
            y[branch.to][branch.from] += tf;
            y[branch.to][branch.to] += tt;
        }
        y
    }

    fn mismatch(
        &self,
        x: &DVector<f64>,
        buses: &[usize],
        y: &[[Complex64; 5]; 5],
        source: f64,
        load_factor: f64,
    ) -> DVector<f64> {
        let mut v = [Complex64::new(0.0, 0.0); 5];
        v[0] = Complex64::new(source, 0.0);
        for (slot, bus) in buses.iter().enumerate() {
            v[*bus] = Complex64::new(x[2 * slot], x[2 * slot + 1]);
        }
        let mut f = DVector::zeros(buses.len() * 2);
        for (slot, bus) in buses.iter().enumerate() {
            let current: Complex64 = (0..5).map(|j| y[*bus][j] * v[j]).sum();
            let power = v[*bus] * current.conj();
            let target = if *bus == 4 {
                let zip = 0.5 + 0.5 * v[4].norm();
                Complex64::new(-2.0 / BASE_MVA, -0.5 / BASE_MVA) * load_factor * zip
            } else {
                Complex64::new(0.0, 0.0)
            };
            f[2 * slot] = power.re - target.re;
            f[2 * slot + 1] = power.im - target.im;
        }
        f
    }

    fn solve_voltages(&self) -> Result<([Complex64; 5], [[Complex64; 5]; 5]), String> {
        let energized = self.energized();
        let buses: Vec<usize> = (1..5).filter(|i| energized[*i]).collect();
        let y = self.ybus();
        let source = self.scenario.source_pu();
        // The fivefold ZIP load has two converged AC solutions. Pandapower's
        // reference run lands on the lower-voltage solution, so seed that
        // branch explicitly instead of silently selecting the higher one.
        let angles: [f64; 5] = if self.scenario.load_multiplier() > 1.5 {
            [0.0, -153.0, -151.0, -149.0, 28.0]
        } else {
            [0.0, -150.0, -150.0, -150.0, 60.0]
        };
        let mut x = DVector::zeros(buses.len() * 2);
        for (slot, bus) in buses.iter().enumerate() {
            let start = if self.scenario.load_multiplier() > 1.5 {
                [1.0, 0.94, 0.79, 0.70, 0.42][*bus]
            } else {
                source
            };
            let init = Complex64::from_polar(start, angles[*bus].to_radians());
            x[2 * slot] = init.re;
            x[2 * slot + 1] = init.im;
        }
        let final_factor = self.scenario.load_multiplier() * self.variation;
        let steps = 1;
        for stage in 1..=steps {
            let factor = if steps == 1 {
                final_factor
            } else {
                1.0 + (final_factor - 1.0) * stage as f64 / steps as f64
            };
            for _ in 0..30 {
                let f = self.mismatch(&x, &buses, &y, source, factor);
                let norm = f.amax();
                if norm < 1e-10 {
                    break;
                }
                let mut jac = DMatrix::zeros(f.len(), x.len());
                for col in 0..x.len() {
                    let mut xp = x.clone();
                    xp[col] += 1e-6;
                    let fp = self.mismatch(&xp, &buses, &y, source, factor);
                    for row in 0..f.len() {
                        jac[(row, col)] = (fp[row] - f[row]) / 1e-6;
                    }
                }
                let delta = jac.lu().solve(&(-&f)).ok_or("singular feeder Jacobian")?;
                let mut scale = 1.0;
                let mut moved = false;
                for _ in 0..14 {
                    let candidate = &x + scale * &delta;
                    if self.mismatch(&candidate, &buses, &y, source, factor).amax() < norm {
                        x = candidate;
                        moved = true;
                        break;
                    }
                    scale *= 0.5;
                }
                if !moved {
                    return Err(format!("power flow did not improve at factor {factor}"));
                }
            }
            if self.mismatch(&x, &buses, &y, source, factor).amax() >= 1e-8 {
                return Err(format!("power flow did not converge at factor {factor}"));
            }
        }
        let mut v = [Complex64::new(0.0, 0.0); 5];
        v[0] = Complex64::new(source, 0.0);
        for (slot, bus) in buses.iter().enumerate() {
            v[*bus] = Complex64::new(x[2 * slot], x[2 * slot + 1]);
        }
        Ok((v, y))
    }

    pub fn solve(&mut self) -> Result<Telemetry, String> {
        let (v, y) = self.solve_voltages()?;
        let energized = self.energized();
        let mut bus_power = [Complex64::new(0.0, 0.0); 5];
        for i in 0..5 {
            if !energized[i] {
                continue;
            }
            let current: Complex64 = (0..5).map(|j| y[i][j] * v[j]).sum();
            bus_power[i] = v[i] * current.conj() * BASE_MVA;
        }
        let buses = (0..5)
            .map(|i| BusMeasurement {
                bus_idx: i,
                name: BUS_NAMES[i].into(),
                nominal_kv: NOMINAL_KV[i],
                vm_pu: energized[i].then_some(v[i].norm()),
                vm_kv: energized[i].then_some(v[i].norm() * NOMINAL_KV[i]),
                va_degree: energized[i].then_some(v[i].arg().to_degrees()),
                p_mw: energized[i].then_some(if i == 0 || i == 4 {
                    bus_power[i].re
                } else {
                    0.0
                }),
                q_mvar: energized[i].then_some(if i == 0 || i == 4 {
                    bus_power[i].im
                } else {
                    0.0
                }),
                energized: energized[i],
                quality: if energized[i] {
                    Quality::Good
                } else {
                    Quality::NotEnergized
                },
            })
            .collect();
        let mut lines = Vec::new();
        let mut transformers = Vec::new();
        for (idx, branch) in BRANCHES.iter().enumerate() {
            let on = self.active()[idx];
            let (yff, yft, ytf, ytt) = branch.admittance();
            let ifrom = yff * v[branch.from] + yft * v[branch.to];
            let ito = ytf * v[branch.from] + ytt * v[branch.to];
            let sf = v[branch.from] * ifrom.conj() * BASE_MVA;
            let st = v[branch.to] * ito.conj() * BASE_MVA;
            let current_from = ifrom.norm() * BASE_MVA / (3.0_f64.sqrt() * NOMINAL_KV[branch.from]);
            let current_to = ito.norm() * BASE_MVA / (3.0_f64.sqrt() * NOMINAL_KV[branch.to]);
            if idx == 1 || idx == 2 {
                let line_idx = idx - 1;
                for (end, bus, power, current) in [
                    ("from", branch.from, sf, current_from),
                    ("to", branch.to, st, current_to),
                ] {
                    lines.push(LineMeasurement {
                        line_idx,
                        name: LINE_NAMES[line_idx].into(),
                        end: end.into(),
                        from_bus: branch.from,
                        to_bus: branch.to,
                        p_mw: on.then_some(power.re),
                        q_mvar: on.then_some(power.im),
                        pl_mw: on.then_some(sf.re + st.re),
                        ql_mvar: on.then_some(sf.im + st.im),
                        i_ka: on.then_some(current),
                        inferred_through_current_ka: (!on).then_some(0.0),
                        vm_pu: on.then_some(v[bus].norm()),
                        va_degree: on.then_some(v[bus].arg().to_degrees()),
                        loading_percent: on.then_some(current_from.max(current_to) / 0.21 * 100.0),
                        energized: on,
                        quality: if on {
                            Quality::Good
                        } else {
                            Quality::NotEnergized
                        },
                    });
                }
            } else {
                let trafo_idx = if idx == 0 { 0 } else { 1 };
                let rated = if idx == 0 { 25.0 } else { 2.5 };
                let base_from = rated / (3.0_f64.sqrt() * NOMINAL_KV[branch.from]);
                let base_to = rated / (3.0_f64.sqrt() * NOMINAL_KV[branch.to]);
                transformers.push(TransformerMeasurement {
                    transformer_idx: trafo_idx,
                    name: TRAFO_NAMES[trafo_idx].into(),
                    hv_bus: branch.from,
                    lv_bus: branch.to,
                    p_hv_mw: on.then_some(sf.re),
                    q_hv_mvar: on.then_some(sf.im),
                    p_lv_mw: on.then_some(st.re),
                    q_lv_mvar: on.then_some(st.im),
                    i_hv_ka: on.then_some(current_from),
                    i_lv_ka: on.then_some(current_to),
                    vm_hv_pu: on.then_some(v[branch.from].norm()),
                    vm_lv_pu: on.then_some(v[branch.to].norm()),
                    va_hv_degree: on.then_some(v[branch.from].arg().to_degrees()),
                    va_lv_degree: on.then_some(v[branch.to].arg().to_degrees()),
                    loading_percent: on
                        .then_some((current_from / base_from).max(current_to / base_to) * 100.0),
                    energized: on,
                    quality: if on {
                        Quality::Good
                    } else {
                        Quality::NotEnergized
                    },
                });
            }
        }
        let ext_grid = ExtGridMeasurement {
            grid_idx: 0,
            name: BUS_NAMES[0].into(),
            bus: 0,
            p_mw: Some(bus_power[0].re),
            q_mvar: Some(bus_power[0].im),
        };
        let result = Telemetry {
            ts: String::new(),
            buses,
            lines,
            transformers,
            ext_grid,
        };
        self.latest = Some(result.clone());
        Ok(result)
    }

    pub fn unknown_telemetry(&self) -> Telemetry {
        let buses = (0..5)
            .map(|i| BusMeasurement {
                bus_idx: i,
                name: BUS_NAMES[i].into(),
                nominal_kv: NOMINAL_KV[i],
                vm_pu: None,
                vm_kv: None,
                va_degree: None,
                p_mw: None,
                q_mvar: None,
                energized: false,
                quality: Quality::Unknown,
            })
            .collect();
        let lines = (0..2)
            .flat_map(|i| {
                ["from", "to"].map(move |end| LineMeasurement {
                    line_idx: i,
                    name: LINE_NAMES[i].into(),
                    end: end.into(),
                    from_bus: i + 1,
                    to_bus: i + 2,
                    p_mw: None,
                    q_mvar: None,
                    pl_mw: None,
                    ql_mvar: None,
                    i_ka: None,
                    inferred_through_current_ka: None,
                    vm_pu: None,
                    va_degree: None,
                    loading_percent: None,
                    energized: false,
                    quality: Quality::Unknown,
                })
            })
            .collect();
        let transformers = [(0, 0, 1), (1, 3, 4)]
            .map(|(i, hv, lv)| TransformerMeasurement {
                transformer_idx: i,
                name: TRAFO_NAMES[i].into(),
                hv_bus: hv,
                lv_bus: lv,
                p_hv_mw: None,
                q_hv_mvar: None,
                p_lv_mw: None,
                q_lv_mvar: None,
                i_hv_ka: None,
                i_lv_ka: None,
                vm_hv_pu: None,
                vm_lv_pu: None,
                va_hv_degree: None,
                va_lv_degree: None,
                loading_percent: None,
                energized: false,
                quality: Quality::Unknown,
            })
            .to_vec();
        Telemetry {
            ts: String::new(),
            buses,
            lines,
            transformers,
            ext_grid: ExtGridMeasurement {
                grid_idx: 0,
                name: BUS_NAMES[0].into(),
                bus: 0,
                p_mw: None,
                q_mvar: None,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> serde_json::Value {
        serde_json::from_str(include_str!("../fixtures/pandapower_reference.json")).unwrap()
    }
    fn close_nonzero(actual: Option<f64>, expected: &serde_json::Value, label: &str) {
        match (actual, expected.as_f64()) {
            (Some(a), Some(e)) if e.abs() > 0.1 => {
                assert!((a - e).abs() <= 0.05 * e.abs(), "{label}: {a} vs {e}")
            }
            (Some(a), Some(e)) => assert!((a - e).abs() < 0.02, "{label}: {a} vs {e}"),
            (None, None) => {}
            _ => panic!("{label}: availability mismatch"),
        }
    }
    fn expected<'a>(
        case: &'a serde_json::Value,
        section: &str,
        name: &str,
        end: Option<&str>,
    ) -> &'a serde_json::Value {
        case[section]
            .as_array()
            .unwrap()
            .iter()
            .find(|x| x["name"] == name && end.is_none_or(|e| x["end"] == e))
            .unwrap()
    }
    #[test]
    fn pandapower_voltage_current_power_and_loading_parity() {
        for (name, scenario, open) in [
            ("normal", Scenario::Normal, None),
            ("f1_open", Scenario::Normal, Some("BRK_F1")),
            ("r1_open", Scenario::Normal, Some("BRK_R1")),
            ("overload", Scenario::TailOvercurrentTest, None),
            ("low_source", Scenario::LowSourceVoltage, None),
        ] {
            let mut plant = Plant::default();
            plant.set_scenario(scenario);
            if let Some(b) = open {
                plant.attempt(b, false);
            }
            let actual = plant.solve().unwrap();
            let reference = &fixture()[name];
            let vtol = if name == "overload" { 0.03 } else { 0.01 };
            let itol = if name == "overload" { 0.03 } else { 0.01 };
            for bus in &actual.buses {
                let exp = expected(reference, "buses", &bus.name, None);
                assert_eq!(
                    bus.energized,
                    exp["energized"].as_bool().unwrap(),
                    "{name} {}",
                    bus.name
                );
                match bus.vm_pu {
                    Some(v) => assert!(
                        (v - exp["vm_pu"].as_f64().unwrap()).abs() < vtol,
                        "{name} {} voltage {} vs {}",
                        bus.name,
                        v,
                        exp["vm_pu"]
                    ),
                    None => assert!(exp["vm_pu"].is_null()),
                }
                assert_eq!(serde_json::to_value(bus.quality).unwrap(), exp["quality"]);
                if bus.energized {
                    close_nonzero(
                        bus.p_mw,
                        &exp["p_mw"],
                        &format!("{name} {} bus P", bus.name),
                    );
                    close_nonzero(
                        bus.q_mvar,
                        &exp["q_mvar"],
                        &format!("{name} {} bus Q", bus.name),
                    );
                }
            }
            for line in &actual.lines {
                let exp = expected(reference, "lines", &line.name, Some(&line.end));
                if let Some(current) = line.i_ka {
                    assert!(
                        (current - exp["i_ka"].as_f64().unwrap()).abs() < itol,
                        "{name} {} {} current",
                        line.name,
                        line.end
                    );
                } else {
                    assert!(
                        exp["i_ka"].is_null()
                            || exp["i_ka"].as_f64().is_some_and(|v| v.abs() < 1e-8)
                    );
                }
                assert_eq!(serde_json::to_value(line.quality).unwrap(), exp["quality"]);
                if let Some(loading) = line.loading_percent {
                    assert!((loading - exp["loading_percent"].as_f64().unwrap()).abs() < 5.0);
                }
                if line.energized {
                    close_nonzero(
                        line.p_mw,
                        &exp["p_mw"],
                        &format!("{name} {} {} P", line.name, line.end),
                    );
                    close_nonzero(
                        line.q_mvar,
                        &exp["q_mvar"],
                        &format!("{name} {} {} Q", line.name, line.end),
                    );
                }
            }
            for trafo in &actual.transformers {
                let exp = expected(reference, "transformers", &trafo.name, None);
                if let Some(loading) = trafo.loading_percent {
                    assert!(
                        (loading - exp["loading_percent"].as_f64().unwrap()).abs() < 5.0,
                        "{name} {} loading {loading} vs {}",
                        trafo.name,
                        exp["loading_percent"]
                    );
                } else {
                    assert!(exp["loading_percent"].is_null());
                }
                assert_eq!(serde_json::to_value(trafo.quality).unwrap(), exp["quality"]);
                if trafo.energized {
                    close_nonzero(
                        trafo.p_hv_mw,
                        &exp["p_hv_mw"],
                        &format!("{name} {} HV P", trafo.name),
                    );
                    close_nonzero(
                        trafo.q_hv_mvar,
                        &exp["q_hv_mvar"],
                        &format!("{name} {} HV Q", trafo.name),
                    );
                }
            }
            serde_json::to_string(&actual).unwrap();
        }
    }
    #[test]
    fn named_test_scenarios_keep_fixed_solvable_inputs_across_publications() {
        for scenario in [
            Scenario::TailOvercurrentTest,
            Scenario::R1OpeningFailureTest,
            Scenario::LowSourceVoltage,
        ] {
            let mut plant = Plant::default();
            plant.set_scenario(scenario);
            for _ in 0..120 {
                plant.vary_load();
                assert_eq!(plant.variation, 1.0);
                let telemetry = plant.solve().expect("test condition must remain solvable");
                assert!(telemetry.buses.iter().all(|b| b.quality == Quality::Good));
            }
        }
    }
}
