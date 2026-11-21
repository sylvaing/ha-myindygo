"""Program writes of the pool controller: output mode and daily adjustment of the filtration.

A program (one per output) exists twice: the editable copy stored by the platform
(``GET /api/getPrograms``) and the copy compiled in the controller (``sched`` matrix, read through
the device relay). A change is a read-modify-write of both copies, freshly read just before, so
that every field that is not changed is sent back as it was. The sequence follows the MyIndygo app:

1. ``PUT /api/updatePrograms``: the platform copy (the app saves it as soon as the user edits);
2. ``POST /api/module/<gateway SN>/programs/<child id>``: the compiled programs, all outputs at
   once (the app's *Send* button);
3. ``POST /api/reportProgramsDatasSent``: tells the platform that the controller is up to date.

If step 2 fails, the platform keeps the new values while the controller keeps the old ones: this
is the state the app shows as "not transmitted" (its *Send* button retries), and the entities keep
showing what the controller really runs. A failure of step 3 only leaves that flag behind.

Changing the mode does not touch the ``sched`` matrix (the app compiles it independently of the
mode). The daily adjustment (``adaptOffset``, *Standard −4 h … +4 h* in the app) shifts the duration
level of a thermo-adaptive filtration, so the matrix is compiled again like the app does; the
write is refused unless compiling the current platform copy gives exactly the matrix read from the
controller, which proves that the compilation matches this installation.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later

from .api import MyIndygoAuthError, MyIndygoConnectionError
from .const import DOMAIN
from .coordinator import gateway_of
from .pool import MODES, device_program

if TYPE_CHECKING:
    from . import MyIndygoData

_LOGGER = logging.getLogger(__name__)

PROGRAM_TYPE_FILTRATION = 4
RULE_TEMPERATURE = 1
# Daily adjustments offered by the MyIndygo app, in hours (``adaptOffset`` is in minutes).
DAILY_ADJUSTMENT_HOURS = tuple(range(-4, 5))
MODE_VALUES = {name: value for value, name in MODES.items()}

# Delay before reading the programs again after a write, in seconds: the controller receives
# them over the radio link after the relay has answered.
PROGRAM_REFRESH_DELAY = 30

# Top-level fields of a platform program sent back by the app (PoolProgram.jsonIJCEncode).
_PLATFORM_FIELDS = (
    "id",
    "index",
    "name",
    "variableSpeedWindows",
    "temperatureSchedules",
    "programCharacteristics",
    "metadata",
    "temperatureThresholdInactive",
    "temperatureThresholdActive",
    "temperatureHysteresis",
)

_LOCKS: dict[str, asyncio.Lock] = {}


class ProgramError(Exception):
    """A program change that cannot be prepared; ``key`` is the translation key."""

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(detail or key)
        self.key = key


def _programs(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    programs = payload.get("programs") if isinstance(payload, dict) else None
    return [p for p in programs or [] if isinstance(p, dict) and isinstance(p.get("index"), int)]


def _by_index(programs: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    return next((p for p in programs if p.get("index") == index), None)


def _characteristics(program: dict[str, Any] | None) -> dict[str, Any]:
    return (program or {}).get("programCharacteristics") or {}


def _time_inside(minute: int, start: int, end: int) -> bool:
    """Same test as the app (PoolProgram.isTimeInside); a range may span midnight."""
    if start < 0:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def compile_temperature_sched(program: dict[str, Any], adapt_offset: int) -> list[list[int]]:
    """Compile the ``sched`` matrix of a thermo-adaptive program (PoolProgram.matrixify of the app).

    For each day, the first temperature schedule covering it gives, per temperature band
    (column), a duration level shifted by ``adapt_offset / 60`` and clamped; every hour whose
    start falls in one of the level's time ranges sets its bit.
    """
    matrix = [[0] * 12 for _ in range(7)]
    shift = int(adapt_offset / 60)  # Java integer division (towards zero)
    for day in range(7):
        for schedule in program.get("temperatureSchedules") or []:
            if not int(schedule.get("days", 0)) >> day & 1:
                continue
            levels = schedule.get("thresholds") or []
            if levels:
                for column, level in enumerate((schedule.get("indexes") or [])[:12]):
                    level = min(max(int(level) + shift, 0), len(levels) - 1)
                    for time_range in levels[level]:
                        for hour in range(24):
                            if _time_inside(hour * 60, int(time_range["start"]), int(time_range["end"])):
                                matrix[day][column] |= 1 << hour
            break
    return matrix


def platform_payload(program: dict[str, Any]) -> dict[str, Any]:
    """The fields of a platform program as the app sends them to ``updatePrograms``.

    Read-only fields (dates, module, flags) are left out; the time windows are cut at the first
    empty one (``start == -1``), like the app does.
    """
    payload = {key: copy.deepcopy(program[key]) for key in _PLATFORM_FIELDS if key in program}
    windows = []
    for window in program.get("windows") or []:
        if not isinstance(window, dict) or window.get("start", -1) == -1:
            break
        windows.append(copy.deepcopy(window))
    payload["windows"] = windows
    return payload


def device_payload(program: dict[str, Any]) -> dict[str, Any]:
    """The fields of a compiled program as the app writes them to the controller."""
    return {
        "index": program["index"],
        "name": program.get("name", ""),
        "programCharacteristics": copy.deepcopy(_characteristics(program)),
        "sched": copy.deepcopy(program.get("sched") or []),
    }


def current_adapt_offset(program: dict[str, Any] | None) -> int:
    """Daily adjustment of a platform program, in minutes (0 when absent, like the app)."""
    value = _characteristics(program).get("adaptOffset")
    return value if isinstance(value, int) else 0


def daily_adjustment_supported(platform: dict[str, Any] | None, device: dict[str, Any] | None) -> bool:
    """True for a thermo-adaptive filtration program, the only one the adjustment applies to."""
    characteristics = _characteristics(device)
    return (
        characteristics.get("programType") == PROGRAM_TYPE_FILTRATION
        and characteristics.get("rule") == RULE_TEMPERATURE
        and _characteristics(platform).get("rule") == RULE_TEMPERATURE
        and bool((platform or {}).get("temperatureSchedules"))
    )


def build_program_change(
    platform: dict[str, Any] | None,
    device: dict[str, Any] | None,
    index: int,
    *,
    mode: int | None = None,
    adapt_offset: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Return the new platform and device programs (all outputs), or None when nothing changes.

    Only the requested fields of program ``index`` differ from the copies read.
    """
    platform_programs = copy.deepcopy(sorted(_programs(platform), key=lambda p: p["index"]))
    device_programs = copy.deepcopy(sorted(_programs(device), key=lambda p: p["index"]))
    if not device_programs or [p["index"] for p in platform_programs] != [
        p["index"] for p in device_programs
    ]:
        raise ProgramError("program_copies_differ", "the platform and controller programs do not match")
    if [p["index"] for p in device_programs] != list(range(len(device_programs))):
        raise ProgramError("program_copies_differ", "unexpected program indexes")
    target_platform = _by_index(platform_programs, index)
    target_device = _by_index(device_programs, index)
    if target_platform is None or target_device is None:
        raise ProgramError("program_copies_differ", f"no program for output {index}")

    changed = False
    if mode is not None and _characteristics(target_device).get("mode") != mode:
        target_platform.setdefault("programCharacteristics", {})["mode"] = mode
        target_device.setdefault("programCharacteristics", {})["mode"] = mode
        changed = True

    if adapt_offset is not None:
        if not daily_adjustment_supported(target_platform, target_device):
            raise ProgramError("daily_adjustment_not_supported")
        current = current_adapt_offset(target_platform)
        if compile_temperature_sched(target_platform, current) != target_device.get("sched"):
            raise ProgramError("program_sched_mismatch")
        if adapt_offset != current:
            target_platform.setdefault("programCharacteristics", {})["adaptOffset"] = adapt_offset
            target_device["sched"] = compile_temperature_sched(target_platform, adapt_offset)
            changed = True

    return (platform_programs, device_programs) if changed else None


async def async_write_program(
    hass: HomeAssistant,
    data: MyIndygoData,
    module_id: str,
    index: int,
    *,
    mode: int | None = None,
    adapt_offset: int | None = None,
) -> None:
    """Change the mode and/or the daily adjustment of one output program of a pool controller."""
    cloud = data.cloud.data
    module = cloud.modules.get(module_id) if cloud else None
    gateway = gateway_of(module, cloud.modules) if cloud and module else None
    if module is None or gateway is None:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_gateway")

    async with _LOCKS.setdefault(module_id, asyncio.Lock()):
        with _errors(data, hass, "program_read_failed"):
            platform = await data.client.async_get_programs(module_id)
            device = await data.client.async_get_device(
                gateway["serialNumber"], "programs", module["serialNumber"]
            )
        try:
            change = build_program_change(platform, device, index, mode=mode, adapt_offset=adapt_offset)
        except ProgramError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=err.key,
                translation_placeholders={"error": str(err)},
            ) from err
        if change is None:
            _LOGGER.debug("Program %s of %s already up to date", index, module.get("name"))
            return
        platform_programs, device_programs = change

        _LOGGER.debug(
            "Writing program %s of %s (mode %s, offset %s)", index, module.get("name"), mode, adapt_offset
        )
        with _errors(data, hass, "program_save_failed"):
            await data.client.async_update_programs(
                module_id, [platform_payload(p) for p in platform_programs]
            )
        with _errors(data, hass, "program_send_failed"):
            await data.client.async_write_device_programs(
                gateway["serialNumber"], module["serialNumber"], [device_payload(p) for p in device_programs]
            )
        ids = [p["id"] for p in platform_programs if p.get("id")]
        try:
            await data.client.async_report_programs_sent(module_id, ids)
        except (MyIndygoAuthError, MyIndygoConnectionError) as err:
            # The controller and the platform are up to date; only the "sent" date is missing,
            # so the app may offer to send the same programs again.
            _LOGGER.warning(
                "Programs of %s written, but the report to the platform failed: %s", module.get("name"), err
            )

    _store(data, module_id, platform, platform_programs, device, device_programs)
    expected = _by_index(device_programs, index) or {}

    async def _refresh(_now: Any) -> None:
        await data.cloud.async_refresh()
        if not data.cloud.last_update_success or data.cloud.data is None:
            return
        current = device_program(data.cloud.data.device_programs.get(module_id), index)
        if current is None:
            return
        if _characteristics(current).get("mode") != _characteristics(expected).get("mode") or current.get(
            "sched"
        ) != expected.get("sched"):
            _LOGGER.warning(
                "The programs read from %s after the write do not show the change of output %s yet",
                module.get("name"),
                index,
            )

    data.cloud.config_entry.async_on_unload(async_call_later(hass, PROGRAM_REFRESH_DELAY, _refresh))


def _store(
    data: MyIndygoData,
    module_id: str,
    platform: dict[str, Any],
    platform_programs: list[dict[str, Any]],
    device: dict[str, Any],
    device_programs: list[dict[str, Any]],
) -> None:
    """Show the written programs at once; the delayed refresh reads them back."""
    cloud = data.cloud.data
    cloud.programs[module_id] = {**platform, "programs": platform_programs}
    cloud.device_programs[module_id] = {**device, "programs": device_programs}
    data.cloud.async_update_listeners()


@contextmanager
def _errors(data: MyIndygoData, hass: HomeAssistant, key: str) -> Iterator[None]:
    """Map the client errors of one step to a translated Home Assistant error."""
    try:
        yield
    except MyIndygoAuthError as err:
        data.cloud.config_entry.async_start_reauth(hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except MyIndygoConnectionError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"error": str(err)},
        ) from err
