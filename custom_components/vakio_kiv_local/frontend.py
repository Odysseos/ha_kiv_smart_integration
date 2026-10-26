# SPDX-License-Identifier: GPL-3.0-only
"""Serve browser assets and load the optional Overview extension."""
import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_URL_PATH = f"/{DOMAIN}/overview.js"
_MODULE_URL = f"{_URL_PATH}?v=0.4.0"
_DATA_KEY = f"{DOMAIN}_frontend"


async def async_register(hass):
    """Register once; keep headless HA and working MQTT independent of the UI."""
    if frontend.DATA_EXTRA_MODULE_URL not in hass.data:
        return
    if hass.data.get(_DATA_KEY):
        return
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_URL_PATH, str(Path(__file__).parent / "www" / "overview.js"), False),
            StaticPathConfig(f"/{DOMAIN}/settings.html",
                str(Path(__file__).parent / "www" / "settings_download.html"), False),
            StaticPathConfig(f"/{DOMAIN}/vakio_settings.html",
                str(Path(__file__).parent / "www" / "vakio_settings.html"), False),
            StaticPathConfig(f"/{DOMAIN}/vakio_settings.py",
                str(Path(__file__).parent / "www" / "vakio_settings.py"), False)
        ])
        frontend.add_extra_js_url(hass, _MODULE_URL)
    except Exception:
        _LOGGER.exception("Could not load the Overview extension")
        return
    # Static routes live until HA restarts. Per-device switches are read by JS
    # from current cover attributes; unloading an entry removes its marker.
    hass.data[_DATA_KEY] = True
