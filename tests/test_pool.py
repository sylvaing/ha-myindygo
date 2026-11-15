"""Tests for the pool controller decoding helpers."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.myindygo import pool

from .conftest import DEVICE_PROGRAMS, STATUS

MONDAY = date(2026, 11, 16)


@pytest.mark.parametrize(
    ("expression", "raw", "expected"),
    [("x/100.0", 1929, 19.29), ("x", 5, 5.0), (None, 7, 7.0), ("x*0.5", 10, 5.0), ("log(x)", 1, None)],
)
def test_apply_expression(expression, raw, expected) -> None:
    assert pool.apply_expression(expression, raw) == expected


def test_input_value_maps_cloud_index_to_device_index() -> None:
    assert pool.input_value(STATUS, {"index": 1, "expression": "x/100.0"}) == 19.29
    assert pool.input_value(STATUS, {"index": 2, "expression": "x"}) is None  # 2147483647: no sensor
    assert pool.input_value(STATUS, {"index": 5}) is None


@pytest.mark.parametrize(
    ("item", "state"),
    [
        ({"value": 1, "info": ["pgm"]}, "program"),
        ({"value": 0}, "off"),
        ({"value": 1, "origin": 2}, "manual"),
        ({"value": 1, "origin": 3}, "boost"),
        ({"value": 1, "info": ["frostfree"]}, "frost_free"),
        ({"value": 0, "pause": 2}, "paused"),
    ],
)
def test_output_state(item, state) -> None:
    assert pool.output_state(item) == state


def test_remaining_minutes() -> None:
    assert pool.remaining_minutes({"time": "01:30"}) == 90
    assert pool.remaining_minutes({"time": "bad"}) is None
    assert pool.remaining_minutes({}) is None


@pytest.mark.parametrize(
    ("band", "label"), [(0, "< 10 °C"), (4, "16-18 °C"), (11, "≥ 30 °C"), (12, None), (None, None)]
)
def test_temperature_band_label(band, label) -> None:
    assert pool.temperature_band_label(pool.device_program(DEVICE_PROGRAMS, 0), band) == label


@pytest.mark.parametrize(("band", "hours"), [(0, 2), (4, 5), (8, 12), (11, 22)])
def test_planned_minutes_temperature_rule(band, hours) -> None:
    program = pool.device_program(DEVICE_PROGRAMS, 0)
    assert pool.planned_minutes(program, band, MONDAY) == hours * 60


def test_planned_minutes_time_rule() -> None:
    # 08:00-10:00 every day: bits 8 and 9 set in the 12 five-minute columns.
    program = {"programCharacteristics": {"rule": 0}, "sched": [[0b11 << 8] * 12] * 7}
    assert pool.planned_minutes(program, None, MONDAY) == 120


def test_planned_minutes_unsupported() -> None:
    assert (
        pool.planned_minutes({"programCharacteristics": {"rule": 2}, "sched": [[0] * 12] * 7}, 0, MONDAY)
        is None
    )
    assert pool.planned_minutes(None, 0, MONDAY) is None


def test_program_characteristics() -> None:
    program = pool.device_program(DEVICE_PROGRAMS, 1)
    assert pool.program_characteristic(program, "mode", pool.MODES) == "auto"
    assert pool.program_characteristic(program, "programType", pool.DEVICE_PROGRAM_TYPES) == "lighting"
    assert pool.program_characteristic(None, "mode", pool.MODES) is None
