#!/usr/bin/env python3
"""Turn raw MyIndygo API captures into anonymised test fixtures.

Usage: python tools/anonymize_captures.py <capture dir> <fixture dir>

The capture directory holds the JSON answers of the API for one account, named as written by the
research probe (getUserWithHisModules.json, getPoolStatus_0.json, relay_<id>_status.json, ...).
Serial numbers, module and account ids and MAC addresses are replaced consistently by fake
values (so that relay URLs still match); identity, contact, location, tokens and weather data are
replaced or dropped. Always review the output before committing it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.myindygo.diagnostics import TO_REDACT  # noqa: E402

# Keys whose values are rewritten through the consistent mapping instead of being redacted.
MAPPED_KEYS = {"serialNumber", "name", "msn", "mac", "macAddress", "parent"}
DROPPED_KEYS = {k for k in TO_REDACT if "WeatherForecast" in k}
FAKE_SUFFIXES = ["AAAAAA", "BBBBBB", "CCCCCC", "DDDDDD", "EEEEEE", "FFFFFF"]
MONGO_ID = re.compile(r"\b[0-9a-f]{24}\b")
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")


def build_mapping(modules: list[dict]) -> dict[str, str]:
    """Map each module's serial number, 6-char child id and MAC digits to fake values."""
    mapping: dict[str, str] = {}
    for index, module in enumerate(sorted(modules, key=lambda m: m["serialNumber"])):
        serial = module["serialNumber"]
        child = serial[-10:-4]
        fake_child = FAKE_SUFFIXES[index]
        # Keep the type prefix (first 2-6 hex digits) so the device type is still recognised.
        middle = serial[:-10]
        fake_middle = middle[:6] + "0" * (len(middle) - 6) if len(middle) > 6 else middle
        mapping[serial] = f"{fake_middle}{fake_child}{serial[-4:]}"
        mapping[child] = fake_child
        if len(middle) > 6:  # IPX serials embed the MAC address of the module
            mapping[middle[6:]] = "0" * (len(middle) - 6)
    return mapping


def anonymize(value, mapping: dict[str, str], ids: dict[str, str], key: str | None = None):
    if key in TO_REDACT and key not in MAPPED_KEYS and isinstance(value, dict | list):
        return "REDACTED"  # users, owner, groups, tokens...
    if isinstance(value, dict):
        # Some objects are keyed by ids (e.g. ``configurationChanged``): rewrite keys too.
        return {
            anonymize(k, mapping, ids): anonymize(v, mapping, ids, k)
            for k, v in value.items()
            if k not in DROPPED_KEYS
        }
    if isinstance(value, list):
        return [anonymize(v, mapping, ids, key) for v in value]
    if isinstance(value, str):
        if key in TO_REDACT and key not in MAPPED_KEYS:
            return "REDACTED"
        text = value
        for real, fake in sorted(mapping.items(), key=lambda item: -len(item[0])):
            text = text.replace(real, fake)
        text = MONGO_ID.sub(lambda m: ids.setdefault(m.group(0), f"{len(ids) + 1:024x}"), text)
        text = MAC.sub("00:11:22:33:44:55", text)
        if key == "serialNumber" and text == value:  # a serial we do not know (e.g. electrolyser)
            return "REDACTED"
        return text
    if key in TO_REDACT and key not in MAPPED_KEYS and isinstance(value, int | float) and value is not True:
        return 0
    return value


def main(src: Path, dst: Path) -> None:
    files = {f.stem: json.loads(f.read_text()) for f in sorted(src.glob("*.json"))}
    modules = files["getUserWithHisModules"]["modules"]
    controller = next(m for m in modules if str(m.get("manufacturerType")) == "15")
    child = controller["serialNumber"][-10:-4]
    wanted = {
        "user_with_modules": files["getUserWithHisModules"],
        "pools": files["getUser_pools"].get("pools", []),
        "pool_status": files["getPoolStatus_0"],
        "controller_programs": files[f"getPrograms_{child}"],
        "device_status": files[f"relay_{child}_status"],
        "device_programs": files[f"relay_{child}_programs"],
        "gateway_information": files["relay_gw_information"],
    }
    mapping = build_mapping(modules)
    ids: dict[str, str] = {}
    dst.mkdir(parents=True, exist_ok=True)
    for name, payload in wanted.items():
        clean = anonymize(payload, mapping, ids)
        (dst / f"{name}.json").write_text(
            json.dumps(clean, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
    print(f"wrote {len(wanted)} fixtures to {dst}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
