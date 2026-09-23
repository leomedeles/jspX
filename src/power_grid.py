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
class ReferenceFeederGrid:
    """Reference 110/20/0.4 kV radial feeder and its measurements."""

    NORMAL: ClassVar[str] = "NORMAL"
    TAIL_OVERCURRENT_TEST: ClassVar[str] = "TAIL_OVERCURRENT_TEST"
    LOW_SOURCE_VOLTAGE: ClassVar[str] = "LOW_SOURCE_VOLTAGE"
    SCENARIOS: ClassVar[frozenset[str]] = frozenset(
        {NORMAL, TAIL_OVERCURRENT_TEST, LOW_SOURCE_VOLTAGE}
    )

    GRID_110KV: ClassVar[str] = "GRID_110KV"
    T1_PRIMARY: ClassVar[str] = "T1_PRIMARY"
    BUS_MV_SOURCE: ClassVar[str] = "BUS_MV_SOURCE"
    BRK_F1: ClassVar[str] = "BRK_F1"
    L1_FEEDER_HEAD: ClassVar[str] = "L1_FEEDER_HEAD"
    BUS_R1_REMOTE: ClassVar[str] = "BUS_R1_REMOTE"
    BRK_R1: ClassVar[str] = "BRK_R1"
    L2_FEEDER_TAIL: ClassVar[str] = "L2_FEEDER_TAIL"
    BUS_SS1_MV: ClassVar[str] = "BUS_SS1_MV"
    T2_SS1: ClassVar[str] = "T2_SS1"
    BUS_SS1_LV: ClassVar[str] = "BUS_SS1_LV"
    LOAD_SS1_AGGREGATE: ClassVar[str] = "LOAD_SS1_AGGREGATE"

    NORMAL_SOURCE_VOLTAGE_PU: ClassVar[float] = 1.0
    LOW_SOURCE_VOLTAGE_PU: ClassVar[float] = 0.90
    TAIL_LOAD_MULTIPLIER: ClassVar[float] = 5.0

    net: pp.pandapowerNet
    base_p_mw: float
    base_q_mvar: float
    bus_indices: dict[str, int]
    line_indices: dict[str, int]
    transformer_indices: dict[str, int]
    breaker_switch_indices: dict[str, int]
    breaker_line_indices: dict[str, int]
    load_idx: int
    scenario: str = NORMAL
    step_count: int = 0

    @staticmethod
    def build(seed: int | None = 42) -> "ReferenceFeederGrid":
        if seed is not None:
            np.random.seed(seed)

        net = pp.create_empty_network(sn_mva=100.0)

        grid_110kv_bus = pp.create_bus(
            net, vn_kv=110.0, name=ReferenceFeederGrid.GRID_110KV
        )
        mv_source_bus = pp.create_bus(
            net, vn_kv=20.0, name=ReferenceFeederGrid.BUS_MV_SOURCE
        )
        r1_remote_bus = pp.create_bus(
            net, vn_kv=20.0, name=ReferenceFeederGrid.BUS_R1_REMOTE
        )
        ss1_mv_bus = pp.create_bus(
            net, vn_kv=20.0, name=ReferenceFeederGrid.BUS_SS1_MV
        )
        ss1_lv_bus = pp.create_bus(
            net, vn_kv=0.4, name=ReferenceFeederGrid.BUS_SS1_LV
        )

        pp.create_ext_grid(
            net,
            bus=grid_110kv_bus,
            vm_pu=ReferenceFeederGrid.NORMAL_SOURCE_VOLTAGE_PU,
            name=ReferenceFeederGrid.GRID_110KV,
        )
        t1 = pp.create_transformer(
            net,
            hv_bus=grid_110kv_bus,
            lv_bus=mv_source_bus,
            std_type="25 MVA 110/20 kV",
            name=ReferenceFeederGrid.T1_PRIMARY,
        )

        line_parameters = {
            "r_ohm_per_km": 0.5939,
            "x_ohm_per_km": 0.372,
            "c_nf_per_km": 9.5,
            "max_i_ka": 0.21,
        }
        l1 = pp.create_line_from_parameters(
            net,
            from_bus=mv_source_bus,
            to_bus=r1_remote_bus,
            length_km=5.0,
            name=ReferenceFeederGrid.L1_FEEDER_HEAD,
            **line_parameters,
        )
        l2 = pp.create_line_from_parameters(
            net,
            from_bus=r1_remote_bus,
            to_bus=ss1_mv_bus,
            length_km=3.0,
            name=ReferenceFeederGrid.L2_FEEDER_TAIL,
            **line_parameters,
        )

        f1 = pp.create_switch(
            net,
            bus=mv_source_bus,
            element=l1,
            et="l",
            closed=True,
            type="CB",
            name=ReferenceFeederGrid.BRK_F1,
        )
        r1 = pp.create_switch(
            net,
            bus=r1_remote_bus,
            element=l2,
            et="l",
            closed=True,
            type="CB",
            name=ReferenceFeederGrid.BRK_R1,
        )

        t2 = pp.create_transformer_from_parameters(
            net,
            hv_bus=ss1_mv_bus,
            lv_bus=ss1_lv_bus,
            sn_mva=2.5,
            vn_hv_kv=20.0,
            vn_lv_kv=0.4,
            vk_percent=6.0,
            vkr_percent=1.0,
            pfe_kw=6.0,
            i0_percent=0.25,
            shift_degree=150.0,
            name=ReferenceFeederGrid.T2_SS1,
        )
        load = pp.create_load(
            net,
            bus=ss1_lv_bus,
            p_mw=2.0,
            q_mvar=0.5,
            name=ReferenceFeederGrid.LOAD_SS1_AGGREGATE,
        )

        return ReferenceFeederGrid(
            net=net,
            base_p_mw=2.0,
            base_q_mvar=0.5,
            bus_indices={
                ReferenceFeederGrid.GRID_110KV: grid_110kv_bus,
                ReferenceFeederGrid.BUS_MV_SOURCE: mv_source_bus,
                ReferenceFeederGrid.BUS_R1_REMOTE: r1_remote_bus,
                ReferenceFeederGrid.BUS_SS1_MV: ss1_mv_bus,
                ReferenceFeederGrid.BUS_SS1_LV: ss1_lv_bus,
            },
            line_indices={
                ReferenceFeederGrid.L1_FEEDER_HEAD: l1,
                ReferenceFeederGrid.L2_FEEDER_TAIL: l2,
            },
            transformer_indices={
                ReferenceFeederGrid.T1_PRIMARY: t1,
                ReferenceFeederGrid.T2_SS1: t2,
            },
            breaker_switch_indices={
                ReferenceFeederGrid.BRK_F1: f1,
                ReferenceFeederGrid.BRK_R1: r1,
            },
            breaker_line_indices={
                ReferenceFeederGrid.BRK_F1: l1,
                ReferenceFeederGrid.BRK_R1: l2,
            },
            load_idx=load,
        )

    def _apply_variation(self) -> None:
        """Apply small smooth variability around the selected demand."""
        t = self.step_count
        swing = 0.05 * np.sin(2 * np.pi * (t % 120) / 120.0)
        noise = float(np.random.normal(0.0, 0.005))
        factor = self._scenario_load_multiplier() * (1.0 + swing + noise)
        self.net.load.at[self.load_idx, "p_mw"] = max(
            0.1, self.base_p_mw * factor
        )
        self.net.load.at[self.load_idx, "q_mvar"] = max(
            0.0, self.base_q_mvar * factor
        )

    def set_scenario(self, scenario: str) -> bool:
        """Apply one validated set of source and aggregate-load inputs."""
        if scenario not in self.SCENARIOS:
            return False

        source_voltage = (
            self.LOW_SOURCE_VOLTAGE_PU
            if scenario == self.LOW_SOURCE_VOLTAGE
            else self.NORMAL_SOURCE_VOLTAGE_PU
        )
        load_multiplier = (
            self.TAIL_LOAD_MULTIPLIER
            if scenario == self.TAIL_OVERCURRENT_TEST
            else 1.0
        )
        self.net.ext_grid.loc[:, "vm_pu"] = source_voltage
        self._set_load(load_multiplier)
        self.scenario = scenario
        return True

    def _scenario_load_multiplier(self) -> float:
        return (
            self.TAIL_LOAD_MULTIPLIER
            if self.scenario == self.TAIL_OVERCURRENT_TEST
            else 1.0
        )

    def _set_load(self, multiplier: float) -> None:
        self.net.load.at[self.load_idx, "p_mw"] = self.base_p_mw * multiplier
        self.net.load.at[self.load_idx, "q_mvar"] = self.base_q_mvar * multiplier

    def breaker_is_closed(self, breaker_name: str) -> bool:
        switch_idx = self._identity_index(
            self.breaker_switch_indices, breaker_name, "breaker"
        )
        return bool(self.net.switch.at[switch_idx, "closed"])

    def set_breaker_closed(self, breaker_name: str, closed: bool) -> None:
        """Set a physical breaker by canonical identity."""
        switch_idx = self._identity_index(
            self.breaker_switch_indices, breaker_name, "breaker"
        )
        self.net.switch.at[switch_idx, "closed"] = bool(closed)

    def breaker_current_ka(self, breaker_name: str) -> float | None:
        """Return the greatest solved terminal current for a breaker's line."""
        line_idx = self._identity_index(
            self.breaker_line_indices, breaker_name, "breaker"
        )
        if line_idx not in self.net.res_line.index:
            return None
        currents = (
            self._json_number(self.net.res_line.at[line_idx, "i_from_ka"]),
            self._json_number(self.net.res_line.at[line_idx, "i_to_ka"]),
        )
        valid_currents = [current for current in currents if current is not None]
        return max(valid_currents) if valid_currents else None

    def bus_voltage_pu(self, bus_name: str) -> float | None:
        bus_idx = self._identity_index(self.bus_indices, bus_name, "bus")
        if bus_idx not in self.net.res_bus.index:
            return None
        return self._json_number(self.net.res_bus.at[bus_idx, "vm_pu"])

    @staticmethod
    def _identity_index(
        indices: dict[str, int], identity: str, asset_type: str
    ) -> int:
        try:
            return indices[identity]
        except KeyError as exc:
            raise ValueError(f"unknown {asset_type}: {identity}") from exc

    def solve(self, *, vary_load: bool = False) -> dict[str, Any]:
        """Solve the selected inputs and topology, then return safe telemetry."""
        if vary_load:
            self._apply_variation()
            self.step_count += 1
        pp.runpp(self.net, algorithm="nr", tolerance_mva=1e-6, numba=False)
        return self.read_measurements()

    @staticmethod
    def _json_number(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _quality(energized: bool) -> str:
        return "GOOD" if energized else "NOT_ENERGIZED"

    def _line_switch_open(self, line_idx: int) -> bool:
        switches = self.net.switch
        line_switches = switches.loc[
            (switches["et"] == "l") & (switches["element"] == line_idx),
            "closed",
        ]
        return any(not bool(closed) for closed in line_switches)

    def read_measurements(self) -> dict[str, Any]:
        """Return bus, line, transformer, and source measurements."""
        out_bus: list[dict[str, Any]] = []
        out_line: list[dict[str, Any]] = []
        out_transformer: list[dict[str, Any]] = []

        for idx, row in self.net.res_bus.iterrows():
            vm_pu = self._json_number(row["vm_pu"])
            energized = vm_pu is not None
            out_bus.append(
                {
                    "bus_idx": int(idx),
                    "name": self.net.bus.at[idx, "name"],
                    "vm_pu": vm_pu,
                    "va_degree": self._json_number(row["va_degree"]),
                    "p_mw": self._negated_json_number(row["p_mw"]),
                    "q_mvar": self._negated_json_number(row["q_mvar"]),
                    "energized": energized,
                    "quality": self._quality(energized),
                }
            )

        for idx, row in self.net.res_line.iterrows():
            line_switch_open = self._line_switch_open(idx)
            for end in ("from", "to"):
                vm_pu = self._json_number(row[f"vm_{end}_pu"])
                energized = vm_pu is not None and not line_switch_open
                out_line.append(
                    {
                        "line_idx": int(idx),
                        "name": self.net.line.at[idx, "name"],
                        "end": end,
                        "from_bus": int(self.net.line.at[idx, "from_bus"]),
                        "to_bus": int(self.net.line.at[idx, "to_bus"]),
                        "p_mw": self._json_number(row[f"p_{end}_mw"]),
                        "q_mvar": self._json_number(row[f"q_{end}_mvar"]),
                        "pl_mw": self._json_number(row["pl_mw"]),
                        "ql_mvar": self._json_number(row["ql_mvar"]),
                        "i_ka": (
                            0.0
                            if line_switch_open
                            else self._json_number(row[f"i_{end}_ka"])
                        ),
                        "vm_pu": vm_pu,
                        "va_degree": self._json_number(
                            row[f"va_{end}_degree"]
                        ),
                        "loading_percent": (
                            0.0
                            if line_switch_open
                            else self._json_number(row["loading_percent"])
                        ),
                        "energized": energized,
                        "quality": self._quality(energized),
                    }
                )

        for idx, row in self.net.res_trafo.iterrows():
            vm_hv_pu = self._json_number(row["vm_hv_pu"])
            vm_lv_pu = self._json_number(row["vm_lv_pu"])
            energized = vm_hv_pu is not None and vm_lv_pu is not None
            out_transformer.append(
                {
                    "transformer_idx": int(idx),
                    "name": self.net.trafo.at[idx, "name"],
                    "hv_bus": int(self.net.trafo.at[idx, "hv_bus"]),
                    "lv_bus": int(self.net.trafo.at[idx, "lv_bus"]),
                    "p_hv_mw": self._json_number(row["p_hv_mw"]),
                    "q_hv_mvar": self._json_number(row["q_hv_mvar"]),
                    "p_lv_mw": self._json_number(row["p_lv_mw"]),
                    "q_lv_mvar": self._json_number(row["q_lv_mvar"]),
                    "i_hv_ka": self._json_number(row["i_hv_ka"]),
                    "i_lv_ka": self._json_number(row["i_lv_ka"]),
                    "vm_hv_pu": vm_hv_pu,
                    "vm_lv_pu": vm_lv_pu,
                    "va_hv_degree": self._json_number(row["va_hv_degree"]),
                    "va_lv_degree": self._json_number(row["va_lv_degree"]),
                    "loading_percent": self._json_number(
                        row["loading_percent"]
                    ),
                    "energized": energized,
                    "quality": self._quality(energized),
                }
            )

        ext_grid_idx = self.net.res_ext_grid.index[0]
        ext_grid_bus = int(self.net.ext_grid.at[ext_grid_idx, "bus"])
        out_ext_grid = {
            "grid_idx": int(ext_grid_idx),
            "name": self.net.ext_grid.at[ext_grid_idx, "name"],
            "bus": ext_grid_bus,
            "p_mw": self._json_number(
                self.net.res_ext_grid.at[ext_grid_idx, "p_mw"]
            ),
            "q_mvar": self._json_number(
                self.net.res_ext_grid.at[ext_grid_idx, "q_mvar"]
            ),
        }
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "buses": out_bus,
            "lines": out_line,
            "transformers": out_transformer,
            "ext_grid": out_ext_grid,
        }

    def _negated_json_number(self, value: object) -> float | None:
        number = self._json_number(value)
        return -number if number is not None else None

    def step(self) -> dict[str, Any]:
        return self.solve(vary_load=True)


def stream_jsonl(
    grid: ReferenceFeederGrid,
    hz: float = 1.0,
    file_path: str | None = None,
) -> None:
    """Print or append strict-JSON telemetry at the requested rate."""
    period = 1.0 / hz
    while True:
        payload = grid.step()
        line = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if file_path:
            with open(file_path, "a", encoding="utf-8") as output:
                output.write(line + "\n")
        else:
            print(line, flush=True)
        time.sleep(period)
