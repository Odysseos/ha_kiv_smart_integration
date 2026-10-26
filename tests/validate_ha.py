# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 vakio-kiv-ha contributors

"""Regression tests with Home Assistant 2025.10.4, Python 3.13.
Uses HA Script, templates, input_text and MQTT schemas; captures mqtt.publish.
"""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
import logging
from pathlib import Path
import tempfile
from unittest.mock import patch
import yaml
from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.helpers import config_validation as cv, script, template
from homeassistant.components.mqtt import MQTT_PUBLISH_SCHEMA
from homeassistant.components.mqtt import cover, select, sensor
from homeassistant.util import dt

ROOT = Path(__file__).resolve().parents[1]
class Loader(yaml.SafeLoader):
    pass
Loader.add_constructor('!input', lambda loader, node: {'__input__': loader.construct_scalar(node)})
RAW = yaml.load((ROOT / 'manual/blueprints/automation/vakio_cover.yaml').read_text(), Loader=Loader)

def resolve(value, inputs):
    if isinstance(value, dict):
        if '__input__' in value:
            return inputs[value['__input__']]
        return {k: resolve(v, inputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, inputs) for v in value]
    return value

class Instance:
    async def setup(self, hass, ident, raw=RAW):
        self.hass = hass
        self.ident = ident
        self.entity = 'input_text.' + ident
        inputs = dict(topic_prefix=ident, id_prefix=ident, device_name=ident,
                      memory_entity=self.entity, boot_report_window=0.03)
        self.cfg = resolve(raw, inputs)
        actions = await script.async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(self.cfg['actions']))
        self.runner = script.Script(hass, actions, ident, 'automation', script_mode=self.cfg['mode'])
        return self

    async def run(self, kind, caps=None, payload=None):
        trigger = {'id': kind, 'payload': payload if payload is not None else json.dumps({'capabilities': caps or {}})}
        variables = cv.SCRIPT_VARIABLES_SCHEMA(self.cfg['variables']).async_render(self.hass, {'trigger': trigger})
        return await self.runner.async_run(variables, Context())

    def memory(self):
        return json.loads(self.hass.states.get(self.entity).state)

    async def clear(self):
        await self.hass.services.async_call('input_text', 'set_value', {'entity_id': self.entity, 'value': ''}, blocking=True)

async def main():
    logging.basicConfig(level=logging.ERROR)
    hass = HomeAssistant(tempfile.mkdtemp(prefix='vakio-ha-regression-'))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    dt.set_default_time_zone(dt.get_time_zone('Europe/Moscow'))
    hass.config.time_zone = 'Europe/Moscow'
    assert await async_setup_component(hass, 'input_text', {'input_text': {'one': {'max': 255}, 'two': {'max': 255}}})
    published = []
    states = {}
    async def publish(call):
        data = dict(call.data)
        published.append(data)
        states[data['topic']] = data['payload']
    hass.services.async_register('mqtt', 'publish', publish, schema=MQTT_PUBLISH_SCHEMA)
    one = await Instance().setup(hass, 'one')
    two = await Instance().setup(hass, 'two')
    def state(ident, suffix):
        return states[f'vakio_ha/{ident}/json/{suffix}']
    def tx(ident):
        return [json.loads(p['payload']) for p in published if p['topic'] == f'server/{ident}/kivsmart/mode']
    def mode_tx(ident):
        return [p['payload'] for p in published if p['topic'] == f'{ident}/workmode']
    def render(text, **variables):
        return template.Template(text, hass).async_render(variables, parse_result=False)

    # An input_text with unknown state must initialize without waiting for a value.
    assert hass.states.get('input_text.one').state == 'unknown'
    broken = deepcopy(RAW)
    broken['actions'][1]['wait_template'] = "{{ states(memory_entity) not in ['unknown', 'unavailable'] }}"
    old = await Instance().setup(hass, 'one', broken)
    for kind, caps in [('restart', None), ('command', {'mode': 'manual', 'on_off': 'on', 'gate': 2}),
                       ('report', {'mode': 'manual', 'on_off': 'on', 'gate': 1}),
                       ('command', {'mode': 'super_auto', 'on_off': 'on'})]:
        task = asyncio.create_task(old.run(kind, caps))
        await asyncio.sleep(0.015)
        assert not task.done() and not published
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert hass.states.get('input_text.one').state == 'unknown'
    print('PASS: original guard blocks startup, UI, buttons and auto with a real fresh input_text')

    await one.run('restart')
    assert one.memory()['mode'] == 'manual'
    assert state('one', 'cover/position') in ['25', '50', '75', '100']
    config = json.loads(states['homeassistant/device/one/config'])
    components = config['components']
    for key, module in [('cover', cover), ('selection', select), ('temperature', sensor), ('humidity', sensor)]:
        module.DISCOVERY_SCHEMA(components[key])
    assert components['cover']['command_topic'] == 'vakio_ha/one/json/command'
    assert components['cover']['set_position_topic'] == 'vakio_ha/one/json/command'
    assert components['selection']['command_topic'] == 'vakio_ha/one/json/command'
    assert components['cover']['position_topic'] == 'vakio_ha/one/json/cover/position'

    # Render the actual discovered command templates with HA, then receive them.
    for position in [0, 25, 50, 75, 100, 50]:
        message = render(components['cover']['set_position_template'], position=position)
        before = len(published)
        await one.run('ui_command', payload=message)
        assert state('one', 'cover/position') == str(position)
        assert one.memory()['power'] == ('off' if position == 0 else 'on')
        commands = [p for p in published[before:] if p['topic'] in ['one/workmode', 'server/one/kivsmart/mode']]
        assert [p['topic'] for p in commands] == ['one/workmode', 'server/one/kivsmart/mode']
        assert mode_tx('one')[-1] == 'manual'
        assert 'mode' not in tx('one')[-1]['capabilities']
        await asyncio.sleep(0.04)
        assert state('one', 'cover/position') == str(position)
    for option in components['selection']['options']:
        await one.run('ui_command', payload=render(components['selection']['command_template'], value=option))
        assert state('one', 'selection/state') == option
    before = len(published)
    await one.run('ui_command', payload=render(components['selection']['command_template'], value='Авто'))
    assert one.memory()['mode'] == 'super_auto'
    assert state('one', 'selection/state') == 'Авто'
    commands = [p for p in published[before:] if p['topic'] in ['one/workmode', 'server/one/kivsmart/mode']]
    assert [p['topic'] for p in commands] == ['server/one/kivsmart/mode', 'one/workmode']
    assert mode_tx('one')[-1] == 'super_auto'
    assert 'mode' not in tx('one')[-1]['capabilities']
    await one.run('restart')
    assert mode_tx('one')[-1] == 'super_auto'
    await one.run('report', {'mode': 'manual', 'on_off': 'on', 'gate': 1})
    assert one.memory()['gate'] == 1 and state('one', 'cover/position') == '25'
    await one.run('restart')
    assert tx('one')[-1]['capabilities']['gate'] == 1
    assert mode_tx('one')[-1] == 'manual'
    # Direct workmode commands update cache/UI, without republishing the command.
    for mode, expected in [('super_auto', 'Авто'), ('manual', 'Малое')]:
        before = len(mode_tx('one'))
        await one.run('workmode', payload=mode)
        assert one.memory()['mode'] == mode
        assert state('one', 'selection/state') == expected
        assert len(mode_tx('one')) == before
    # Leaving physical auto via percentage or selecting a manual option.
    for option in ['Среднее', 'Нет', 'Полное']:
        await one.run('report', {'mode': 'super_auto', 'on_off': 'on', 'gate': 1})
        assert state('one', 'selection/state') == 'Авто'
        await one.run('ui_command', payload=render(components['selection']['command_template'], value=option))
        assert one.memory()['mode'] == 'manual' and mode_tx('one')[-1] == 'manual'
        assert state('one', 'selection/state') == option
    print('PASS: Discovery schemas, all cover/select commands, auto, physical report and restored commands')

    for month, gate in {1:1, 2:1, 3:2, 4:3, 5:4, 6:4, 7:4, 8:4, 9:4, 10:3, 11:2, 12:1}.items():
        await two.clear()
        with patch('homeassistant.util.dt.now', return_value=datetime(2026, month, 15, tzinfo=dt.DEFAULT_TIME_ZONE)):
            await two.run('restart')
        assert two.memory()['gate'] == gate
        await two.run('restart')
        assert two.memory()['gate'] == gate

    await one.run('command', {'mode': 'manual', 'on_off': 'on', 'gate': 3})
    for kind in ['command', 'boot']:
        older = asyncio.create_task(one.run('report', {'mode': 'manual', 'on_off': 'on', 'gate': 1}))
        await asyncio.sleep(0.01)
        await one.run(kind, {'mode': 'manual', 'on_off': 'on', 'gate': 3})
        await older
        assert one.memory()['gate'] == 3 and state('one', 'cover/position') == '75'
    original = one.memory()
    for payload in ['not JSON', '{"settings":{"gate":1}}', '{"relation":{}}']:
        await one.run('report', payload=payload)
        assert one.memory() == original
    await two.run('command', {'mode': 'manual', 'on_off': 'on', 'gate': 2})
    assert one.memory()['gate'] == 3 and two.memory()['gate'] == 2
    await one.run('boot')
    assert tx('one')[-1]['capabilities']['gate'] == 3
    assert two.memory()['gate'] == 2
    print('PASS: 12 months, saved targets, report/command/auth races, invalid reports, independent devices')

    # Deliver own MQTT publications back through the subscribed event routes.
    # Any accidental command retransmission will keep the task queue nonempty.
    pending = []
    async def loopback(call):
        await publish(call)
        for instance in [one, two]:
            ident = instance.ident
            kind = 'command' if call.data['topic'] == f'server/{ident}/kivsmart/mode' else 'workmode' if call.data['topic'] == f'{ident}/workmode' else None
            if kind:
                pending.append(asyncio.create_task(instance.run(kind, payload=call.data['payload'])))
    hass.services.async_register('mqtt', 'publish', loopback, schema=MQTT_PUBLISH_SCHEMA)
    async def drain():
        for _ in range(6):
            if not pending:
                return
            tasks = pending[:]
            pending.clear()
            await asyncio.gather(*tasks)
        raise AssertionError('MQTT feedback loop')
    for mode in ['super_auto', 'manual']:
        await one.run('ui_command', {'mode': mode, 'on_off': 'on', 'gate': 2})
        await drain()
        assert one.memory()['mode'] == mode and mode_tx('one')[-1] == mode
    await one.run('workmode', payload='super_auto')
    await drain()
    assert state('one', 'selection/state') == 'Авто'
    await one.run('command', {'mode': 'manual', 'on_off': 'on', 'gate': 3})
    await drain()
    assert state('one', 'selection/state') == 'Большое' and mode_tx('one')[-1] == 'manual'
    await one.run('ui_command', {'mode': 'super_auto', 'on_off': 'on'})
    await drain()
    for event in ['restart', 'boot']:
        await one.run(event)
        await drain()
        assert state('one', 'selection/state') == 'Авто' and mode_tx('one')[-1] == 'super_auto'
    assert two.memory()['mode'] == 'manual' and two.memory()['gate'] == 2
    assert all(not p['retain'] for p in published if p['topic'].startswith('server/') or p['topic'].endswith('/workmode'))
    print('PASS: raw workmode, auto/manual command order, physical-auto exit, restart/auth restore, own MQTT echoes without loops')
    await hass.async_stop()

if __name__ == '__main__':
    asyncio.run(main())
