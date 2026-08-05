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
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_COVER_IMAGE,
    CONF_CURRENCY,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_ENERGY_SENSORS,
    CONF_LAYERS,
    CONF_LENGTH,
    CONF_NOZZLE_SIZE,
    CONF_NOZZLE_TYPE,
    CONF_PRINT_STATUS,
    CONF_PRINT_WEIGHT,
    CONF_SLOTS,
    CONF_TASK_NAME,
    DEFAULT_CURRENCY,
    DEFAULT_ELECTRICITY_PRICE,
    DEFAULT_FILAMENT_PRICE,
    DEFAULT_NAME,
    DOMAIN,
)

_SENSOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
_SENSOR_OPT = EntitySelector(EntitySelectorConfig(domain="sensor"))
_IMAGE = EntitySelector(EntitySelectorConfig(domain=["image", "camera"]))
_ENERGY = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
)
_SLOTS = TextSelector(TextSelectorConfig(multiple=True))

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
    CONF_SLOTS,
    CONF_ENERGY_SENSORS,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_ELECTRICITY_PRICE,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_CURRENCY,
)


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
        }
    )


class BambuCostsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_costs()

        return self.async_show_form(
            step_id="user", data_schema=_printer_schema({"name": DEFAULT_NAME})
        )

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

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_costs()

        full = _printer_schema(self._current).schema
        # The entry title is changed by renaming the entry, not from this form.
        schema = vol.Schema(
            {k: v for k, v in full.items() if getattr(k, "schema", k) != "name"}
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="", data={key: self._data.get(key) for key in ALL_KEYS}
            )

        return self.async_show_form(step_id="costs", data_schema=_costs_schema(self._current))
