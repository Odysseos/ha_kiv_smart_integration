# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 vakio-kiv-ha contributors

"""Integration contract test: YaHA 1.1.3 -> HA select -> existing blueprint.
Run with PYTHONPATH pointing at a checkout of dext0r/yandex_smart_home.
Actual YaHA capability classes/schemas, HA Script and input_text are used.
MQTT transport and select entity dispatch are replaced with local callbacks.
"""
import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import yaml
from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv, script, template
from homeassistant.helpers.entityfilter import EntityFilter
from homeassistant.setup import async_setup_component
from homeassistant.components.mqtt import MQTT_PUBLISH_SCHEMA
from custom_components.yandex_smart_home.config_schema import YANDEX_SMART_HOME_SCHEMA
from custom_components.yandex_smart_home.device import Device
from custom_components.yandex_smart_home.schema import (
    CapabilityType, DeviceType, ModeCapabilityInstance,
    ModeCapabilityInstanceActionState, ModeCapabilityMode,
    OnOffCapabilityInstance, OnOffCapabilityInstanceActionState,
)
from validate_ha import Loader, resolve

ROOT = Path(__file__).resolve().parents[1]

async def main():
    logging.basicConfig(level=logging.ERROR)
    pack = yaml.safe_load((ROOT / 'manual/includes/vakio_cover.yaml').read_text())
    actual_inputs = pack['automation'][0]['use_blueprint']['input']
    inputs = deepcopy(actual_inputs)
    inputs['boot_report_window'] = 0.01
    prefix = inputs['id_prefix']
    cover_id = 'cover.' + prefix
    select_id = 'select.' + prefix + '_selection'
    bridge = 'vakio_ha/' + prefix + '/json'
    hass = HomeAssistant(tempfile.mkdtemp(prefix='vakio-yaha-test-'))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    assert await async_setup_component(hass, 'input_text', {'input_text': pack['input_text']})
    validated = YANDEX_SMART_HOME_SCHEMA(pack['yandex_smart_home'])
    filter_example = yaml.safe_load((ROOT / 'manual/examples/yaha_filter.yaml').read_text())
    filter_config = YANDEX_SMART_HOME_SCHEMA(filter_example['yandex_smart_home'])['filter']
    export_filter = EntityFilter(filter_config)
    assert export_filter(cover_id)
    assert export_filter('cover.vakio_kiv_aux_cover')
    assert not export_filter(select_id)
    assert not export_filter('sensor.' + prefix + '_temperature')
    assert not export_filter(inputs['memory_entity'])
    previous_filter = EntityFilter(YANDEX_SMART_HOME_SCHEMA({
        'filter': {'include_entity_globs': ['cover.blind_*']},
    })['filter'])
    assert not previous_filter(cover_id)
    template.attach(hass, validated)
    entry = SimpleNamespace(
        get_entity_config=lambda entity_id: validated['entity_config'].get(entity_id, {}),
        is_reporting_states=True, should_expose=export_filter,
        use_entry_aliases=False,
    )
    cfg = resolve(yaml.load((ROOT / 'manual/blueprints/automation/vakio_cover.yaml').read_text(), Loader=Loader), inputs)
    actions = await script.async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(cfg['actions']))
    runner = script.Script(hass, actions, 'YaHA blueprint path', 'automation', script_mode=cfg['mode'])
    discovery = {}
    wire = []
    async def publish(call):
        topic, payload = call.data['topic'], call.data['payload']
        if topic.endswith('/config'):
            discovery.update(json.loads(payload))
        elif topic.startswith('server/') or topic.endswith('/workmode'):
            wire.append((topic, payload))
        elif topic == bridge + '/selection/state':
            hass.states.async_set(select_id, payload, {'options': discovery['components']['selection']['options']})
        elif topic in [bridge + '/cover/state', bridge + '/cover/position']:
            old = hass.states.get(cover_id)
            state = old.state if old else 'unknown'
            attrs = dict(old.attributes) if old else {'supported_features': 7, 'device_class': 'damper'}
            if topic.endswith('/position'):
                attrs['current_position'] = int(payload)
            else:
                state = payload
            hass.states.async_set(cover_id, state, attrs)
    hass.services.async_register('mqtt', 'publish', publish, schema=MQTT_PUBLISH_SCHEMA)
    async def run(kind, caps=None, payload=None):
        variables = cv.SCRIPT_VARIABLES_SCHEMA(cfg['variables']).async_render(hass, {
            'trigger': {'id': kind, 'payload': payload if payload is not None else json.dumps({'capabilities': caps or {}})}
        })
        await runner.async_run(variables, Context())
    async def select_option(call):
        assert call.data['entity_id'] in [select_id, [select_id]]
        option = call.data['option']
        assert option in discovery['components']['selection']['options']
        payload = template.Template(discovery['components']['selection']['command_template'], hass).async_render(
            {'value': option}, parse_result=False)
        await run('ui_command', payload=payload)
    hass.services.async_register('select', 'select_option', select_option)
    await run('restart')
    hass.states.async_set('sensor.' + prefix + '_temperature', '22.5', {'unit_of_measurement': '°C', 'device_class': 'temperature'})
    hass.states.async_set('sensor.' + prefix + '_humidity', '45', {'unit_of_measurement': '%', 'device_class': 'humidity'})
    def device():
        return Device(hass, entry, cover_id, hass.states.get(cover_id))
    def capabilities():
        caps = device().get_capabilities()
        assert len(caps) == 2, [(c.type, c.instance) for c in caps]
        assert not any(c.type == CapabilityType.RANGE for c in caps)
        return {c.type: c for c in caps}
    assert device().type == DeviceType.VENTILATION
    caps = capabilities()
    assert caps[CapabilityType.ON_OFF].parameters is None
    assert set(caps[CapabilityType.MODE].supported_yandex_modes) == {
        ModeCapabilityMode.AUTO, ModeCapabilityMode.LOW, ModeCapabilityMode.MEDIUM,
        ModeCapabilityMode.HIGH, ModeCapabilityMode.MAX,
    }
    for yandex_mode, expected_option, gate in [
        ('low', 'Малое', 1), ('medium', 'Среднее', 2),
        ('high', 'Большое', 3), ('max', 'Полное', 4), ('auto', 'Авто', None),
    ]:
        await capabilities()[CapabilityType.MODE].set_instance_state(Context(), ModeCapabilityInstanceActionState(
            instance=ModeCapabilityInstance.PROGRAM, value=ModeCapabilityMode(yandex_mode)))
        assert hass.states.get(select_id).state == expected_option
        saved = json.loads(hass.states.get(inputs['memory_entity']).state)
        assert saved['mode'] == ('super_auto' if yandex_mode == 'auto' else 'manual')
        if gate:
            assert saved['gate'] == gate and hass.states.get(cover_id).attributes['current_position'] == gate * 25
        assert capabilities()[CapabilityType.MODE].get_value() == yandex_mode
        assert capabilities()[CapabilityType.ON_OFF].get_value() is True
    for power, expected in [(False, 'Нет'), (True, 'Полное')]:
        await capabilities()[CapabilityType.ON_OFF].set_instance_state(Context(), OnOffCapabilityInstanceActionState(
            instance=OnOffCapabilityInstance.ON, value=power))
        assert hass.states.get(select_id).state == expected
        assert capabilities()[CapabilityType.ON_OFF].get_value() is power
        if not power:
            assert capabilities()[CapabilityType.MODE].get_value() is None
    for mode, gate, expected in [('super_auto', 2, 'auto'), ('manual', 3, 'high')]:
        await run('report', {'mode': mode, 'on_off': 'on', 'gate': gate})
        assert capabilities()[CapabilityType.MODE].get_value() == expected
    await run('workmode', payload='super_auto')
    assert capabilities()[CapabilityType.MODE].get_value() == 'auto'
    await run('restart')
    assert capabilities()[CapabilityType.MODE].get_value() == 'auto'
    props = {p.instance: p.get_value() for p in device().get_properties()}
    assert props['temperature'] == 22.5 and props['humidity'] == 45
    description = await device().describe()
    assert description.type == DeviceType.VENTILATION
    assert len(description.capabilities) == 2 and len(description.properties) == 2
    # Existing filters are intentionally not changed by this package.
    assert 'filter' not in validated
    hass.states.async_set(cover_id, 'unavailable')
    assert device().unavailable is True
    print('PASS: YaHA schema/device description; all modes -> select -> blueprint -> memory/MQTT/state; on/off; buttons; raw workmode; restore; temperature/humidity; unavailable; example export filter')
    await hass.async_stop()

if __name__ == '__main__':
    asyncio.run(main())
