# SPDX-License-Identifier: GPL-3.0-only
"""Add independent valves through the standard HA interface."""
import math
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import CONF_OVERVIEW_CLIMATE, CONF_PREFIX, CONF_WINDOW, DOMAIN


def valid_window(value):
    value = float(value)
    if not math.isfinite(value) or not 1 <= value <= 15:
        raise vol.Invalid("Delay must be between 1 and 15 seconds")
    return value


def valid_prefix(value):
    value = cv.string(value).strip().strip("/")
    if not value or any(c in value for c in ("+", "#", "\x00")):
        raise vol.Invalid("A concrete MQTT prefix is required")
    return value


class ValveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                prefix = valid_prefix(user_input[CONF_PREFIX])
                name = cv.string(user_input["name"]).strip()
                if not name:
                    raise vol.Invalid("Empty name")
                window = valid_window(user_input.get(CONF_WINDOW, 3))
            except (vol.Invalid, KeyError, TypeError, ValueError):
                errors["base"] = "invalid_config"
            else:
                await self.async_set_unique_id(prefix)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data={CONF_PREFIX: prefix, CONF_WINDOW: window})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("name", default="Vakio KIV"): str,
            vol.Required(CONF_PREFIX, default="vakio_kiv"): str,
            vol.Optional(CONF_WINDOW, default=3): vol.All(vol.Coerce(float), vol.Range(min=1, max=15)),
        }), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ValveOptionsFlow()


class ValveOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                value = valid_window(user_input[CONF_WINDOW])
            except (vol.Invalid, ValueError, TypeError, KeyError):
                errors["base"] = "invalid_config"
            else:
                return self.async_create_entry(title="", data={
                    CONF_WINDOW: value,
                    CONF_OVERVIEW_CLIMATE: user_input.get(CONF_OVERVIEW_CLIMATE,
                        self.config_entry.options.get(CONF_OVERVIEW_CLIMATE, True)),
                })
        return self.async_show_form(step_id="init", errors=errors, data_schema=vol.Schema({
            vol.Optional(CONF_OVERVIEW_CLIMATE, default=self.config_entry.options.get(
                CONF_OVERVIEW_CLIMATE, True)): bool,
            vol.Required(CONF_WINDOW, default=self.config_entry.options.get(
                CONF_WINDOW, self.config_entry.data.get(CONF_WINDOW, 3))):
                    vol.All(vol.Coerce(float), vol.Range(min=1, max=15)),
        }))
