"""The Bambu Print Costs integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_ENTRY_ID,
    ATTR_PRICE,
    ATTR_SERIAL,
    ATTR_TAGS,
    CONF_PRINT_STATUS,
    DOMAIN,
    PLATFORMS,
    RUNNING_STATES,
    SERVICE_IMPORT_LEGACY,
    SERVICE_LOG_JOB,
    SERVICE_REFRESH,
    SERVICE_SET_TAG_PRICE,
    SERVICE_SYNC_SLOT_PRICES,
    SERVICE_WRITE_TAGS,
    URL_CARDS,
    URL_COVERS,
)
from .coordinator import BambuCostsCoordinator

_LOGGER = logging.getLogger(__name__)

CARD_FILES = (
    "bambu-costs-tags-editor.js",
    "bambu-costs-jobs-table.js",
    "bambu-costs-calculator.js",
)

_FRONTEND_DONE = f"{DOMAIN}_frontend_registered"
_SERVICES_DONE = f"{DOMAIN}_services_registered"

_TAG_SCHEMA = vol.Schema(
    {
        vol.Optional("filament"): cv.string,
        vol.Optional("color_code"): cv.string,
        vol.Optional("color_name"): cv.string,
        vol.Optional("serial"): cv.string,
        vol.Optional("cost_per_kg"): vol.Coerce(float),
        vol.Optional("disabled"): vol.Any(cv.boolean, cv.string),
    },
    extra=vol.REMOVE_EXTRA,
)

_WRITE_TAGS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_TAGS): vol.All(cv.ensure_list, [_TAG_SCHEMA]),
    }
)

_SET_PRICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_PRICE): vol.Coerce(float),
    }
)

_LOG_JOB_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional("job"): cv.string,
        vol.Optional("print_time_min"): vol.Coerce(float),
        vol.Optional("print_time"): cv.string,
        vol.Optional("layers"): vol.Coerce(float),
        vol.Optional("length_m"): vol.Coerce(float),
        vol.Optional("nozzle_size"): cv.string,
        vol.Optional("nozzle_type"): cv.string,
        vol.Optional("filament_cost"): vol.Coerce(float),
        vol.Optional("power_cost"): vol.Coerce(float),
        vol.Optional("energy_kwh"): vol.Coerce(float),
        vol.Optional("capture_cover", default=True): cv.boolean,
        vol.Optional("update_totals", default=True): cv.boolean,
    }
)

_REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})

_IMPORT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional("tags_path"): cv.string,
        vol.Optional("jobs_path"): cv.string,
        vol.Optional("covers_path"): cv.string,
        vol.Optional("replace", default=False): cv.boolean,
    }
)


def _safe_path(hass: HomeAssistant, path: str | None, must_be_dir: bool = False) -> str | None:
    """Resolve a user-supplied path, refusing anything outside the config dir.

    Import reads a path chosen in a service call, so it is confined to Home
    Assistant's own configuration directory rather than the whole filesystem.
    """
    if not path:
        return None

    resolved = os.path.realpath(path)
    config_root = os.path.realpath(hass.config.config_dir)
    try:
        inside = os.path.commonpath([resolved, config_root]) == config_root
    except ValueError:  # different drives on Windows
        inside = False
    if not inside:
        raise ServiceValidationError(
            f"'{path}' is outside the Home Assistant configuration directory"
        )

    exists = os.path.isdir(resolved) if must_be_dir else os.path.isfile(resolved)
    if not exists:
        raise ServiceValidationError(f"'{path}' does not exist")
    return resolved


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bambu Print Costs from a config entry."""
    coordinator = BambuCostsCoordinator(hass, entry)
    await hass.async_add_executor_job(coordinator.store.ensure)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await _async_register_frontend(hass)
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_track_print_start(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


@callback
def _async_track_print_start(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: BambuCostsCoordinator
) -> None:
    """Sync slot prices from the tag library whenever a print starts."""
    status_entity = coordinator.entity_of(CONF_PRINT_STATUS)
    if not status_entity:
        return

    @callback
    def _status_changed(event: Event[EventStateChangedData]) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or new_state.state.lower() not in RUNNING_STATES:
            return
        # Only on the transition in, not on every update while running.
        if old_state is not None and old_state.state.lower() in RUNNING_STATES:
            return

        updated = coordinator.sync_slot_prices()
        if updated:
            _LOGGER.info("Print started; synced slot prices from tags: %s", updated)

    entry.async_on_unload(
        async_track_state_change_event(hass, [status_entity], _status_changed)
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


# ── frontend ─────────────────────────────────────────────────────────────────
async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and register the bundled cards.

    The version from the manifest is appended to every URL, so upgrading the
    integration busts the browser and service-worker caches on its own — no
    hand-bumped ``?v=N`` on a Lovelace resource.
    """
    if hass.data.get(_FRONTEND_DONE):
        return
    hass.data[_FRONTEND_DONE] = True

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version or "0")
    cards_dir = os.path.join(os.path.dirname(__file__), "www")
    covers_root = hass.config.path("bambu_costs")

    await hass.async_add_executor_job(lambda: os.makedirs(covers_root, exist_ok=True))
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(URL_CARDS, cards_dir, False),
            StaticPathConfig(URL_COVERS, covers_root, False),
        ]
    )

    for filename in CARD_FILES:
        add_extra_js_url(hass, f"{URL_CARDS}/{filename}?v={version}")

    _LOGGER.debug("Registered %s cards at %s (v%s)", len(CARD_FILES), URL_CARDS, version)


# ── services ─────────────────────────────────────────────────────────────────
def _resolve(hass: HomeAssistant, call: ServiceCall) -> BambuCostsCoordinator:
    """Pick the config entry a service call targets."""
    entries: dict[str, BambuCostsCoordinator] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get(ATTR_ENTRY_ID)

    if entry_id:
        if entry_id not in entries:
            raise ServiceValidationError(f"No loaded Bambu Print Costs entry '{entry_id}'")
        return entries[entry_id]

    if not entries:
        raise ServiceValidationError("No Bambu Print Costs entry is loaded")
    if len(entries) > 1:
        raise ServiceValidationError(
            "Several Bambu Print Costs entries are loaded — pass entry_id to pick one"
        )
    return next(iter(entries.values()))


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.data.get(_SERVICES_DONE):
        return
    hass.data[_SERVICES_DONE] = True

    async def _write_tags(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve(hass, call)
        written = await coordinator.async_write_tags(call.data[ATTR_TAGS])
        return {"written": written}

    async def _set_tag_price(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve(hass, call)
        changed = await coordinator.async_set_tag_price(
            call.data[ATTR_SERIAL], call.data[ATTR_PRICE]
        )
        return {"changed": changed}

    async def _log_job(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve(hass, call)
        overrides: dict[str, Any] = {
            k: v
            for k, v in call.data.items()
            if k not in (ATTR_ENTRY_ID, "capture_cover", "update_totals")
        }
        row = coordinator.build_job_row(overrides)

        if call.data.get("capture_cover", True):
            stamp = str(row["timestamp"]).replace("-", "").replace(":", "").replace(" ", "-")
            row["cover"] = await coordinator.async_capture_cover(stamp)

        await coordinator.async_append_job(row)

        if call.data.get("update_totals", True):
            coordinator.set_value("last_print_filament_cost", row["filament_cost"])
            coordinator.set_value("last_print_power_cost", row["power_cost"])
            coordinator.set_value("last_print_cost", row["total_cost"])
            coordinator.set_value(
                "total_filament_used",
                coordinator.value("total_filament_used") + row["weight_g"],
            )
            coordinator.set_value(
                "total_cost", coordinator.value("total_cost") + row["total_cost"]
            )
        return {"logged": True, "total_cost": row["total_cost"], "cover": row["cover"]}

    async def _refresh(call: ServiceCall) -> None:
        coordinator = _resolve(hass, call)
        await coordinator.async_request_refresh()

    async def _import_legacy(call: ServiceCall) -> ServiceResponse:
        from .migrate import import_files

        coordinator = _resolve(hass, call)
        tags_path = _safe_path(hass, call.data.get("tags_path"))
        jobs_path = _safe_path(hass, call.data.get("jobs_path"))
        covers_path = _safe_path(hass, call.data.get("covers_path"), must_be_dir=True)

        if not tags_path and not jobs_path:
            raise ServiceValidationError("Give at least one of tags_path or jobs_path")

        result = await hass.async_add_executor_job(
            import_files,
            coordinator.store,
            tags_path,
            jobs_path,
            covers_path,
            call.data.get("replace", False),
        )
        await coordinator.async_request_refresh()
        _LOGGER.info("Imported legacy data: %s", result)
        return dict(result)

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_TAGS,
        _write_tags,
        schema=_WRITE_TAGS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TAG_PRICE,
        _set_tag_price,
        schema=_SET_PRICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOG_JOB,
        _log_job,
        schema=_LOG_JOB_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async def _sync_slot_prices(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve(hass, call)
        return {"updated": coordinator.sync_slot_prices()}

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh, schema=_REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_SLOT_PRICES,
        _sync_slot_prices,
        schema=_REFRESH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_LEGACY,
        _import_legacy,
        schema=_IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
