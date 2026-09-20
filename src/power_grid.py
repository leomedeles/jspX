# src/power_grid.py
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

import numpy as np
import pandapower as pp


@dataclass
class ThreeBusGrid:
    """
    Minimal 3-bus MV network:
      BUS0_SLACK --BRK_L1_SOURCE--L1--> BUS1_LOAD --BRK_L2--L2--> BUS2_LOAD

    All buses at 20 kV. Slack at BUS0. Two loads on BUS1 & BUS2.
    Lines use rough MV parameters; goal is stable, reproducible telemetry (not planning).
    """
    NORMAL: ClassVar[str] = "NORMAL"
    OVERCURRENT: ClassVar[str] = "OVERCURRENT"
    UNDERVOLTAGE: ClassVar[str] = "UNDERVOLTAGE"
    DOWNSTREAM_OVERCURRENT: ClassVar[str] = "DOWNSTREAM_OVERCURRENT"
    SCENARIOS: ClassVar[frozenset[str]] = frozenset(
        {NORMAL, OVERCURRENT, UNDERVOLTAGE, DOWNSTREAM_OVERCURRENT}
    )
    NORMAL_SOURCE_VOLTAGE_PU: ClassVar[float] = 1.0
    UNDERVOLTAGE_SOURCE_VOLTAGE_PU: ClassVar[float] = 0.90
    OVERCURRENT_LOAD_MULTIPLIER: ClassVar[float] = 5.0

    net: pp.pandapowerNet
    base_p_mw: np.ndarray  # [p_bus1, p_bus2]
    base_q_mvar: np.ndarray  # [q_bus1, q_bus2]
    protected_line_idx: int
    breaker_switch_idx: int
    l2_line_idx: int
    l2_breaker_switch_idx: int
    downstream_bus_indices: tuple[int, ...]
    scenario: str = NORMAL
    step_count: int = 0

    @staticmethod
    def build(seed: int | None = 42) -> "ThreeBusGrid":
        if seed is not None:
            np.random.seed(seed)

        net = pp.create_empty_network(sn_mva=100.0)

        # Buses (20 kV level)
        b0 = pp.create_bus(net, vn_kv=20.0, name="BUS0_SLACK")
        b1 = pp.create_bus(net, vn_kv=20.0, name="BUS1_LOAD")
        b2 = pp.create_bus(net, vn_kv=20.0, name="BUS2_LOAD")

        # Slack (external grid) at BUS0
        pp.create_ext_grid(net, bus=b0, vm_pu=1.0, name="GRID_SLACK")

        # Lines (simple MV-ish parameters; not tied to a std_type to keep it portable)
        # L1: BUS0 -> BUS1 (5 km)
        l1 = pp.create_line_from_parameters(
            net, from_bus=b0, to_bus=b1, length_km=5.0,
            r_ohm_per_km=0.08, x_ohm_per_km=0.30, c_nf_per_km=210.0, max_i_ka=0.20,
            name="L1_5km"
        )
        # L2: BUS1 -> BUS2 (3 km)
        l2 = pp.create_line_from_parameters(
            net, from_bus=b1, to_bus=b2, length_km=3.0,
            r_ohm_per_km=0.08, x_ohm_per_km=0.30, c_nf_per_km=210.0, max_i_ka=0.20,
            name="L2_3km"
        )

        # Source-side circuit breaker for the protected feeder path. Opening this
        # real pandapower line switch isolates L1 and both downstream load buses.
        breaker = pp.create_switch(
            net,
            bus=b0,
            element=l1,
            et="l",
            closed=True,
            type="CB",
            name="BRK_L1_SOURCE",
        )

        # Downstream feeder breaker at the BUS1 side of L2. This slice exposes
        # only its physical position; controller integration remains separate.
        l2_breaker = pp.create_switch(
            net,
            bus=b1,
            element=l2,
            et="l",
            closed=True,
            type="CB",
            name="BRK_L2",
        )

        # Base loads
        base_p = np.array([1.20, 0.80])  # MW at BUS1, BUS2
        base_q = np.array([0.30, 0.20])  # Mvar at BUS1, BUS2

        # Create loads
        pp.create_load(net, bus=b1, p_mw=base_p[0], q_mvar=base_q[0], name="LOAD_B1")
        pp.create_load(net, bus=b2, p_mw=base_p[1], q_mvar=base_q[1], name="LOAD_B2")

        return ThreeBusGrid(
            net=net,
            base_p_mw=base_p,
            base_q_mvar=base_q,
            protected_line_idx=l1,
            breaker_switch_idx=breaker,
            l2_line_idx=l2,
            l2_breaker_switch_idx=l2_breaker,
            downstream_bus_indices=(b1, b2),
        )

    def _apply_variation(self) -> None:
        """Small, smooth variability so values move a bit each second."""
        t = self.step_count
        swing = 0.05 * np.sin(2 * np.pi * (t % 120) / 120.0)  # ±5% over ~2 minutes
        noise = np.random.normal(0.0, 0.005, size=2)          # ±0.5% jitter
        factor = self._scenario_load_multiplier() * (1.0 + swing + noise)

        # Update the two loads
        self.net.load.at[0, "p_mw"] = max(0.1, self.base_p_mw[0] * factor[0])
        self.net.load.at[0, "q_mvar"] = max(0.0, self.base_q_mvar[0] * factor[0] * 0.8)
        self.net.load.at[1, "p_mw"] = max(0.1, self.base_p_mw[1] * factor[1])
        self.net.load.at[1, "q_mvar"] = max(0.0, self.base_q_mvar[1] * factor[1] * 0.8)

    def set_scenario(self, scenario: str) -> bool:
        """Apply one validated set of physical grid conditions atomically."""
        if scenario not in self.SCENARIOS:
            return False

        source_voltage = (
            self.UNDERVOLTAGE_SOURCE_VOLTAGE_PU
            if scenario == self.UNDERVOLTAGE
            else self.NORMAL_SOURCE_VOLTAGE_PU
        )
        load_multiplier = (
            self.OVERCURRENT_LOAD_MULTIPLIER
            if scenario == self.OVERCURRENT
            else 1.0
        )

        # DOWNSTREAM_OVERCURRENT is an explicit protection teaching signal,
        # not a calculated electrical fault. Its persistent condition is read
        # by the simulator while the solved load flow remains at base demand.

        self.net.ext_grid.loc[:, "vm_pu"] = source_voltage
        self._set_loads(load_multiplier)
        self.scenario = scenario
        return True

    def _scenario_load_multiplier(self) -> float:
        return (
            self.OVERCURRENT_LOAD_MULTIPLIER
            if self.scenario == self.OVERCURRENT
            else 1.0
        )

    def _set_loads(self, multiplier: float) -> None:
        """Set deterministic P/Q demand without changing line ratings."""
        for load_idx, p_mw, q_mvar in zip(
            self.net.load.index, self.base_p_mw, self.base_q_mvar
        ):
            self.net.load.at[load_idx, "p_mw"] = p_mw * multiplier
            self.net.load.at[load_idx, "q_mvar"] = q_mvar * multiplier

    @property
    def breaker_closed(self) -> bool:
        """Return the physical position of the protected-line switch."""
        return bool(self.net.switch.at[self.breaker_switch_idx, "closed"])

    def set_breaker_closed(self, closed: bool) -> None:
        """Apply a controller position to the real pandapower line switch."""
        self.net.switch.at[self.breaker_switch_idx, "closed"] = bool(closed)

    @property
    def l2_breaker_closed(self) -> bool:
        """Return the physical position of the BUS1-side L2 switch."""
        return bool(self.net.switch.at[self.l2_breaker_switch_idx, "closed"])

    def set_l2_breaker_closed(self, closed: bool) -> None:
        """Set the physical position of the BUS1-side L2 switch."""
        self.net.switch.at[self.l2_breaker_switch_idx, "closed"] = bool(closed)

    def solve(self, *, vary_load: bool = False) -> dict[str, Any]:
        """Solve the currently selected topology and return safe telemetry."""
        if vary_load:
            self._apply_variation()
            self.step_count += 1
        pp.runpp(self.net, algorithm="nr", tolerance_mva=1e-6, numba=False)
        return self.read_measurements()

    def protected_line_loading_percent(self) -> float | None:
        """Return pandapower's finite L1 loading result for protection."""
        if self.protected_line_idx not in self.net.res_line.index:
            return None
        return self._json_number(
            self.net.res_line.at[self.protected_line_idx, "loading_percent"]
        )

    def downstream_voltages_pu(self) -> tuple[float | None, ...]:
        """Return finite voltages for the buses supplied through L1."""
        return tuple(
            self._json_number(self.net.res_bus.at[bus_idx, "vm_pu"])
            for bus_idx in self.downstream_bus_indices
        )

    @staticmethod
    def _json_number(value: object) -> float | None:
        """Convert a numeric result to finite JSON data or ``None``."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _quality(energized: bool) -> str:
        return "GOOD" if energized else "NOT_ENERGIZED"

    def _line_switch_open(self, line_idx: int) -> bool:
        """Return whether any pandapower line switch for this line is open."""
        switches = self.net.switch
        line_switches = switches.loc[
            (switches["et"] == "l") & (switches["element"] == line_idx),
            "closed",
        ]
        return any(not bool(closed) for closed in line_switches)

    def read_measurements(self) -> dict[str, Any]:
        """Return a SCADA-like snapshot from res_bus (vm_pu, p_mw, q_mvar)."""
        rb = self.net.res_bus  # has vm_pu, va_degree, p_mw, q_mvar (bus injections)
        rl = self.net.res_line
        rext = self.net.res_ext_grid
        out_bus: list[dict[str, Any]] = []
        out_line: list[dict[str, Any]] = []
        for idx, row in rb.iterrows():
            vm_pu = self._json_number(row["vm_pu"])
            energized = vm_pu is not None
            out_bus.append({
                "bus_idx": int(idx),
                "name": self.net.bus.at[idx, "name"],
                "vm_pu": vm_pu,
                "va_degree": self._json_number(row["va_degree"]),
                "p_mw": self._negated_json_number(row["p_mw"]),
                "q_mvar": self._negated_json_number(row["q_mvar"]),
                "energized": energized,
                "quality": self._quality(energized),
            })
        for idx, row in rl.iterrows():
            line_switch_open = self._line_switch_open(idx)
            for end in ("from", "to"):
                vm_pu = self._json_number(row[f"vm_{end}_pu"])
                energized = vm_pu is not None and not line_switch_open
                # pandapower reports NaN current/loading for a line disconnected
                # by an open switch. The open circuit makes through-current and
                # loading exactly zero; voltages remain unavailable and become null.
                i_ka = (
                    0.0
                    if line_switch_open
                    else self._json_number(row[f"i_{end}_ka"])
                )
                loading_percent = (
                    0.0
                    if line_switch_open
                    else self._json_number(row["loading_percent"])
                )
                out_line.append({
                    "line_idx": int(idx),
                    "name": self.net.line.at[idx, "name"],
                    "end": end,
                    "from_bus": int(self.net.line.at[idx, "from_bus"]),
                    "to_bus": int(self.net.line.at[idx, "to_bus"]),
                    "p_mw": self._json_number(row[f"p_{end}_mw"]),
                    "q_mvar": self._json_number(row[f"q_{end}_mvar"]),
                    "pl_mw": self._json_number(row["pl_mw"]),
                    "ql_mvar": self._json_number(row["ql_mvar"]),
                    "i_ka": i_ka,
                    "vm_pu": vm_pu,
                    "va_degree": self._json_number(row[f"va_{end}_degree"]),
                    "loading_percent": loading_percent,
                    "energized": energized,
                    "quality": self._quality(energized),
                })
        out_ext_grid = {
            "p_mw": self._json_number(rext.at[rext.index[0], "p_mw"]),
            "q_mvar": self._json_number(rext.at[rext.index[0], "q_mvar"]),
            }
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "buses": out_bus,
            "lines": out_line,
            "ext_grid": out_ext_grid
        }

    def _negated_json_number(self, value: object) -> float | None:
        number = self._json_number(value)
        return -number if number is not None else None

    def step(self) -> dict[str, Any]:
        """Advance one second of 'time': vary load, solve power flow, return JSON-able dict."""
        return self.solve(vary_load=True)


def stream_jsonl(grid: ThreeBusGrid, hz: float = 1.0, file_path: str | None = None) -> None:
    """Utility for quick local testing: print or append JSONL at the given rate."""
    period = 1.0 / hz
    while True:
        payload = grid.step()
        line = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if file_path:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line, flush=True)
        time.sleep(period)
