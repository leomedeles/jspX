# src/power_grid.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, List

import numpy as np
import pandapower as pp


@dataclass
class ThreeBusGrid:
    """
    Minimal 3-bus MV network:
      BUS0_SLACK --L1--> BUS1_LOAD --L2--> BUS2_LOAD

    All buses at 20 kV. Slack at BUS0. Two loads on BUS1 & BUS2.
    Lines use rough MV parameters; goal is stable, reproducible telemetry (not planning).
    """
    net: pp.pandapowerNet
    base_p_mw: np.ndarray  # [p_bus1, p_bus2]
    base_q_mvar: np.ndarray  # [q_bus1, q_bus2]
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
        pp.create_line_from_parameters(
            net, from_bus=b0, to_bus=b1, length_km=5.0,
            r_ohm_per_km=0.08, x_ohm_per_km=0.30, c_nf_per_km=210.0, max_i_ka=0.20,
            name="L1_5km"
        )
        # L2: BUS1 -> BUS2 (3 km)
        pp.create_line_from_parameters(
            net, from_bus=b1, to_bus=b2, length_km=3.0,
            r_ohm_per_km=0.08, x_ohm_per_km=0.30, c_nf_per_km=210.0, max_i_ka=0.20,
            name="L2_3km"
        )

        # Base loads
        base_p = np.array([1.20, 0.80])  # MW at BUS1, BUS2
        base_q = np.array([0.30, 0.20])  # Mvar at BUS1, BUS2

        # Create loads
        pp.create_load(net, bus=b1, p_mw=base_p[0], q_mvar=base_q[0], name="LOAD_B1")
        pp.create_load(net, bus=b2, p_mw=base_p[1], q_mvar=base_q[1], name="LOAD_B2")

        return ThreeBusGrid(net=net, base_p_mw=base_p, base_q_mvar=base_q)

    def _apply_variation(self) -> None:
        """Small, smooth variability so values move a bit each second."""
        t = self.step_count
        swing = 0.05 * np.sin(2 * np.pi * (t % 120) / 120.0)  # ±5% over ~2 minutes
        noise = np.random.normal(0.0, 0.005, size=2)          # ±0.5% jitter
        factor = 1.0 + swing + noise

        # Update the two loads
        self.net.load.at[0, "p_mw"] = max(0.1, self.base_p_mw[0] * factor[0])
        self.net.load.at[0, "q_mvar"] = max(0.0, self.base_q_mvar[0] * factor[0] * 0.8)
        self.net.load.at[1, "p_mw"] = max(0.1, self.base_p_mw[1] * factor[1])
        self.net.load.at[1, "q_mvar"] = max(0.0, self.base_q_mvar[1] * factor[1] * 0.8)

    def read_measurements(self) -> Dict[str, Any]:
        """Return a SCADA-like snapshot from res_bus (vm_pu, p_mw, q_mvar)."""
        rb = self.net.res_bus  # has vm_pu, va_degree, p_mw, q_mvar (bus injections)
        rl = self.net.res_line
        rext = self.net.res_ext_grid
        out_bus: List[Dict[str, Any]] = []
        out_line: List[Dict[str, Any]] = []
        out_ext_grid: Dict[str, Any] = {}
        for idx, row in rb.iterrows():
            out_bus.append({
                "bus_idx": int(idx),
                "name": self.net.bus.at[idx, "name"],
                "vm_pu": float(row["vm_pu"]),
                "va_degree": float(row["va_degree"]),
                "p_mw": -float(row["p_mw"]),     # sign convention: + injection, - load
                "q_mvar": -float(row["q_mvar"]), # sign convention as above
            })
        for idx, row in rl.iterrows():
            out_line.append({
                "line_idx": int(idx),
                "name": self.net.line.at[idx, "name"],
                "end": "from",
                "from_bus": int(self.net.line.at[idx, "from_bus"]),
                "to_bus": int(self.net.line.at[idx, "to_bus"]),
                "p_mw": float(row["p_from_mw"]),
                "q_mvar": float(row["q_from_mvar"]),
                "pl_mw": float(row["pl_mw"]),
                "ql_mvar": float(row["ql_mvar"]),
                "i_ka": float(row["i_from_ka"]),
                "vm_pu": float(row["vm_from_pu"]),
                "va_degree": float(row["va_from_degree"]),
                "loading_percent": float(row["loading_percent"]),
            })
            out_line.append({
                "line_idx": int(idx),
                "name": self.net.line.at[idx, "name"],
                "end": "to",
                "from_bus": int(self.net.line.at[idx, "from_bus"]),
                "to_bus": int(self.net.line.at[idx, "to_bus"]),
                "p_mw": float(row["p_to_mw"]),
                "q_mvar": float(row["q_to_mvar"]),
                "pl_mw": float(row["pl_mw"]),
                "ql_mvar": float(row["ql_mvar"]),
                "i_ka": float(row["i_to_ka"]),
                "vm_pu": float(row["vm_to_pu"]),
                "va_degree": float(row["va_to_degree"]),
                "loading_percent": float(row["loading_percent"]),
            })
        out_ext_grid = {
            "p_mw": float(rext.at[rext.index[0], "p_mw"]),
            "q_mvar": float(rext.at[rext.index[0], "q_mvar"])
            }
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "buses": out_bus,
            "lines": out_line,
            "ext_grid": out_ext_grid
        }

    def step(self) -> Dict[str, Any]:
        """Advance one second of 'time': vary load, solve power flow, return JSON-able dict."""
        self._apply_variation()
        pp.runpp(self.net, algorithm="nr", tolerance_mva=1e-6, numba=False)
        self.step_count += 1
        return self.read_measurements()


def stream_jsonl(grid: ThreeBusGrid, hz: float = 1.0, file_path: str | None = None) -> None:
    """Utility for quick local testing: print or append JSONL at the given rate."""
    period = 1.0 / hz
    while True:
        payload = grid.step()
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if file_path:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line, flush=True)
        time.sleep(period)
