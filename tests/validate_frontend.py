# SPDX-License-Identifier: GPL-3.0-only
"""Serve the shipped module through HA HTTP and register its extra-module URL."""
import asyncio
from pathlib import Path
import sys
import tempfile
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from homeassistant import bootstrap, config_entries, loader
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.components.http import HomeAssistantHTTP
from homeassistant.components.http.cors import setup_cors

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.vakio_kiv_local.frontend import async_register


async def main():
    with tempfile.TemporaryDirectory(prefix="kiv-frontend-") as directory:
        hass = HomeAssistant(directory)
        loader.async_setup(hass)
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await bootstrap.async_load_base_functionality(hass)
        # Headless HA must not require the frontend or create a route.
        await async_register(hass)
        assert "vakio_kiv_local_frontend" not in hass.data
        hass.http = HomeAssistantHTTP(
            hass, ssl_certificate=None, ssl_peer_certificate=None, ssl_key=None,
            server_host=["127.0.0.1"], server_port=0, trusted_proxies=[], ssl_profile="modern",
        )
        setup_cors(hass.http.app, [])
        changes = []
        urls = frontend.UrlManager(lambda *args: changes.append(args), [])
        hass.data[frontend.DATA_EXTRA_MODULE_URL] = urls
        # Failed UI setup is contained; the device integration can keep running.
        with patch.object(hass.http, 'async_register_static_paths', AsyncMock(side_effect=OSError('test failure'))), \
                patch('custom_components.vakio_kiv_local.frontend._LOGGER.exception') as log:
            await async_register(hass)
            assert log.call_count == 1 and not urls.urls
        await async_register(hass)
        await async_register(hass)
        assert len(urls.urls) == len(changes) == 1
        module_url = next(iter(urls.urls))
        assert module_url.endswith('/overview.js?v=0.5.0')
        # Exercise the actual HTTP static path, not a fake registration callback.
        async with TestClient(TestServer(hass.http.app)) as client:
            response = await client.get(module_url)
            assert response.status == 200, await response.text()
            assert 'javascript' in response.headers['Content-Type']
            assert await response.text() == (ROOT/'custom_components/vakio_kiv_local/www/overview.js').read_text()
            assert response.headers.get('Cache-Control') != 'public, max-age=2678400'
            response = await client.get("/vakio_kiv_local/settings.html")
            assert response.status == 200
            assert await response.text() == (ROOT / "custom_components/vakio_kiv_local/www/settings_download.html").read_text()
            for filename in ("vakio_settings.html", "vakio_settings.py"):
                response = await client.get(f"/vakio_kiv_local/{filename}")
                assert response.status == 200
                assert await response.text() == (ROOT / "custom_components/vakio_kiv_local/www" / filename).read_text()
        await hass.async_stop()
    print('PASS: headless HA; contained registration error; one extra-module URL; actual HA HTTP route and JS response')


if __name__ == '__main__':
    asyncio.run(main())
