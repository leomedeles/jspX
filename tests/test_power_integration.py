import json

import pytest

from src.power_grid import ReferenceFeederGrid
from src.power_sim import BRK_F1, BRK_R1, ControlledPandapowerSimulator


def by_name(items: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(item for item in items if item["name"] == name)


def line_ends(
    payload: dict[str, object], name: str
) -> list[dict[str, object]]:
    return [line for line in payload["lines"] if line["name"] == name]


def test_reference_feeder_uses_canonical_assets_and_reference_values() -> None:
    grid = ReferenceFeederGrid.build(seed=1)

    assert set(grid.net.bus["name"]) == {
        "GRID_110KV",
        "BUS_MV_SOURCE",
        "BUS_R1_REMOTE",
        "BUS_SS1_MV",
        "BUS_SS1_LV",
    }
    assert list(grid.net.ext_grid["name"]) == ["GRID_110KV"]
    assert set(grid.net.line["name"]) == {
        "L1_FEEDER_HEAD",
        "L2_FEEDER_TAIL",
    }
    assert set(grid.net.trafo["name"]) == {"T1_PRIMARY", "T2_SS1"}
    assert list(grid.net.load["name"]) == ["LOAD_SS1_AGGREGATE"]
    assert set(grid.net.switch["name"]) == {"BRK_F1", "BRK_R1"}

    t1 = grid.net.trafo.loc[grid.transformer_indices[grid.T1_PRIMARY]]
    assert t1["std_type"] == "25 MVA 110/20 kV"
    assert float(t1["sn_mva"]) == pytest.approx(25.0)
    assert float(t1["vn_hv_kv"]) == pytest.approx(110.0)
    assert float(t1["vn_lv_kv"]) == pytest.approx(20.0)

    t2 = grid.net.trafo.loc[grid.transformer_indices[grid.T2_SS1]]
    assert float(t2["sn_mva"]) == pytest.approx(2.5)
    assert float(t2["vn_hv_kv"]) == pytest.approx(20.0)
    assert float(t2["vn_lv_kv"]) == pytest.approx(0.4)
    assert float(t2["vk_percent"]) == pytest.approx(6.0)
    assert float(t2["vkr_percent"]) == pytest.approx(1.0)
    assert float(t2["pfe_kw"]) == pytest.approx(6.0)
    assert float(t2["i0_percent"]) == pytest.approx(0.25)
    assert float(t2["shift_degree"]) == pytest.approx(150.0)

    for name, length in ((grid.L1_FEEDER_HEAD, 5.0), (grid.L2_FEEDER_TAIL, 3.0)):
        line = grid.net.line.loc[grid.line_indices[name]]
        assert float(line["length_km"]) == pytest.approx(length)
        assert float(line["r_ohm_per_km"]) == pytest.approx(0.5939)
        assert float(line["x_ohm_per_km"]) == pytest.approx(0.372)
        assert float(line["c_nf_per_km"]) == pytest.approx(9.5)
        assert float(line["max_i_ka"]) == pytest.approx(0.21)

    load = grid.net.load.loc[grid.load_idx]
    assert float(load["p_mw"]) == pytest.approx(2.0)
    assert float(load["q_mvar"]) == pytest.approx(0.5)
    assert float(load["const_i_percent"]) == pytest.approx(50.0)


def test_normal_supply_energizes_aggregate_load_through_real_line_switches() -> None:
    grid = ReferenceFeederGrid.build(seed=1)

    payload = grid.solve()

    assert grid.breaker_is_closed(BRK_F1) is True
    assert grid.breaker_is_closed(BRK_R1) is True
    for breaker_name in (BRK_F1, BRK_R1):
        switch = grid.net.switch.loc[grid.breaker_switch_indices[breaker_name]]
        assert switch["name"] == breaker_name
        assert switch["et"] == "l"
        assert int(switch["element"]) == grid.breaker_line_indices[breaker_name]
        assert grid.breaker_current_ka(breaker_name) > 0.0

    for bus in payload["buses"]:
        assert bus["energized"] is True
        assert bus["quality"] == "GOOD"
    assert by_name(payload["transformers"], grid.T2_SS1)[
        "loading_percent"
    ] > 0.0
    assert payload["ext_grid"]["name"] == grid.GRID_110KV
    json.dumps(payload, allow_nan=False)


def test_open_f1_deenergizes_remote_point_and_ss1() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    grid.set_breaker_closed(BRK_F1, False)

    payload = grid.solve()

    assert grid.breaker_is_closed(BRK_F1) is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert by_name(payload["buses"], grid.BUS_MV_SOURCE)["energized"] is True
    for bus_name in (
        grid.BUS_R1_REMOTE,
        grid.BUS_SS1_MV,
        grid.BUS_SS1_LV,
    ):
        bus = by_name(payload["buses"], bus_name)
        assert bus["vm_pu"] is None
        assert bus["energized"] is False
        assert bus["quality"] == "NOT_ENERGIZED"
    for line in line_ends(payload, grid.L1_FEEDER_HEAD):
        assert line["i_ka"] == pytest.approx(0.0, abs=1e-12)
        assert line["loading_percent"] == pytest.approx(0.0, abs=1e-12)
        assert line["energized"] is False
    t2 = by_name(payload["transformers"], grid.T2_SS1)
    assert t2["loading_percent"] is None
    assert t2["energized"] is False
    assert t2["quality"] == "NOT_ENERGIZED"
    json.dumps(payload, allow_nan=False)


def test_open_r1_keeps_remote_point_energized_but_deenergizes_ss1() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    grid.set_breaker_closed(BRK_R1, False)

    payload = grid.solve()

    assert grid.breaker_is_closed(BRK_F1) is True
    assert grid.breaker_is_closed(BRK_R1) is False
    assert by_name(payload["buses"], grid.BUS_R1_REMOTE)["energized"] is True
    for bus_name in (grid.BUS_SS1_MV, grid.BUS_SS1_LV):
        bus = by_name(payload["buses"], bus_name)
        assert bus["vm_pu"] is None
        assert bus["energized"] is False
        assert bus["quality"] == "NOT_ENERGIZED"
    assert all(
        line["i_ka"] > 0.0
        for line in line_ends(payload, grid.L1_FEEDER_HEAD)
    )
    for line in line_ends(payload, grid.L2_FEEDER_TAIL):
        assert line["i_ka"] == pytest.approx(0.0, abs=1e-12)
        assert line["loading_percent"] == pytest.approx(0.0, abs=1e-12)
        assert line["energized"] is False
        assert line["quality"] == "NOT_ENERGIZED"
    t2 = by_name(payload["transformers"], grid.T2_SS1)
    assert t2["vm_hv_pu"] is None
    assert t2["vm_lv_pu"] is None
    assert t2["energized"] is False
    json.dumps(payload, allow_nan=False)


def test_breaker_access_is_generic_and_rejects_unknown_identity() -> None:
    grid = ReferenceFeederGrid.build(seed=1)

    for breaker_name in (BRK_F1, BRK_R1):
        grid.set_breaker_closed(breaker_name, False)
        assert grid.breaker_is_closed(breaker_name) is False
        grid.set_breaker_closed(breaker_name, True)
        assert grid.breaker_is_closed(breaker_name) is True

    with pytest.raises(ValueError, match="unknown breaker: UNKNOWN"):
        grid.set_breaker_closed("UNKNOWN", False)
    with pytest.raises(ValueError, match="unknown breaker: UNKNOWN"):
        grid.breaker_is_closed("UNKNOWN")


def test_transformer_telemetry_has_identity_endpoints_and_quality() -> None:
    grid = ReferenceFeederGrid.build(seed=1)

    payload = grid.solve()

    for transformer_name in (grid.T1_PRIMARY, grid.T2_SS1):
        transformer = by_name(payload["transformers"], transformer_name)
        assert transformer["transformer_idx"] == grid.transformer_indices[
            transformer_name
        ]
        assert isinstance(transformer["hv_bus"], int)
        assert isinstance(transformer["lv_bus"], int)
        for field in (
            "p_hv_mw",
            "q_hv_mvar",
            "p_lv_mw",
            "q_lv_mvar",
            "i_hv_ka",
            "i_lv_ka",
            "vm_hv_pu",
            "vm_lv_pu",
            "loading_percent",
        ):
            assert transformer[field] is not None
        assert transformer["energized"] is True
        assert transformer["quality"] == "GOOD"
    json.dumps(payload, allow_nan=False)


def test_commands_change_physical_breakers_only_on_control_scan() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)

    assert tuple(simulator.controllers) == (BRK_F1, BRK_R1)
    assert simulator.command_breaker(BRK_R1, "OPEN") is True
    assert grid.breaker_is_closed(BRK_R1) is True

    opened = simulator.control_step(timestamp=0.0)

    assert grid.breaker_is_closed(BRK_F1) is True
    assert grid.breaker_is_closed(BRK_R1) is False
    assert by_name(opened["buses"], grid.BUS_R1_REMOTE)["energized"] is True
    assert by_name(opened["buses"], grid.BUS_SS1_LV)["energized"] is False
    json.dumps(opened, allow_nan=False)
