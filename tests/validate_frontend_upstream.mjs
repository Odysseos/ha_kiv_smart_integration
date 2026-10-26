// SPDX-License-Identifier: GPL-3.0-only
// Optional source-level check. UI feature support functions are stubbed; actual
// upstream room generators, grouping filters and context resolution execute.
import {readFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import vm from 'node:vm';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const checkout = process.argv[2];
assert(checkout, "Pass a Home Assistant frontend checkout path");
const root = pathToFileURL(resolve(checkout, 'src') + '/');
const ctx=vm.createContext({console});
vm.runInContext(`
class ReactiveElement {}
const ensureArray = value => Array.isArray(value) ? value : [value];
const computeDomain = id => id.split('.')[0];
const clamp = (v,min,max) => Math.min(max,Math.max(min,v));
const computeDeviceName = device => device.name;
const computeStateName = state => state.attributes.friendly_name || state.entity_id;
const stripPrefixFromEntityName = name => name;
const floorDefaultIcon = () => 'mdi:home';
const isComponentLoaded = () => false;
const OTHER_DEVICES_FILTERS = [];
const filterSecurityAlertEntities = () => [];
const computeDefaultSecurityAlertVisibility = () => [];
const resolveShortcutItems = () => [{type:'summary',key:'climate'}];
const SMALL_SCREEN_CONDITION = {};
const LARGE_SCREEN_CONDITION = {};
const orderCompare = () => () => 0;
const supportsCoverOpenCloseCardFeature = (hass,context) => context.entity_id.startsWith('cover.');
const supportsLightBrightnessCardFeature = () => false;
const supportsTargetTemperatureCardFeature = () => false;
const supportsFanSpeedCardFeature = () => false;
const supportsAlarmModesCardFeature = () => false;
const supportsLockCommandsCardFeature = () => false;
const maintenanceEntityFilters = [];
const lightEntityFilters = [{domain:'light'}];
const securityEntityFilters = [{domain:'alarm_control_panel'}];
`,ctx);
async function load(path){
 let source=await readFile(new URL(path, root),'utf8');
 source=source.replace(/^import\s[\s\S]*?;\s*$/gm,'').replace(/^@customElement\([^\n]*\)\s*$/gm,'');
 source=stripTypeScriptTypes(source,{mode:'transform'}).replace(/\bexport /g,'');
 vm.runInContext(source,ctx,{filename:path});
}
await load('common/areas/areas-floor-hierarchy.ts');
await load('common/entity/context/get_device_context.ts');
await load('common/entity/context/get_entity_context.ts');
await load('common/entity/entity_filter.ts');
await load('panels/climate/strategies/climate-view-strategy.ts');
await load('panels/lovelace/strategies/home/helpers/home-summaries.ts');
await load('panels/lovelace/strategies/areas/helpers/areas-strategy-helper.ts');
await load('panels/lovelace/strategies/home/home-area-view-strategy.ts');
await load('panels/lovelace/strategies/areas/area-view-strategy.ts');
await load('panels/lovelace/strategies/home/home-overview-view-strategy.ts');
const {moveToClimate,install}=await import(new URL("../custom_components/vakio_kiv_local/www/overview.js", import.meta.url));
const hass={states:{},entities:{},devices:{one:{id:'one',name:'First',area_id:'room'},two:{id:'two',name:'Second',area_id:'other'}},areas:{room:{area_id:'room',name:'Room'},other:{area_id:'other',name:'Other'}},floors:{},panels:{climate:{}},config:{components:[]},connection:{},user:{is_admin:true},localize:key=>key==='panel.climate'?'Климат':key};
for(const [id,device] of [['cover.first','one'],['cover.second','two'],['select.mode','one'],['climate.ac','one']]){
 hass.states[id]={entity_id:id,state:'open',attributes:id.startsWith('cover.')?{device_class:'damper',vakio_kiv_local_overview_climate:true}:{}};
 hass.entities[id]={entity_id:id,device_id:device,platform:'vakio_kiv_local',labels:[]};
}
for(const cls of ['HomeAreaViewStrategy','AreaViewStrategy']){
 const Strategy=vm.runInContext(cls,ctx);
 const view=await Strategy.generate({area:'room'},hass);
 const result=moveToClimate(view,hass);
 const group=result.sections.find(s=>s.cards?.[0]?.icon==='mdi:home-thermometer');
 assert(group.cards.some(c=>c.entity==='cover.first'));
 assert(group.cards.some(c=>c.entity==='climate.ac'));
 assert.equal(result.sections.flatMap(s=>s.cards??[]).filter(c=>c.entity==='cover.first').length,1);
 assert(!JSON.stringify(result).includes('cover.second'));
 assert.equal(hass.states['cover.first'].attributes.device_class,'damper');
 console.log('PASS: actual upstream',cls,'generate -> extension -> Climate in correct room');
}

const classes = new Map([
  ["climate-view-strategy", vm.runInContext("ClimateViewStrategy",ctx)],
  ["home-overview-view-strategy", vm.runInContext("HomeOverviewViewStrategy",ctx)],
]);
install({ get: tag => classes.get(tag), whenDefined: () => new Promise(() => {}) });
const climate = await classes.get("climate-view-strategy").generate({},hass);
const entities = climate.sections.flatMap(s=>s.cards??[]).map(c=>c.entity).filter(Boolean);
assert(entities.includes('cover.first'));
assert(entities.includes('cover.second'));
assert.equal(entities.filter(id=>id==='cover.first').length,1);
assert.equal(hass.states['cover.first'].attributes.device_class,'damper');
// Only our covers: Climate must still be reachable from the main overview.
const onlyValves = {...hass,states:{...hass.states}};
delete onlyValves.states['climate.ac'];
const overview = await classes.get('home-overview-view-strategy').generate({hide_suggested_entities:true},onlyValves);
assert(overview.sections.flatMap(s=>s.cards??[]).some(c=>c.type==='home-summary'&&c.summary==='climate'));
// Native filtering still excludes hidden covers.
const hidden = {...hass,entities:{...hass.entities,'cover.first':{...hass.entities['cover.first'],hidden:true}}};
const hiddenView = await classes.get('climate-view-strategy').generate({},hidden);
assert(!hiddenView.sections.flatMap(s=>s.cards??[]).some(c=>c.entity==='cover.first'));
console.log('PASS: actual upstream Climate and overview strategies; room grouping; hidden entities; only Vakio covers; real class preserved');
