# SPDX-License-Identifier: GPL-3.0-only
"""Diagnostics without topic prefixes, custom names or device identifiers."""
from .const import CONF_OVERVIEW_CLIMATE


async def async_get_config_entry_diagnostics(hass, entry):
    controller = entry.runtime_data
    return {
        "target": controller.state.dump(), "state_source": controller.source,
        "mqtt_connected": controller.connected, "device_availability_confirmed": False,
        "boot_report_window": controller.window,
        "overview_climate_enabled": entry.options.get(CONF_OVERVIEW_CLIMATE, True),
        "overview_module_registered": hass.data.get("vakio_kiv_local_frontend", False),
        "temperature_received": controller.temperature is not None,
        "humidity_received": controller.humidity is not None,
    }
