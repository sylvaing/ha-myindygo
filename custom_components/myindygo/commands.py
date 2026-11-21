"""Manual commands of the pool controller outputs: forced run, boost, pause and stop.

The commands are entity actions of the ``myindygo`` domain, targeting the binary sensor of an
output (``Filtration``, ``Output 1``…). They are sent through the device relay
(``POST /api/module/<gateway SN>/manual/<child id>``) with the ``pool`` body of the device API:

=========================  =====================================================
Action                     Body
=========================  =====================================================
``start_manual_run``       ``{"index": i, "action": 2, "manualDuration": <s>}``
``start_boost``            ``{"index": i, "action": 3, "time": "HH:MM"}``
``pause``                  ``{"index": i, "action": 5, "manualDuration": <days>}``
``stop_manual_command``    ``{"index": i, "action": 1}``
=========================  =====================================================

The controller silently ignores a command on an output whose program is not in mode ``auto``
(verified on a real controller), and the MyIndygo app only offers boost for the filtration and
treatment outputs: these cases are refused before anything is sent. The relay answers before the
radio exchange with the controller, so the status is read again a few seconds later and a warning
is logged when the command had no visible effect.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.entity import Entity

from .api import MyIndygoAuthError, MyIndygoConnectionError
from .const import DOMAIN
from .coordinator import gateway_of
from .pool import MODES, device_program, output_state, output_status

if TYPE_CHECKING:
    from . import MyIndygoData

_LOGGER = logging.getLogger(__name__)

# ``action`` codes of the ``manual`` endpoint for a pool product (URLManual of the app).
ACTION_STOP = 1
ACTION_MANUAL_RUN = 2
ACTION_BOOST = 3
ACTION_PAUSE = 5

# Program types (same value in the controller and on the platform) for which the app offers boost.
BOOST_PROGRAM_TYPES = {4: "filtration", 5: "treatment"}

SERVICE_START_MANUAL_RUN = "start_manual_run"
SERVICE_START_BOOST = "start_boost"
SERVICE_PAUSE = "pause"
SERVICE_STOP_MANUAL_COMMAND = "stop_manual_command"

ATTR_DURATION = "duration"
ATTR_DAYS = "days"

MIN_DURATION = timedelta(minutes=1)
MAX_DURATION = timedelta(hours=24)
MAX_PAUSE_DAYS = 30

DURATION_SCHEMA = vol.All(cv.time_period, vol.Range(min=MIN_DURATION, max=MAX_DURATION))


@dataclass(frozen=True)
class OutputCommand:
    """A manual command for one output, with the state it should lead to."""

    name: str
    body: dict[str, Any]
    expected_states: frozenset[str]

    @property
    def index(self) -> int:
        return int(self.body["index"])

    @property
    def action(self) -> int:
        return int(self.body["action"])


def manual_run(index: int, duration: timedelta) -> OutputCommand:
    """Forced run for ``duration`` (sent in seconds)."""
    body = {"index": index, "action": ACTION_MANUAL_RUN, "manualDuration": int(duration.total_seconds())}
    return OutputCommand(SERVICE_START_MANUAL_RUN, body, frozenset({"manual"}))


def boost(index: int, duration: timedelta) -> OutputCommand:
    """Boost for ``duration``, sent as ``HH:MM`` (seconds are dropped)."""
    hours, minutes = divmod(int(duration.total_seconds()) // 60, 60)
    body = {"index": index, "action": ACTION_BOOST, "time": f"{hours:02d}:{minutes:02d}"}
    return OutputCommand(SERVICE_START_BOOST, body, frozenset({"boost"}))


def pause(index: int, days: int) -> OutputCommand:
    """Pause the output (its program included) for a number of days."""
    body = {"index": index, "action": ACTION_PAUSE, "manualDuration": days}
    return OutputCommand(SERVICE_PAUSE, body, frozenset({"paused"}))


def stop(index: int) -> OutputCommand:
    """End the current manual command: the output goes back to its program."""
    body = {"index": index, "action": ACTION_STOP}
    return OutputCommand(SERVICE_STOP_MANUAL_COMMAND, body, frozenset({"off", "program", "frost_free"}))


def program_value(index: int, key: str, *program_sets: dict[str, Any] | None) -> int | None:
    """First known characteristic of an output program: compiled in the controller, then platform."""
    for programs in program_sets:
        value = ((device_program(programs, index) or {}).get("programCharacteristics") or {}).get(key)
        if isinstance(value, int):
            return value
    return None


class OutputCommandEntity(Entity):
    """Entity of a controller output, target of the command actions."""

    module_id: str
    output_index: int
    _data: MyIndygoData

    async def async_send_output_command(self, command: OutputCommand) -> None:
        """Validate and send a command to this output."""
        await async_send_command(self.hass, self._data, self.module_id, command)


async def async_send_command(
    hass: HomeAssistant, data: MyIndygoData, module_id: str, command: OutputCommand
) -> None:
    """Send a manual command to an output of a pool controller and schedule a status re-read."""
    cloud = data.cloud.data
    module = cloud.modules.get(module_id) if cloud else None
    gateway = gateway_of(module, cloud.modules) if cloud and module else None
    if module is None or gateway is None:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_gateway")

    program_sets = (cloud.device_programs.get(module_id), cloud.programs.get(module_id))
    if command.action != ACTION_STOP:
        mode = program_value(command.index, "mode", *program_sets)
        # Unknown mode (programs not read yet): send anyway, the status re-read will tell.
        if mode is not None and MODES.get(mode) != "auto":
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="output_not_auto",
                translation_placeholders={"mode": MODES.get(mode, str(mode))},
            )
    if command.action == ACTION_BOOST:
        program_type = program_value(command.index, "programType", *program_sets)
        if program_type is not None and program_type not in BOOST_PROGRAM_TYPES:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="boost_not_supported")

    _LOGGER.debug("Sending %s to %s: %s", command.name, module.get("name"), command.body)
    try:
        status = await data.client.async_send_manual_command(
            gateway["serialNumber"], module["serialNumber"], command.body
        )
    except MyIndygoAuthError as err:
        data.cloud.config_entry.async_start_reauth(hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except MyIndygoConnectionError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    if isinstance(status.get("pool"), list):
        data.live.async_set_controller_status(module_id, status)
    data.live.async_schedule_command_refresh(partial(_check_applied, data, module_id, command))


@callback
def _check_applied(data: MyIndygoData, module_id: str, command: OutputCommand) -> None:
    """Log when the re-read status does not show the effect of a command."""
    status = (data.live.data or {}).get(module_id)
    if status is None:
        return
    item = output_status(status, command.index)
    state = output_state(item) if item else None
    if state in command.expected_states:
        _LOGGER.debug("%s on output %s applied (state %s)", command.name, command.index, state)
        return
    if "cmd" in (status.get("radio") or []):
        _LOGGER.warning(
            "%s on output %s is still waiting for the radio link with the controller",
            command.name,
            command.index,
        )
        return
    _LOGGER.warning(
        "%s on output %s had no visible effect: the controller reports the state %s",
        command.name,
        command.index,
        state,
    )


def _entity_action(
    build: Callable[[int, dict[str, Any]], OutputCommand],
) -> Callable[[Entity, ServiceCall], Awaitable[None]]:
    async def handle(entity: Entity, call: ServiceCall) -> None:
        if not isinstance(entity, OutputCommandEntity):
            # Targeting a whole device or area also selects other binary sensors: skip them,
            # but tell the user when one was picked explicitly.
            if entity.entity_id in cv.ensure_list(call.data.get(ATTR_ENTITY_ID)):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_an_output",
                    translation_placeholders={"entity_id": entity.entity_id},
                )
            return
        await entity.async_send_output_command(build(entity.output_index, call.data))

    return handle


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the entity actions of the controller outputs."""
    actions: list[tuple[str, dict[Any, Any], Callable[[int, dict[str, Any]], OutputCommand]]] = [
        (
            SERVICE_START_MANUAL_RUN,
            {vol.Required(ATTR_DURATION): DURATION_SCHEMA},
            lambda index, data: manual_run(index, data[ATTR_DURATION]),
        ),
        (
            SERVICE_START_BOOST,
            {vol.Required(ATTR_DURATION): DURATION_SCHEMA},
            lambda index, data: boost(index, data[ATTR_DURATION]),
        ),
        (
            SERVICE_PAUSE,
            {vol.Required(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_PAUSE_DAYS))},
            lambda index, data: pause(index, data[ATTR_DAYS]),
        ),
        (SERVICE_STOP_MANUAL_COMMAND, {}, lambda index, _data: stop(index)),
    ]
    for name, schema, build in actions:
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=BINARY_SENSOR_DOMAIN,
            schema=schema,
            func=_entity_action(build),
        )
