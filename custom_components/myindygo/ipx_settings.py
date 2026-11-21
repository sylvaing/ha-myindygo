"""Settings of the IPX PoolTech electrolyser: pH mode and setpoint, electrolysis mode, production, boost.

A setting is written to the platform with ``POST /api/outputs/<output id>/ipxData`` and the body
``{"ipxData": {<key>: <value>}}``, one key per request like the MyIndygo app. The platform does
not apply it at once: it stores it in ``outputs[n].pendingIpxData`` and hands it over to the
electrolyser (gateway -> pool controller -> Bluetooth) at the next IPX exchange, about every 10-15
minutes while the filtration runs. Only then does ``pendingIpxData`` empty and ``ipxData`` carry
the new value: this is the only acknowledgement.

So the entities keep showing the value reported by the electrolyser and expose the requested one
as pending (``pending_value`` attribute, ``Settings pending`` binary sensor). Once the request
leaves ``pendingIpxData``, the reported value tells whether it was applied; a warning is logged
when it was not, or when it is still pending after ``PENDING_WARNING_DELAY``.

The safety rules of the app are reproduced before anything is sent: no change while the
filtration is stopped, the pH setpoint only with pH regulation on, the production setpoint only in
percentage mode, no boost while the electrolyser is wintering, and the app's ranges and steps.

The keys, ranges and steps come from the MyIndygo Android app; writing has not been tested on a
real electrolyser yet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from .api import MyIndygoAuthError, MyIndygoConnectionError, MyIndygoError
from .const import DOMAIN
from .electrolyser import OUTPUT_ELECTROLYZER, ElectrolyserEntity
from .pool import output_status

if TYPE_CHECKING:
    from . import MyIndygoData

_LOGGER = logging.getLogger(__name__)

KEY_PH_MODE = "pHMode"
KEY_PH_SETPOINT = "pHSetpoint"
KEY_ELECTROLYZER_MODE = "electrolyzerMode"
KEY_PERCENTAGE_SETPOINT = "percentageSetpoint"
KEY_BOOST_COMMAND = "boostCommand"

PH_MODE_ON = 1
ELECTROLYZER_MODE_PERCENTAGE = 1

# Ranges and steps of the app (PoolTech.PHMode / ElectrolyzerMode, PoolTechOutputActivity).
PH_SETPOINT_MIN = 6.8
PH_SETPOINT_MAX = 7.6
PH_SETPOINT_STEP = 0.1
PRODUCTION_MIN = 0
PRODUCTION_MAX = 100
# Electrolysers whose configuration code has a "3" as second digit only accept multiples of 5.
PRODUCTION_STEP_COARSE = 5

# PoolTech.BoostCommand of the app: 0 stops the current boost.
BOOST_COMMANDS = (0, 12, 24)

# Output of the pool controller driving the filtration pump.
FILTRATION_OUTPUT = 0

# A request still pending after this delay is logged (the electrolyser reports every 10-15 min).
PENDING_WARNING_DELAY = timedelta(minutes=30)


def ipx_output(module: dict[str, Any], output_type: int) -> dict[str, Any] | None:
    """Return the output object (with ``id``, ``ipxData`` and ``pendingIpxData``) of a type."""
    for output in module.get("outputs", []):
        if (output.get("ipxData") or {}).get("type") == output_type:
            return output
    return None


def pending_value(module: dict[str, Any], output_type: int, key: str) -> Any:
    """Requested value not yet picked up by the electrolyser, if any."""
    output = ipx_output(module, output_type) or {}
    return (output.get("pendingIpxData") or {}).get(key)


def reported_value(module: dict[str, Any], output_type: int, key: str) -> Any:
    """Value reported by the electrolyser."""
    return ((ipx_output(module, output_type) or {}).get("ipxData") or {}).get(key)


def effective_value(module: dict[str, Any], output_type: int, key: str) -> Any:
    """Requested value if one is pending, else the reported one (what the app displays)."""
    pending = pending_value(module, output_type, key)
    return pending if pending is not None else reported_value(module, output_type, key)


def all_pending(module: dict[str, Any]) -> dict[str, Any]:
    """Every pending request of the electrolyser, merged across its outputs."""
    found: dict[str, Any] = {}
    for output in module.get("outputs", []):
        found.update(output.get("pendingIpxData") or {})
    return found


def production_step(module: dict[str, Any]) -> int:
    """Step of the production setpoint: 5 when the configuration code's second digit is 3."""
    code = str((module.get("ipxData") or {}).get("configurationCode") or "")
    return PRODUCTION_STEP_COARSE if len(code) > 1 and code[1] == "3" else 1


def is_wintered(module: dict[str, Any]) -> bool:
    return bool(reported_value(module, OUTPUT_ELECTROLYZER, "isWintered"))


def filtration_running(data: MyIndygoData, module: dict[str, Any]) -> bool | None:
    """Running state of the filtration of the pool controller relaying the electrolyser."""
    status = (data.live.data or {}).get(module.get("ipxRelay") or "")
    item = output_status(status or {}, FILTRATION_OUTPUT)
    return bool(item.get("value")) if item else None


def validate(module: dict[str, Any], output_type: int, key: str, value: Any) -> Any:
    """Check a setting against the rules of the app; return the value to send."""
    if key == KEY_PH_SETPOINT:
        rounded = round(float(value), 1)
        if abs(rounded - float(value)) > 1e-6 or not PH_SETPOINT_MIN <= rounded <= PH_SETPOINT_MAX:
            raise _invalid(value)
        if effective_value(module, output_type, KEY_PH_MODE) != PH_MODE_ON:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="ph_regulation_off")
        return rounded
    if key == KEY_PERCENTAGE_SETPOINT:
        if float(value) != int(value) or not PRODUCTION_MIN <= int(value) <= PRODUCTION_MAX:
            raise _invalid(value)
        if int(value) % production_step(module):
            raise _invalid(value)
        if effective_value(module, output_type, KEY_ELECTROLYZER_MODE) != ELECTROLYZER_MODE_PERCENTAGE:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="production_not_percentage"
            )
        return int(value)
    if key == KEY_BOOST_COMMAND:
        if value not in BOOST_COMMANDS:
            raise _invalid(value)
        if is_wintered(module):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="boost_wintering")
        return value
    if key in (KEY_PH_MODE, KEY_ELECTROLYZER_MODE):
        allowed = (0, PH_MODE_ON) if key == KEY_PH_MODE else (0, ELECTROLYZER_MODE_PERCENTAGE)
        if value not in allowed:
            raise _invalid(value)
        return value
    raise _invalid(value)  # pragma: no cover


def _invalid(value: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_setting",
        translation_placeholders={"value": str(value)},
    )


@dataclass
class PendingRequest:
    """A setting sent by this entity, followed until the electrolyser reports it."""

    key: str
    value: Any
    applied: Callable[[dict[str, Any]], bool | None]
    sent_at: datetime
    report_at_send: Any
    warned: bool = False


class IpxSettingEntity(ElectrolyserEntity):
    """Electrolyser entity that writes one setting of one output."""

    _output_type: int
    _key: str
    _request: PendingRequest | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        module = self.current_module
        pending = pending_value(module, self._output_type, self._key) if module else None
        return {"pending_value": pending}

    async def async_write_setting(
        self, value: Any, applied: Callable[[dict[str, Any]], bool | None] | None = None
    ) -> None:
        """Validate and send a setting; it then shows as pending until the electrolyser takes it."""
        module = self.current_module
        output = ipx_output(module, self._output_type) if module else None
        if module is None or output is None or not output.get("id"):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_ipx_output")
        value = validate(module, self._output_type, self._key, value)
        if self._key != KEY_BOOST_COMMAND and effective_value(module, self._output_type, self._key) == value:
            _LOGGER.debug("%s of %s is already %s: nothing sent", self._key, module.get("name"), value)
            return
        running = filtration_running(self._data, module)
        if running is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="filtration_stopped" if running is False else "filtration_unknown",
            )

        _LOGGER.debug("Sending %s=%s to %s", self._key, value, module.get("name"))
        try:
            await self._data.client.async_send_ipx_data(output["id"], {self._key: value})
        except MyIndygoAuthError as err:
            self._data.cloud.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
        except MyIndygoConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        # Like the app, record the request as pending right away; the platform's own view
        # replaces it as soon as the module is read again.
        output.setdefault("pendingIpxData", {})[self._key] = value
        await async_reread_module(self._data, self.module_id)
        self._request = PendingRequest(
            key=self._key,
            value=value,
            applied=applied or (lambda m: _same(reported_value(m, self._output_type, self._key), value)),
            sent_at=dt_util.utcnow(),
            report_at_send=module.get("lastIpxCommunication"),
        )
        self._data.cloud.async_update_listeners()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._check_request()
        super()._handle_coordinator_update()

    def _check_request(self) -> None:
        request = self._request
        module = self.current_module
        if request is None or module is None:
            return
        name = module.get("name")
        pending = all_pending(module)
        if request.key in pending and pending[request.key] != request.value:
            # Replaced by a newer request (another boost button, the app…): nothing to follow.
            self._request = None
            return
        if request.key in pending:
            if not request.warned and dt_util.utcnow() - request.sent_at > PENDING_WARNING_DELAY:
                request.warned = True
                _LOGGER.warning(
                    "%s=%s for %s is still waiting for the electrolyser after %s min; it only takes "
                    "settings while the filtration runs",
                    request.key,
                    request.value,
                    name,
                    int(PENDING_WARNING_DELAY.total_seconds() // 60),
                )
            return
        if request.applied(module):
            _LOGGER.debug("%s=%s applied by %s", request.key, request.value, name)
            self._request = None
        elif module.get("lastIpxCommunication") != request.report_at_send:
            _LOGGER.warning(
                "%s=%s was not applied by %s: it reports %s",
                request.key,
                request.value,
                name,
                reported_value(module, self._output_type, request.key)
                if request.key != KEY_BOOST_COMMAND
                else reported_value(module, self._output_type, "boostEnabled"),
            )
            self._request = None


def _same(reported: Any, requested: Any) -> bool:
    if isinstance(reported, int | float) and isinstance(requested, int | float):
        return round(float(reported), 1) == round(float(requested), 1)
    return reported == requested


async def async_reread_module(data: MyIndygoData, module_id: str) -> None:
    """Read the electrolyser again to show the platform's view of the pending settings.

    Only ``ipxData`` and ``pendingIpxData`` of the outputs are taken from the answer; a failure
    keeps the locally recorded request. The listeners are not notified here.
    """
    cloud = data.cloud.data
    module = cloud.modules.get(module_id) if cloud else None
    if module is None:
        return
    try:
        fresh = await data.client.async_get_module(module_id)
    except MyIndygoError as err:
        _LOGGER.debug("Cannot read %s again after a setting: %s", module.get("name"), err)
    else:
        if isinstance(fresh, dict) and fresh.get("id") == module_id:
            by_id = {output.get("id"): output for output in fresh.get("outputs") or []}
            for output in module.get("outputs", []):
                update = by_id.get(output.get("id"))
                if update is None:
                    continue
                for key in ("ipxData", "pendingIpxData"):
                    if isinstance(update.get(key), dict):
                        output[key] = update[key]
            if fresh.get("lastIpxCommunication"):
                module["lastIpxCommunication"] = fresh["lastIpxCommunication"]
