"""Decoding helpers for the pool controller (LR-PC) data.

Pure functions, without Home Assistant dependencies, so they are easy to test against captures.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Raw value reported for an input without a sensor.
INVALID_RAW_VALUE = 2147483647

# Cloud input types measuring a temperature (Input.SensorType of the app).
TEMPERATURE_INPUT_TYPES = {4, 5, 133}  # analog, PT100, PT100 provided by an external probe
UNIT_CELSIUS = 2

MODES = {0: "off", 1: "on", 2: "auto"}
RULES = {0: "time", 1: "temperature", 2: "variable_speed"}
# Program type as stored in the controller (lighting and generic auxiliary are swapped
# compared to the platform values).
DEVICE_PROGRAM_TYPES = {
    2: "auxiliary",
    4: "filtration",
    5: "treatment",
    6: "robot",
    7: "heat_pump",
    8: "lighting",
    9: "backwash",
    11: "pulse",
}

OUTPUT_STATES = ["off", "program", "manual", "boost", "frost_free", "paused"]

_EXPRESSION = re.compile(r"^\s*x\s*(?:([*/])\s*([0-9]+(?:\.[0-9]+)?))?\s*$")


def apply_expression(expression: str | None, raw: float) -> float | None:
    """Convert a raw value with the platform expression (``x``, ``x/100.0``, ``x*0.1``).

    Only these simple forms are supported; anything else returns None rather than guessing.
    """
    match = _EXPRESSION.match(expression or "x")
    if not match:
        return None
    operator, operand = match.groups()
    if operator is None:
        return float(raw)
    value = float(operand)
    if operator == "/":
        return raw / value if value else None
    return raw * value


def temperature_inputs(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the cloud inputs of a controller that measure a temperature in °C."""
    return [
        item
        for item in module.get("inputs", [])
        if item.get("type") in TEMPERATURE_INPUT_TYPES and item.get("unit") == UNIT_CELSIUS
    ]


def input_value(status: dict[str, Any], cloud_input: dict[str, Any]) -> float | None:
    """Return the converted value of a cloud input from the device status.

    Cloud input indexes start at 1, device ``sensorState`` indexes at 0.
    """
    device_index = int(cloud_input.get("index", 1)) - 1
    for state in status.get("sensorState", []):
        if state.get("index") == device_index:
            raw = state.get("value")
            if raw is None or raw == INVALID_RAW_VALUE:
                return None
            value = apply_expression(cloud_input.get("expression"), raw)
            return round(value, 2) if value is not None else None
    return None


def output_status(status: dict[str, Any], index: int) -> dict[str, Any] | None:
    """Return the status entry of an output, if reported."""
    return next((item for item in status.get("pool", []) if item.get("index") == index), None)


def output_state(item: dict[str, Any]) -> str:
    """Why an output is in its current state: off, program, manual, boost, frost_free, paused."""
    if item.get("pause"):
        return "paused"
    if not item.get("value"):
        return "off"
    if item.get("origin") == 3:
        return "boost"
    if item.get("origin") == 2:
        return "manual"
    if "frostfree" in (item.get("info") or []):
        return "frost_free"
    return "program"


def remaining_minutes(item: dict[str, Any]) -> int | None:
    """Remaining time of the current run, from ``time`` (``HH:MM``)."""
    text = item.get("time")
    if not isinstance(text, str) or ":" not in text:
        return None
    hours, _, minutes = text.partition(":")
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return None


def device_program(device_programs: dict[str, Any] | None, index: int) -> dict[str, Any] | None:
    """Return the compiled program of an output."""
    for program in (device_programs or {}).get("programs", []):
        if program.get("index") == index:
            return program
    return None


def program_characteristic(program: dict[str, Any] | None, key: str, names: dict[int, str]) -> str | None:
    """Return a named characteristic (mode, rule, type) of a compiled program."""
    if not program:
        return None
    return names.get((program.get("programCharacteristics") or {}).get(key))


def temperature_band_label(program: dict[str, Any] | None, band: int | None) -> str | None:
    """Label of a temperature band of a thermo-adaptive program, e.g. ``16-18 °C``."""
    if program is None or band is None:
        return None
    thresholds = [t for t in (program.get("programCharacteristics") or {}).get("ths", []) if t != 127]
    if not thresholds or not 0 <= band <= len(thresholds):
        return None
    if band == 0:
        return f"< {thresholds[0]} °C"
    if band == len(thresholds):
        return f"≥ {thresholds[-1]} °C"
    return f"{thresholds[band - 1]}-{thresholds[band]} °C"


def planned_minutes(program: dict[str, Any] | None, band: int | None, day: date) -> int | None:
    """Planned running time of an output for a day, decoded from the compiled ``sched`` matrix.

    ``sched[weekday][column]`` holds 24-bit hour masks (row 0 = Monday). With the temperature
    rule a column is a temperature band and a bit is one hour; with the time rule a column is a
    5-minute slot of every hour. Variable speed programs are not decoded.
    """
    if program is None:
        return None
    rule = (program.get("programCharacteristics") or {}).get("rule")
    sched = program.get("sched") or []
    if len(sched) != 7:
        return None
    row = sched[day.weekday()]
    if rule == 1:
        if band is None or not 0 <= band < len(row):
            return None
        return bin(row[band]).count("1") * 60
    if rule == 0:
        return sum(bin(mask).count("1") for mask in row) * 5
    return None
