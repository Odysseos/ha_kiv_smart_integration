# SPDX-License-Identifier: GPL-3.0-only
"""Real HA registries and services -> generated include -> YaHA schema."""
import asyncio
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import custom_components
custom_components.__path__.append(str(ROOT / 'custom_components'))
from homeassistant import bootstrap, config_entries, loader
from homeassistant.config import merge_packages_config
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.entityfilter import EntityFilter
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
from custom_components.vakio_kiv_local.const import DOMAIN
from custom_components.vakio_kiv_local.yaha import EXPORT_PATH
from custom_components.yandex_smart_home.config_schema import YANDEX_SMART_HOME_SCHEMA


async def main():
    logging.basicConfig(level=logging.ERROR)
    with tempfile.TemporaryDirectory(prefix='kiv-yaha-export-') as directory:
        root = Path(directory)
        shutil.copytree(ROOT / 'custom_components', root / 'custom_components')
        hass = HomeAssistant(directory)
        loader.async_setup(hass)
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await bootstrap.async_load_base_functionality(hass)
        hass.config.components.add('mqtt')
        assert await async_setup_component(hass, DOMAIN, {})
        descriptions = await async_get_all_descriptions(hass)
        assert descriptions[DOMAIN]['export_yaha_config']['response']['optional'] is True
        registry, devices, areas = er.async_get(hass), dr.async_get(hass), ar.async_get(hass)
        entries, ids, device_ids = [], [], []
        with patch('custom_components.vakio_kiv_local.async_setup_entry', new=AsyncMock(return_value=True)):
            for number in range(3):
                result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': 'user'}, data={
                    'name': f'Valve {number}', 'topic_prefix': f'vakio_kiv_{number}', 'boot_report_window': 3})
                entry = result['result']
                await hass.async_block_till_done()
                entries.append(entry)
                area = areas.async_create(f'Комната {number}')
                device = devices.async_get_or_create(config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, entry.entry_id)}, name=f'Клапан {number}')
                devices.async_update_device(device.id, area_id=area.id)
                device_ids.append(device.id)
                current = {}
                for key, platform in [('cover', 'cover'), ('selection', 'select'), ('temperature', 'sensor'), ('humidity', 'sensor')]:
                    entity = registry.async_get_or_create(platform, DOMAIN, f'{entry.entry_id}_{key}',
                        config_entry=entry, device_id=device.id, suggested_object_id=f'vakio_kiv_{number}_{key}')
                    current[key] = entity.entity_id
                ids.append(current)
        path = root / EXPORT_PATH
        other = path.parent / 'other_devices.yaml'
        other.parent.mkdir(parents=True)
        other.write_text('media_player.tv_livingroom:\n  name: Телевизор\n')
        other_bytes = other.read_bytes()

        async def export(context=None):
            return await hass.services.async_call(DOMAIN, 'export_yaha_config', {},
                blocking=True, return_response=True, context=context)

        try:
            response = await export()
            assert response['file'] == EXPORT_PATH and response['device_count'] == 3
            data = load_yaml(str(path))['entity_config']
            assert set(data) == {item['cover'] for item in ids}
            for number, item in enumerate(ids):
                block = data[item['cover']]
                assert block['name'] == f'Клапан {number}' and block['room'] == f'Комната {number}'
                assert block['turn_on']['target']['entity_id'] == item['selection']
                assert block['properties'][0]['entity'] == item['temperature']
                assert block['properties'][1]['entity'] == item['humidity']
            YANDEX_SMART_HOME_SCHEMA(load_yaml(str(path)))
            assert load_yaml(str(path))['filter']['include_entities'] == sorted(data)
            config_file = root / 'configuration.yaml'
            config_file.write_text(
                'homeassistant:\n  packages:\n'
                '    yaha_other:\n'
                '      yandex_smart_home: !include includes/yandex_smart_home.yaml\n'
                '    yaha_vakio:\n'
                '      yandex_smart_home: !include includes/yandex_smart_home_vakio.yaml\n')
            main_yaha = root / 'includes/yandex_smart_home.yaml'
            main_yaha.write_text('filter:\n  include_entities:\n    - media_player.tv_livingroom\n  include_entity_globs:\n    - light.zigbee_*\n'
                'entity_config:\n  media_player.tv_livingroom:\n    name: Телевизор\n')
            main_bytes = main_yaha.read_bytes()
            loaded = load_yaml(str(config_file))
            package_errors = []
            await merge_packages_config(hass, loaded, loaded['homeassistant']['packages'],
                _log_pkg_error=lambda *args: package_errors.append(args))
            assert not package_errors, package_errors
            assert len(loaded['yandex_smart_home']['entity_config']) == 4
            assert loaded['yandex_smart_home']['entity_config']['media_player.tv_livingroom']['name'] == 'Телевизор'
            assert loaded['yandex_smart_home']['filter']['include_entity_globs'] == ['light.zigbee_*']
            validated = YANDEX_SMART_HOME_SCHEMA(loaded['yandex_smart_home'])
            expose = EntityFilter(validated['filter'])
            assert expose('media_player.tv_livingroom') and expose('light.zigbee_example')
            assert all(expose(item['cover']) for item in ids)
            assert not expose('cover.unrelated')
            assert not expose('cover.vakio_kiv_old_mqtt_cover')
            assert all(not expose(item['selection']) for item in ids)
            assert main_yaha.read_bytes() == main_bytes
            assert other.read_bytes() == other_bytes
            original = path.read_bytes()
            await export()
            assert path.read_bytes() == original
            registry.async_update_entity(ids[0]['cover'], new_entity_id='cover.custom_valve')
            new_area = areas.async_create('Новая комната')
            registry.async_update_entity('cover.custom_valve', area_id=new_area.id)
            devices.async_update_device(device_ids[0], name_by_user='Новое имя')
            await export()
            data = load_yaml(str(path))['entity_config']
            assert ids[0]['cover'] not in data and 'cover.custom_valve' in data
            assert load_yaml(str(path))['filter']['include_entities'] == sorted(data)
            assert data['cover.custom_valve']['room'] == 'Новая комната'
            assert data['cover.custom_valve']['name'] == 'Новое имя'
            before_failure = path.read_bytes()
            registry.async_update_entity(ids[1]['humidity'], disabled_by=er.RegistryEntryDisabler.USER)
            try:
                await export()
            except ServiceValidationError:
                pass
            else:
                raise AssertionError('Disabled sensor did not block export')
            assert path.read_bytes() == before_failure
            registry.async_update_entity(ids[1]['humidity'], disabled_by=None)
            with patch('custom_components.vakio_kiv_local.yaha.os.replace', side_effect=OSError('test write failure')):
                try:
                    await export()
                except ServiceValidationError:
                    pass
                else:
                    raise AssertionError('Write failure ignored')
            assert path.read_bytes() == before_failure
            assert not list(path.parent.glob('*.tmp'))
            path.write_text('cover.manual_device:\n  name: Manual\n')
            manual_bytes = path.read_bytes()
            try:
                await export()
            except ServiceValidationError:
                pass
            else:
                raise AssertionError('Unowned configuration overwritten')
            assert path.read_bytes() == manual_bytes
            path.write_bytes(before_failure)
            with patch.object(hass, 'auth', SimpleNamespace(
                    async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=False))), create=True):
                try:
                    await export(Context(user_id='not-admin'))
                except Unauthorized:
                    pass
                else:
                    raise AssertionError('Non-admin export accepted')
            assert path.read_bytes() == before_failure
            with patch('custom_components.vakio_kiv_local.async_unload_entry', new=AsyncMock(return_value=True)):
                assert await hass.config_entries.async_remove(entries[2].entry_id)
                response = await export()
                assert response['device_count'] == 2 and ids[2]['cover'] not in load_yaml(str(path))['entity_config']
                for entry in entries[:2]:
                    assert await hass.config_entries.async_remove(entry.entry_id)
                response = await export()
                assert response['device_count'] == 0 and load_yaml(str(path)) == {'filter': {'include_entities': []}, 'entity_config': {}}
            assert other.read_bytes() == other_bytes
        finally:
            await hass.async_stop()
    print('PASS: registered action; three devices; generated YAML and HA package merge -> YaHA schema; registry renames and areas; repeat export; removed/zero devices; disabled sensor; atomic-write failure; unowned file; other files unchanged; admin permission')


if __name__ == '__main__':
    asyncio.run(main())
