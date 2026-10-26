# SPDX-License-Identifier: GPL-3.0-only
"""Generate YaHA configuration from actual registry entity IDs."""
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN


def entity_config(cover, selection, temperature, humidity):
    return {
        cover: {
            "name": "Приточный клапан", "type": "ventilation",
            "state_template": "{{ {'open': 'on', 'closed': 'off'}.get(states('" + cover + "'), 'unavailable') }}",
            "turn_on": {"action": "select.select_option", "target": {"entity_id": selection}, "data": {"option": "Полное"}},
            "turn_off": {"action": "select.select_option", "target": {"entity_id": selection}, "data": {"option": "Нет"}},
            "modes": {"program": {"auto": "Авто", "low": "Малое", "medium": "Среднее", "high": "Большое", "max": "Полное"}},
            "custom_modes": {"program": {
                "state_template": "{{ 'off' if is_state('" + cover + "', 'closed') else states('" + selection + "') }}",
                "set_mode": {"action": "select.select_option", "target": {"entity_id": selection}, "data": {"option": "{{ mode }}"}},
            }},
            "custom_ranges": {"open": False},
            "properties": [{"type": "temperature", "entity": temperature}, {"type": "humidity", "entity": humidity}],
        }
    }


def config_for_device(hass, device_id):
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError("Unknown device")
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id in device.config_entries]
    if len(entries) != 1:
        raise ServiceValidationError("Choose a Vakio KIV Local device")
    entry = entries[0]
    registry = er.async_get(hass)
    ids = {}
    for key, platform in (("cover", "cover"), ("selection", "select"), ("temperature", "sensor"), ("humidity", "sensor")):
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
        if entity_id is None or registry.async_get(entity_id).disabled:
            raise ServiceValidationError("Enable all four entities before generating the YaHA configuration")
        ids[key] = entity_id
    return {
        "yandex_smart_home": {"entity_config": entity_config(**ids)},
        "filter_hint": {"include_entities": [ids["cover"]]},
    }
