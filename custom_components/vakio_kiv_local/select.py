# SPDX-License-Identifier: GPL-3.0-only
"""Opening level and firmware automatic mode."""
from homeassistant.components.select import SelectEntity

from .const import OPTIONS
from .entity import ValveEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ValveSelect(entry.runtime_data)])


class ValveSelect(ValveEntity, SelectEntity):
    _attr_name = "Открытие заслонки"
    _attr_icon = "mdi:hvac"
    _attr_options = OPTIONS

    def __init__(self, controller):
        super().__init__(controller, "selection")

    @property
    def current_option(self):
        return self.controller.state.option

    async def async_select_option(self, option):
        await self.controller.set_option(option)
