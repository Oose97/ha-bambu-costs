"""Config and options flow for Bambu Print Costs.

Nothing about the printer is hard-coded: every entity the integration reads is
chosen here, and the per-slot filament sources are free-form so any AMS layout
(or none at all) works.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .discovery import discover
from .const import (
    CONF_AUTO_LOG,
    CONF_CAMERA,
    CONF_COVER_IMAGE,
    CONF_CURRENCY,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_END_TIME,
    CONF_ENERGY_SENSORS,
    CONF_LAYERS,
    CONF_LENGTH,
    CONF_NOZZLE_SIZE,
    CONF_NOZZLE_TYPE,
    CONF_POWER_SENSORS,
    CONF_PRINT_STATUS,
    CONF_PRINT_WEIGHT,
    CONF_SLOTS,
    CONF_START_TIME,
    CONF_TASK_NAME,
    DEFAULT_CURRENCY,
    DEFAULT_ELECTRICITY_PRICE,
    DEFAULT_FILAMENT_PRICE,
    DEFAULT_NAME,
    DOMAIN,
    PRINTER_MANUFACTURER,
)

_SENSOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
_SENSOR_OPT = EntitySelector(EntitySelectorConfig(domain="sensor"))
_IMAGE = EntitySelector(EntitySelectorConfig(domain=["image", "camera"]))
_CAMERA = EntitySelector(EntitySelectorConfig(domain="camera"))
_ENERGY = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
)
_POWER = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
)
_SLOTS = TextSelector(TextSelectorConfig(multiple=True))
# Narrowed by manufacturer rather than by integration, so a fork or a rename of
# ha-bambulab still lists — every one of them registers its devices under the
# same brand. Discovery only recognises printer sensors, so offering the whole
# device registry was offering hundreds of devices that cannot work.
#
# AMS units are listed alongside the printer, since they carry the same brand.
# That is fine: they hang off the printer via ``via_device``, and discovery
# walks up that link, so picking one discovers its printer.
_DEVICE = DeviceSelector(DeviceSelectorConfig(manufacturer=PRINTER_MANUFACTURER))
CONF_DEVICE = "device"

# Every key the flow can set. Options are written in full on each save so that
# clearing an optional entity actually clears it, instead of the original setup
# value showing through the merge.
ALL_KEYS = (
    CONF_PRINT_WEIGHT,
    CONF_PRINT_STATUS,
    CONF_TASK_NAME,
    CONF_LAYERS,
    CONF_LENGTH,
    CONF_NOZZLE_SIZE,
    CONF_NOZZLE_TYPE,
    CONF_COVER_IMAGE,
    CONF_CAMERA,
    CONF_START_TIME,
    CONF_END_TIME,
    CONF_SLOTS,
    CONF_ENERGY_SENSORS,
    CONF_POWER_SENSORS,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_ELECTRICITY_PRICE,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_CURRENCY,
    CONF_AUTO_LOG,
    # Kept so reconfiguring can show which printer was chosen. Nothing reads it
    # at runtime — the entities picked from it are what the integration uses.
    CONF_DEVICE,
)


def _device_from_entities(hass: HomeAssistant, current: dict[str, Any]) -> str | None:
    """The printer device inferred from the entities already configured.

    Entries created before the device id was stored have every sensor but no
    device key, so the options flow's device box came up empty until the
    printer was picked again by hand. The sensors know which device they
    belong to, and the status and weight sensors live on the printer itself —
    so the registry can answer instead of the user.
    """
    registry = er.async_get(hass)
    for key in (CONF_PRINT_STATUS, CONF_PRINT_WEIGHT):
        entity_id = current.get(key)
        entry = registry.async_get(entity_id) if entity_id else None
        if entry and entry.device_id:
            return entry.device_id
    return None


def _price(maximum: float) -> NumberSelector:
    """A free-precision price box.

    HA rejects any numeric ``step`` below 0.001, so a rate like 0.0008 EUR
    cannot be expressed that way. ``"any"`` drops the constraint entirely and
    lets the field carry as many decimals as the price needs.
    """
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=maximum,
            step="any",  # type: ignore[typeddict-item]
            mode=NumberSelectorMode.BOX,
        )
    )


def _printer_schema(defaults: dict[str, Any]) -> vol.Schema:
    def dflt(key: str, fallback: Any = None) -> Any:
        value = defaults.get(key, fallback)
        return {"suggested_value": value} if value not in (None, "", []) else {}

    return vol.Schema(
        {
            vol.Required("name", description=dflt("name", DEFAULT_NAME)): str,
            vol.Required(CONF_PRINT_WEIGHT, description=dflt(CONF_PRINT_WEIGHT)): _SENSOR,
            vol.Required(CONF_PRINT_STATUS, description=dflt(CONF_PRINT_STATUS)): _SENSOR,
            vol.Optional(CONF_TASK_NAME, description=dflt(CONF_TASK_NAME)): _SENSOR_OPT,
            vol.Optional(CONF_LAYERS, description=dflt(CONF_LAYERS)): _SENSOR_OPT,
            vol.Optional(CONF_LENGTH, description=dflt(CONF_LENGTH)): _SENSOR_OPT,
            vol.Optional(CONF_NOZZLE_SIZE, description=dflt(CONF_NOZZLE_SIZE)): _SENSOR_OPT,
            vol.Optional(CONF_NOZZLE_TYPE, description=dflt(CONF_NOZZLE_TYPE)): _SENSOR_OPT,
            vol.Optional(CONF_COVER_IMAGE, description=dflt(CONF_COVER_IMAGE)): _IMAGE,
            vol.Optional(CONF_CAMERA, description=dflt(CONF_CAMERA)): _CAMERA,
            vol.Optional(CONF_START_TIME, description=dflt(CONF_START_TIME)): _SENSOR_OPT,
            vol.Optional(CONF_END_TIME, description=dflt(CONF_END_TIME)): _SENSOR_OPT,
        }
    )


def _costs_schema(defaults: dict[str, Any]) -> vol.Schema:
    def dflt(key: str, fallback: Any) -> dict[str, Any]:
        return {"suggested_value": defaults.get(key, fallback)}

    return vol.Schema(
        {
            vol.Optional(CONF_SLOTS, description=dflt(CONF_SLOTS, [])): _SLOTS,
            vol.Optional(
                CONF_ENERGY_SENSORS, description=dflt(CONF_ENERGY_SENSORS, [])
            ): _ENERGY,
            vol.Optional(
                CONF_POWER_SENSORS, description=dflt(CONF_POWER_SENSORS, [])
            ): _POWER,
            vol.Optional(
                CONF_ELECTRICITY_PRICE_ENTITY,
                description=dflt(CONF_ELECTRICITY_PRICE_ENTITY, None),
            ): _SENSOR_OPT,
            vol.Required(
                CONF_ELECTRICITY_PRICE,
                description=dflt(CONF_ELECTRICITY_PRICE, DEFAULT_ELECTRICITY_PRICE),
            ): _price(10),
            vol.Required(
                CONF_DEFAULT_FILAMENT_PRICE,
                description=dflt(CONF_DEFAULT_FILAMENT_PRICE, DEFAULT_FILAMENT_PRICE),
            ): _price(1000),
            vol.Required(
                CONF_CURRENCY, description=dflt(CONF_CURRENCY, DEFAULT_CURRENCY)
            ): str,
            vol.Required(
                CONF_AUTO_LOG, description=dflt(CONF_AUTO_LOG, True)
            ): BooleanSelector(),
        }
    )


class BambuCostsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._found: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionally pick the printer device and fill the rest in from it."""
        if user_input is not None:
            device_id = user_input.get(CONF_DEVICE)
            if device_id:
                result = discover(self.hass, device_id)
                self._found = result
                self._data.update(result["config"])
                # Stored so reconfiguring can show it already chosen.
                self._data[CONF_DEVICE] = device_id
            return await self.async_step_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Optional(CONF_DEVICE): _DEVICE}),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_costs()

        defaults = {"name": DEFAULT_NAME, **self._data}
        return self.async_show_form(
            step_id="sensors",
            data_schema=_printer_schema(defaults),
            description_placeholders={"found": self._summary()},
        )

    def _summary(self) -> str:
        if not self._found:
            return "No device chosen — fill these in yourself."
        n = len(self._found["config"])
        if not n:
            return (
                "Nothing recognisable on that device or anything connected "
                "to it — fill these in yourself."
            )
        left = self._found.get("unpaired_trays") or []
        text = f"Found {n} of these from the device. Check them before continuing."
        if left:
            text += " Trays that could not be matched to a slot: " + ", ".join(left)
        return text

    async def async_step_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            title = self._data.pop("name", DEFAULT_NAME)
            return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(step_id="costs", data_schema=_costs_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> BambuCostsOptionsFlow:
        return BambuCostsOptionsFlow()


class BambuCostsOptionsFlow(OptionsFlow):
    """Let every choice be changed after setup."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._found: dict[str, Any] | None = None

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-run discovery against a device, or go straight to the sensors."""
        if user_input is not None:
            device_id = user_input.get(CONF_DEVICE)
            if device_id:
                self._found = discover(self.hass, device_id)
                self._data.update(self._found["config"])
            # Carried forward even when the box was left alone, because the
            # options are rebuilt from ALL_KEYS and anything absent is dropped.
            # The registry fallback backfills entries set up before the device
            # id was stored, so one pass through here repairs them.
            self._data[CONF_DEVICE] = (
                device_id
                or self._current.get(CONF_DEVICE)
                or _device_from_entities(self.hass, self._current)
            )
            return await self.async_step_sensors()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Optional(CONF_DEVICE): _DEVICE}),
                {
                    CONF_DEVICE: self._current.get(CONF_DEVICE)
                    or _device_from_entities(self.hass, self._current)
                },
            ),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_costs()

        # Anything discovery filled in wins over the stored value; the rest
        # keeps what is already configured.
        full = _printer_schema({**self._current, **self._data}).schema
        # The entry title is changed by renaming the entry, not from this form.
        schema = vol.Schema(
            {k: v for k, v in full.items() if getattr(k, "schema", k) != "name"}
        )
        return self.async_show_form(step_id="sensors", data_schema=schema)

    async def async_step_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="", data={key: self._data.get(key) for key in ALL_KEYS}
            )

        return self.async_show_form(
            step_id="costs", data_schema=_costs_schema({**self._current, **self._data})
        )
