# SPDX-License-Identifier: GPL-3.0-only
"""Numeric telemetry; preserve decimal values and reject malformed payloads."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature

from .entity import ValveEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ValveSensor(entry.runtime_data, "temperature"), ValveSensor(entry.runtime_data, "humidity")])


class ValveSensor(ValveEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, key):
        super().__init__(controller, key)
        self.key = key
        self._attr_name = "Температура" if key == "temperature" else "Влажность"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE if key == "temperature" else SensorDeviceClass.HUMIDITY
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS if key == "temperature" else PERCENTAGE

    @property
    def native_value(self):
        return getattr(self.controller, self.key)
