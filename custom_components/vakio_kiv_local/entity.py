# SPDX-License-Identifier: GPL-3.0-only
"""Common device identity and push updates."""
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.util import slugify

from .const import DOMAIN


class ValveEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, key):
        self.controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        prefix = slugify(controller.prefix)
        base = prefix if prefix.startswith("vakio_") else f"vakio_kiv_{prefix}"
        platform = "select" if key == "selection" else "cover" if key == "cover" else "sensor"
        # HA treats entity_id as a suggestion on first registration; registry renames win.
        self.entity_id = f"{platform}.{base}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            manufacturer="Vakio", model="KIV Smart", name=controller.entry.title,
        )

    @property
    def available(self):
        # Broker connectivity only; firmware does not supply reliable device availability.
        return self.controller.connected

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self.async_write_ha_state))
