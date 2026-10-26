# SPDX-License-Identifier: GPL-3.0-only
"""Mechanical air damper with four nonzero positions."""
from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature

from .const import ATTR_OVERVIEW_CLIMATE, CONF_OVERVIEW_CLIMATE
from .entity import ValveEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ValveCover(entry.runtime_data)])


class ValveCover(ValveEntity, CoverEntity):
    _attr_name = "Заслонка"
    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_icon = "mdi:hvac"
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION

    def __init__(self, controller):
        super().__init__(controller, "cover")

    @property
    def current_cover_position(self):
        return self.controller.state.position

    @property
    def is_closed(self):
        return self.controller.state.power == "off"

    @property
    def extra_state_attributes(self):
        return {
            "state_source": self.controller.source,
            ATTR_OVERVIEW_CLIMATE: self.controller.entry.options.get(CONF_OVERVIEW_CLIMATE, True),
        }

    async def async_open_cover(self, **kwargs):
        await self.controller.set_option("Полное")

    async def async_close_cover(self, **kwargs):
        await self.controller.set_option("Нет")

    async def async_set_cover_position(self, **kwargs):
        await self.controller.set_position(kwargs["position"])
