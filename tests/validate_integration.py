# SPDX-License-Identifier: GPL-3.0-only
"""Actual config flow, entity platforms, persistent stores and MQTT loopback."""
import asyncio
from collections import defaultdict
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import custom_components
custom_components.__path__.append(str(ROOT / "custom_components"))
from homeassistant import bootstrap, config_entries, loader
from homeassistant.components import mqtt
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import InvalidData
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from custom_components.vakio_kiv_local.const import DOMAIN
from custom_components.vakio_kiv_local.controller import ValveController
from custom_components.vakio_kiv_local.state import ValveState


async def main():
    logging.basicConfig(level=logging.ERROR)
    with tempfile.TemporaryDirectory(prefix="kiv-local-test-") as directory:
        cfg = Path(directory)
        shutil.copytree(ROOT / 'custom_components', cfg / 'custom_components')
        hass = HomeAssistant(directory)
        loader.async_setup(hass)
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await bootstrap.async_load_base_functionality(hass)
        # MQTT network I/O is replaced below; skip HTTP/network broker setup.
        hass.config.components.add("mqtt")
        subscriptions = defaultdict(list)
        connection_callbacks = []
        wire = []
        async def subscribe(hass, topic, cb, qos=0, **kwargs):
            subscriptions[topic].append(cb)
            return lambda: subscriptions[topic].remove(cb)
        def status(hass, cb):
            connection_callbacks.append(cb)
            return lambda: connection_callbacks.remove(cb)
        def deliver(topic, payload):
            for cb in tuple(subscriptions[topic]):
                cb(SimpleNamespace(payload=payload))
        async def publish(hass, topic, payload, qos=0, retain=False, **kwargs):
            wire.append((topic, payload, qos, retain))
            deliver(topic, payload)
        async def drain():
            await asyncio.sleep(0.06)
            await hass.async_block_till_done()
        with patch.object(mqtt, 'async_wait_for_mqtt_client', return_value=True), \
                patch.object(mqtt, 'is_connected', return_value=True), \
                patch.object(mqtt, 'async_subscribe', side_effect=subscribe), \
                patch.object(mqtt, 'async_publish', side_effect=publish), \
                patch.object(mqtt, 'async_subscribe_connection_status', side_effect=status):
            assert await async_setup_component(hass, DOMAIN, {})
            result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': 'user'})
            assert result['type'] == 'form', result
            bad = await hass.config_entries.flow.async_configure(result['flow_id'], {'name': 'Valve', 'topic_prefix': 'bad/#'})
            assert bad['errors']['base'] == 'invalid_config'
            result = await hass.config_entries.flow.async_configure(result['flow_id'], {
                'name': 'Vakio KIV', 'topic_prefix': 'vakio_kiv', 'boot_report_window': 1,
            })
            assert result['type'] == 'create_entry', result
            entry = result['result']
            await hass.async_block_till_done()
            assert entry.state == config_entries.ConfigEntryState.LOADED, entry.state
            controller = entry.runtime_data
            controller.window = 0.02
            registry = er.async_get(hass)
            def ids_for(entry):
                return {key: registry.async_get_entity_id(platform, DOMAIN, f'{entry.entry_id}_{key}')
                        for key, platform in [('cover','cover'), ('selection','select'), ('temperature','sensor'), ('humidity','sensor')]}
            ids = ids_for(entry)
            assert all(ids.values()), ids
            assert ids['cover'] == 'cover.vakio_kiv_cover', ids
            assert hass.states.get(ids['cover']).attributes['device_class'] == 'damper'
            assert hass.states.get(ids['cover']).attributes['vakio_kiv_local_overview_climate'] is True
            assert len([e for e in er.async_entries_for_config_entry(registry, entry.entry_id)]) == 4
            assert not hass.states.async_entity_ids('input_text')
            duplicate = await hass.config_entries.flow.async_init(DOMAIN, context={'source':'user'}, data={
                'name':'Duplicate', 'topic_prefix':'/vakio_kiv/', 'boot_report_window':3})
            assert duplicate['reason'] == 'already_configured', duplicate
            for option, position in [('Малое',25),('Среднее',50),('Большое',75),('Полное',100),('Нет',0),('Авто',0)]:
                await hass.services.async_call('select', 'select_option', {'entity_id':ids['selection'], 'option':option}, blocking=True)
                await drain()
                assert hass.states.get(ids['selection']).state == option
                if option != 'Авто':
                    assert hass.states.get(ids['cover']).attributes['current_position'] == position
            assert wire[-1][0] == 'vakio_kiv/workmode' and wire[-1][1] == 'super_auto'
            deliver('device/vakio_kiv/kivsmart/mode', json.dumps({'capabilities':{'mode':'manual','on_off':'on','gate':2}}))
            await drain()
            assert hass.states.get(ids['selection']).state == 'Среднее'
            await hass.services.async_call('cover','set_cover_position',{'entity_id':ids['cover'], 'position':75},blocking=True)
            await drain()
            assert hass.states.get(ids['selection']).state == 'Большое'
            deliver('vakio_kiv/temp','22.5')
            deliver('vakio_kiv/hud','45.2')
            await drain()
            assert hass.states.get(ids['temperature']).state == '22.5'
            assert hass.states.get(ids['humidity']).state == '45.2'
            for payload in ('nan','inf','bad'):
                deliver('vakio_kiv/temp',payload)
            deliver('vakio_kiv/hud','101')
            await drain()
            assert hass.states.get(ids['temperature']).state == '22.5'
            assert hass.states.get(ids['humidity']).state == '45.2'
            # Older report must lose to a new UI command or boot registration.
            for event in ('ui','boot'):
                deliver('device/vakio_kiv/kivsmart/mode', '{"capabilities":{"gate":1}}')
                await asyncio.sleep(0.003)
                if event == 'ui':
                    await controller.set_option('Большое')
                else:
                    deliver('device/vakio_kiv/kivsmart/system','{"type":"auth"}')
                await drain()
                assert controller.state.gate == 3
            # Direct mode commands update both entities and persist, without retransmission.
            before = len(wire)
            deliver('vakio_kiv/workmode', 'super_auto')
            await drain()
            assert controller.state.mode == 'super_auto' and len(wire) == before
            # Partial JSON mode commands require an actual workmode publication.
            deliver('server/vakio_kiv/kivsmart/mode','{"capabilities":{"mode":"manual","gate":1}}')
            await drain()
            assert controller.state.mode == 'manual' and controller.state.gate == 1
            assert any(t == 'vakio_kiv/workmode' and p == 'manual' for t,p,_,_ in wire[before:])
            assert all(not retain for _,_,_,retain in wire)
            # Service uses actual registry IDs, including user renames.
            renamed = 'cover.my_custom_valve'
            registry.async_update_entity(ids['cover'], new_entity_id=renamed)
            await drain()
            ids = ids_for(entry)
            device = next(d for d in dr.async_get(hass).devices.values() if entry.entry_id in d.config_entries)
            response = await hass.services.async_call(DOMAIN,'get_yaha_config', {'device_id':device.id},blocking=True,return_response=True)
            assert renamed in response['yandex_smart_home']['entity_config']
            assert response['filter_hint']['include_entities'] == [renamed]
            # Validate the generated config with real YaHA classes and real HA entities.
            from custom_components.yandex_smart_home.config_schema import YANDEX_SMART_HOME_SCHEMA
            from custom_components.yandex_smart_home.device import Device
            from custom_components.yandex_smart_home.schema import (
                CapabilityType, DeviceType, ModeCapabilityInstance,
                ModeCapabilityInstanceActionState, ModeCapabilityMode,
                OnOffCapabilityInstance, OnOffCapabilityInstanceActionState,
            )
            from homeassistant.helpers import template
            validated = YANDEX_SMART_HOME_SCHEMA(response['yandex_smart_home'])
            template.attach(hass, validated)
            yaha_entry = SimpleNamespace(
                get_entity_config=lambda entity_id: validated['entity_config'].get(entity_id, {}),
                is_reporting_states=True, should_expose=lambda entity_id: entity_id == renamed,
                use_entry_aliases=False,
            )
            def yaha_device():
                return Device(hass, yaha_entry, renamed, hass.states.get(renamed))
            def yaha_caps():
                return {c.type:c for c in yaha_device().get_capabilities()}
            assert yaha_device().type == DeviceType.VENTILATION
            assert set(yaha_caps()) == {CapabilityType.MODE, CapabilityType.ON_OFF}
            for mode, option in [('low','Малое'),('medium','Среднее'),('high','Большое'),('max','Полное'),('auto','Авто')]:
                await yaha_caps()[CapabilityType.MODE].set_instance_state(Context(), ModeCapabilityInstanceActionState(
                    instance=ModeCapabilityInstance.PROGRAM, value=ModeCapabilityMode(mode)))
                await drain()
                assert controller.state.option == option
                assert yaha_caps()[CapabilityType.MODE].get_value() == mode
            for power in (False,True):
                await yaha_caps()[CapabilityType.ON_OFF].set_instance_state(Context(), OnOffCapabilityInstanceActionState(
                    instance=OnOffCapabilityInstance.ON, value=power))
                await drain()
                assert yaha_caps()[CapabilityType.ON_OFF].get_value() is power
            props = {p.instance:p.get_value() for p in yaha_device().get_properties()}
            assert props['temperature'] == 22.5 and props['humidity'] == 45.2
            # A newer unchanged report must also supersede an older different report.
            await controller.set_option('Большое')
            await drain()
            deliver('device/vakio_kiv/kivsmart/mode','{"capabilities":{"gate":1}}')
            await asyncio.sleep(0.003)
            deliver('device/vakio_kiv/kivsmart/mode','{"capabilities":{"gate":3}}')
            await drain()
            assert controller.state.gate == 3
            # Persisted target must survive unload/reload with no helper.
            await controller.set_option('Авто')
            await drain()
            expected = controller.state
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert not any(subscriptions.values()) and not connection_callbacks
            assert await hass.config_entries.async_setup(entry.entry_id)
            await drain()
            assert entry.runtime_data.state == expected
            entry.runtime_data.window = 0.02
            # A second config entry uses its own store and subscriptions.
            second = await hass.config_entries.flow.async_init(DOMAIN, context={'source':'user'}, data={
                'name':'Another valve','topic_prefix':'vakio_kiv_aux','boot_report_window':1})
            await hass.async_block_till_done()
            other = second['result']
            other.runtime_data.window = 0.02
            await other.runtime_data.set_option('Малое')
            await drain()
            assert entry.runtime_data.state == expected and other.runtime_data.state.gate == 1
            # Broker loss is detectable; device loss itself is not claimed detectable.
            entry.runtime_data.connection_changed(False)
            await drain()
            assert hass.states.get(ids['cover']).state == 'unavailable'
            assert yaha_device().unavailable
            entry.runtime_data.connection_changed(True)
            await drain()
            assert entry.runtime_data.state == expected
            # Reload through the options flow; no duplicate listeners.
            opts = await hass.config_entries.options.async_init(entry.entry_id)
            assert opts['type'] == 'form'
            try:
                await hass.config_entries.options.async_configure(opts['flow_id'], {'boot_report_window': float('nan')})
            except InvalidData:
                pass
            else:
                raise AssertionError('NaN delay accepted by options schema')
            await hass.config_entries.options.async_configure(opts['flow_id'], {'boot_report_window':2, 'overview_climate':False})
            await hass.async_block_till_done()
            assert entry.runtime_data.window == 2
            assert hass.states.get(ids['cover']).attributes['vakio_kiv_local_overview_climate'] is False
            assert hass.states.get(ids_for(other)['cover']).attributes['vakio_kiv_local_overview_climate'] is True
            # A failed durable write must neither publish commands nor advance state.
            saved_target = entry.runtime_data.state
            before = len(wire)
            with patch.object(entry.runtime_data.store, 'async_save', side_effect=OSError('test storage failure')):
                try:
                    await entry.runtime_data.set_option('Нет')
                except OSError:
                    pass
                else:
                    raise AssertionError('Storage failure was silently ignored')
            assert entry.runtime_data.state == saved_target and len(wire) == before
            # Real store removal is scoped to the entry being removed.
            store_path = cfg / '.storage' / f'{DOMAIN}.{other.entry_id}'
            assert store_path.exists()
            assert await hass.config_entries.async_remove(other.entry_id)
            assert not store_path.exists()
            assert entry.runtime_data.state == expected
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert not any(subscriptions.values()) and not connection_callbacks
        for month in range(1,13):
            assert ValveState.seasonal(month).gate == (4 if month in (5,6,7,8,9) else 3 if month in (4,10) else 2 if month in (3,11) else 1)
        await hass.async_stop()
    print('PASS: config flow; invalid/duplicate prefix; actual entities/services; generated YaHA config -> all modes/on-off -> native entities/MQTT; all levels/auto; buttons; raw MQTT; loops; races; decimals; bad telemetry; registry-aware YaHA config; real storage/reload/removal; two entries; MQTT reconnect; options; unload')


if __name__ == '__main__':
    asyncio.run(main())
