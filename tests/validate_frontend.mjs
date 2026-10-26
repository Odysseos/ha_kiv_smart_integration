// SPDX-License-Identifier: GPL-3.0-only
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const source = await readFile(new URL("../custom_components/vakio_kiv_local/www/overview.js", import.meta.url), "utf8");
const { moveToClimate, climateGroupingHass, install, start, STRATEGIES } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const marker = "vakio_kiv_local_overview_climate";
const icon = "mdi:home-thermometer";
const tile = (entity, extra = {}) => ({ type: "tile", entity, ...extra });
const section = (heading, cards, extra = {}) => ({ type: "grid", cards: [{ type: "heading", heading, ...extra }, ...cards] });
const hass = {
  states: {
    "cover.valve_one": { attributes: { device_class: "damper", [marker]: true } },
    "cover.renamed_valve": { attributes: { device_class: "damper", [marker]: true } },
    "cover.disabled_valve": { attributes: { device_class: "damper", [marker]: false } },
    "cover.foreign": { attributes: { device_class: "damper" } },
  },
  entities: { "cover.valve_one": { platform: "vakio_kiv_local" } },
  localize: (key) => key === "panel.climate" ? "Климат" : "",
};
function freeze(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
freeze(hass);
// Real strategy output structure: room grid, device heading + tiles, full
// device name only in heading; tile uses entity-only name within that device.
const first = freeze({ type: "sections", max_columns: 3, sections: [
  section("Свет", [tile("light.room")], { icon: "mdi:lamps" }),
  section("Климат", [tile("climate.ac")], { icon }),
  section("Vakio", [tile("cover.valve_one", { name: { type: "entity" }, features: [{ type: "cover-open-close" }] }), tile("select.valve")]),
  section("Other", [tile("cover.foreign"), tile("cover.disabled_valve")]),
] });
const changed = moveToClimate(first, hass);
assert.equal(changed.sections[1].cards.at(-1).entity, "cover.valve_one");
assert.equal(changed.sections[1].cards.at(-1).name, undefined);
assert.deepEqual(changed.sections[1].cards.at(-1).features, [{ type: "cover-open-close" }]);
assert.deepEqual(changed.sections[2].cards.map((c) => c.entity).filter(Boolean), ["select.valve"]);
assert.equal(changed.sections[3], first.sections[3]);
assert.equal(moveToClimate(changed, hass), changed); // Idempotent.
assert.equal(hass.states["cover.valve_one"].attributes.device_class, "damper");
assert.equal(first.sections[2].cards.length, 3); // Original not mutated.
// No climate yet; support legacy area's Covers group and renamed entity IDs.
const only = freeze({ type: "sections", sections: [section("Шторы", [tile("cover.renamed_valve")])] });
const created = moveToClimate(only, hass);
assert.equal(created.sections.length, 1);
assert.equal(created.sections[0].cards[0].heading, "Климат");
assert.equal(created.sections[0].cards[1].entity, "cover.renamed_valve");
const divider = { type: "grid", column_span: 3, cards: [{ type: "heading", heading: "", heading_style: "subtitle" }] };
const lone = moveToClimate({ sections: [divider, section("Vakio", [tile("cover.valve_one")])] }, hass);
assert.equal(lone.sections.length, 1);
assert.equal(lone.sections[0].column_span, 2);
// Different rooms are not mixed: only cards already in this view can move.
assert(!JSON.stringify(created).includes("cover.valve_one"));
// Hidden cards absent from HA output stay absent, even when present in states.
const hidden = { type: "sections", sections: [section("Свет", [tile("light.room")])] };
assert.equal(moveToClimate(hidden, hass), hidden);
assert.equal(moveToClimate(first, { ...hass, states: {} }), first);
// Leave unsupported layouts, custom cards, nested cards and non-cover markers.
const custom = { sections: [section("Custom", [{ type: "custom:test", entity: "cover.valve_one" }])] };
assert.equal(moveToClimate(custom, hass), custom);
assert.equal(moveToClimate({ type: "panel", cards: [] }, hass).type, "panel");
// A duplicate source card must not duplicate the destination tile.
const duplicate = { sections: [section("Климат", [tile("cover.valve_one")], { icon }), section("Vakio", [tile("cover.valve_one")])] };
assert.equal(moveToClimate(duplicate, hass).sections.flatMap((s) => s.cards).filter((c) => c.entity === "cover.valve_one").length, 1);
// Immediate registration, lazy registration, repeated module install and error fallback.
const definitions = new Map();
const waiting = new Map();
const registry = {
  get: (tag) => definitions.get(tag),
  whenDefined: (tag) => new Promise((resolve) => waiting.set(tag, resolve)),
};
let calls = 0;
class Existing { static async generate(config, actual) { assert.equal(actual, hass); calls++; return first; } }
definitions.set(STRATEGIES[0], Existing);
install(registry);
const wrapped = Existing.generate;
install(registry);
assert.equal(Existing.generate, wrapped);
assert.deepEqual(await Existing.generate({}, hass), changed);
assert.equal(calls, 1);
class Lazy { static async generate() { return only; } }
definitions.set(STRATEGIES[1], Lazy);
waiting.get(STRATEGIES[1])();
await Promise.resolve();
assert.deepEqual(await Lazy.generate({}, hass), created);
const expected = new Error("HA strategy failed");
class Broken { static async generate() { throw expected; } }
install({ get: () => Broken });
await assert.rejects(Broken.generate({}, hass), (error) => error === expected);
const malformed = { get sections() { throw new Error("future incompatible layout"); } };
class Future { static async generate() { return malformed; } }
install({ get: () => Future });
const warn = console.warn;
try { console.warn = () => {}; assert.equal(await Future.generate({}, hass), malformed); }
finally { console.warn = warn; }
class Sealed { static async generate() { return first; } }
Object.freeze(Sealed);
try { console.warn = () => {}; install({ get: () => Sealed }); }
finally { console.warn = warn; }
assert.equal(await Sealed.generate(), first);
console.log("PASS: Climate move; both room strategy tags; original states/config immutable; no duplicates; preserved controls; rooms; hidden/foreign/disabled entities; entity rename; lazy loading; repeated install; error fallback");

// A native registry and the scoped registry return different constructors.
// HA can replace the registry after extra modules have already subscribed.
function makeRegistry() {
  const classes = new Map();
  const resolvers = new Map();
  return {
    get: (tag) => classes.get(tag),
    whenDefined: (tag) => classes.has(tag) ? Promise.resolve(classes.get(tag)) :
      new Promise((resolve) => resolvers.set(tag, [...(resolvers.get(tag) ?? []), resolve])),
    define(tag, Class) {
      classes.set(tag, Class);
      for (const resolve of resolvers.get(tag) ?? []) resolve(Class);
    },
  };
}
const native = makeRegistry();
let current = native;
start(() => current);
const scoped = makeRegistry();
current = scoped;
class RoomAfterPolyfill { static async generate() { return first; } }
class StandIn {}
scoped.define("home-area-view-strategy", RoomAfterPolyfill);
native.define("home-area-view-strategy", StandIn);
scoped.define("home-assistant", class {});
native.define("home-assistant", StandIn);
await Promise.resolve();
await Promise.resolve();
assert.deepEqual(await RoomAfterPolyfill.generate({}, hass), changed);
assert.equal(StandIn.generate, undefined);
// A strategy loaded after app initialization is patched in the new registry.
class LazyAfterApp { static async generate() { return only; } }
scoped.define("area-view-strategy", LazyAfterApp);
await Promise.resolve();
assert.deepEqual(await LazyAfterApp.generate({}, hass), created);
const grouping = climateGroupingHass(hass);
assert.notEqual(grouping, hass);
assert.equal(grouping.states["cover.valve_one"].attributes.device_class, undefined);
assert.equal(hass.states["cover.valve_one"].attributes.device_class, "damper");
assert.equal(grouping.states["cover.disabled_valve"], hass.states["cover.disabled_valve"]);
assert.equal(grouping.states["cover.foreign"], hass.states["cover.foreign"]);
assert.equal(climateGroupingHass({ states: {} }).states !== undefined, true);
for (const tag of ["climate-view-strategy", "home-overview-view-strategy"]) {
  class Climate {
    static async generate(config, input) {
      assert.equal(input.states["cover.valve_one"].attributes.device_class, undefined);
      assert.equal(input.states["cover.disabled_valve"].attributes.device_class, "damper");
      return first;
    }
  }
  const r = makeRegistry();
  r.define(tag, Climate);
  install(r);
  assert.equal(await Climate.generate({}, hass), first);
}
console.log("PASS: native/scoped registry replacement; automatic and lazy strategy installation; Climate panel and overview grouping; real damper states preserved");

// A later panel may register in a registry different from the startup one.
const initialRegistry = makeRegistry();
let panelRegistry = initialRegistry;
const navigation = new EventTarget();
start(() => panelRegistry, navigation);
initialRegistry.define("home-assistant", class {});
await Promise.resolve();
panelRegistry = makeRegistry();
class LateClimate {
  static async generate(config, input) {
    assert.equal(input.states["cover.valve_one"].attributes.device_class, undefined);
    return first;
  }
}
panelRegistry.define("climate-view-strategy", LateClimate);
initialRegistry.define("climate-view-strategy", class {});
await Promise.resolve();
assert.equal(await LateClimate.generate({}, hass), first);
// Navigation also repairs a missed subscription when the old registry never
// emits a definition for a strategy owned by the new one.
panelRegistry = makeRegistry();
class NavigationClimate extends LateClimate {
  static async generate(config, input) {
    assert.equal(input.states["cover.valve_one"].attributes.device_class, undefined);
    return first;
  }
}
panelRegistry.define("climate-view-strategy", NavigationClimate);
navigation.dispatchEvent(new Event("location-changed"));
assert.equal(await NavigationClimate.generate({}, hass), first);
const once = NavigationClimate.generate;
navigation.dispatchEvent(new Event("popstate"));
assert.equal(NavigationClimate.generate, once);
console.log("PASS: late Climate panel in current registry; navigation recovery; no duplicate wrappers");
