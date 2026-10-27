# SPDX-License-Identifier: GPL-3.0-only
"""Vakio KIV Local, using the MQTT client configured in Home Assistant."""
import asyncio

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN, PLATFORMS
from .controller import ValveController
from .frontend import async_register
from .yaha import async_export_config, config_for_device

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass, config):
    async def generate(call):
        return config_for_device(hass, call.data["device_id"])
    hass.services.async_register(DOMAIN, "get_yaha_config", generate,
        schema=vol.Schema({vol.Required("device_id"): cv.string}),
        supports_response=SupportsResponse.ONLY)
    export_lock = asyncio.Lock()

    async def export(call):
        async with export_lock:
            return await async_export_config(hass)

    async_register_admin_service(hass, DOMAIN, "export_yaha_config", export,
        supports_response=SupportsResponse.OPTIONAL)
    await async_register(hass)
    return True


async def async_setup_entry(hass, entry):
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT client is not ready")
    controller = ValveController(hass, entry)
    entry.runtime_data = controller
    try:
        await controller.start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await controller.restore()
    except Exception:
        await controller.stop()
        # Clean up any platforms already forwarded before a partial setup failure.
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        raise
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.stop()
        return True
    return False


async def async_remove_entry(hass, entry):
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
