// SPDX-License-Identifier: GPL-3.0-only
// HA's built-in strategy classes are not a public extension API.
const MARKER = "vakio_kiv_local_overview_climate";
const WRAPPED = Symbol.for("vakio_kiv_local.overview.wrapper");
const CLIMATE_ICON = "mdi:home-thermometer";

// These strategies create room views in the standard automatic dashboards.
const ROOM_STRATEGIES = ["home-area-view-strategy", "area-view-strategy"];
const CLIMATE_STRATEGIES = ["climate-view-strategy", "home-climate-view-strategy"];
const OVERVIEW_STRATEGIES = ["home-overview-view-strategy", "home-main-view-strategy"];
export const STRATEGIES = [...ROOM_STRATEGIES, ...CLIMATE_STRATEGIES, ...OVERVIEW_STRATEGIES];

function eligibleCovers(hass) {
  return Object.keys(hass.states ?? {}).filter((id) => {
    const state = hass.states[id];
    return id.startsWith("cover.") && state.attributes?.device_class === "damper" &&
      state.attributes[MARKER] === true &&
      (!hass.entities?.[id]?.platform || hass.entities[id].platform === "vakio_kiv_local");
  });
}

export function climateGroupingHass(hass) {
  const ids = eligibleCovers(hass);
  if (!ids.length) return hass;
  const states = { ...hass.states };
  for (const id of ids) {
    const state = states[id];
    // Built-in Climate filters accept a generic cover. Only the generator
    // receives this copy; cards and backend entities retain their real damper.
    const attributes = { ...state.attributes };
    delete attributes.device_class;
    states[id] = { ...state, attributes };
  }
  return { ...hass, states };
}

export function moveToClimate(view, hass) {
  if (!Array.isArray(view?.sections)) return view;
  // Match our explicit marker, not names or MQTT prefixes. Entity renames work.
  const eligible = new Set(eligibleCovers(hass));
  if (!eligible.size) return view;

  const sections = view.sections;
  const climateIndex = sections.findIndex((section) =>
    section.type === "grid" && section.cards?.[0]?.type === "heading" &&
    section.cards[0].icon === CLIMATE_ICON);
  const moved = [];
  // Work on copies: never change the original strategy result or hass.states.
  const next = sections.map((section, index) => {
    if (section.type !== "grid" || !Array.isArray(section.cards)) return section;
    if (index === climateIndex) return section;
    const cards = section.cards.filter((card) => {
      if (card.type !== "tile" || !eligible.has(card.entity)) return true;
      // Hidden cards already excluded by HA stay excluded. Never create a tile
      // from states, and never touch nested/custom cards or other integrations.
      if (!moved.some((existing) => existing.entity === card.entity)) {
        const tile = { ...card };
        // Device sections use entity-only labels. In a shared climate section
        // retain the device name, otherwise two valves look identical.
        if (tile.name?.type === "entity") delete tile.name;
        moved.push(tile);
      }
      return false;
    });
    return cards.length === section.cards.length ? section : { ...section, cards };
  });
  if (!moved.length) return view;

  const alreadyInClimate = new Set(sections[climateIndex]?.cards?.map((card) => card.entity));
  const additions = moved.filter((card) => !alreadyInClimate.has(card.entity));
  if (climateIndex >= 0) {
    next[climateIndex] = {
      ...next[climateIndex], cards: [...next[climateIndex].cards, ...additions],
    };
  } else {
    const heading = hass.localize?.("panel.climate") ||
      hass.localize?.("ui.panel.lovelace.strategy.areas.groups.climate") || "Climate";
    next.unshift({ type: "grid", cards: [
      { type: "heading", heading, icon: CLIMATE_ICON }, ...additions,
    ] });
  }
  // Remove only a section emptied by this move; preserve unrelated headings.
  const populated = next.filter((section, index) => {
    const original = climateIndex < 0 ? sections[index - 1] : sections[index];
    return !original || section.cards === original.cards ||
      section.cards.some((card) => card.type !== "heading");
  });
  // Home-area inserts a blank divider before device groups. Drop it when
  // moving the final device tile leaves only the divider (or automations).
  const cleaned = populated.filter((section, index) => {
    const heading = section.cards?.[0];
    const divider = section.column_span === 3 && section.cards.length === 1 &&
      heading?.type === "heading" && heading.heading === "" &&
      heading.heading_style === "subtitle";
    return !divider || (index < populated.length - 1 &&
      populated[index + 1].cards?.[0]?.icon !== "mdi:robot");
  });
  if (cleaned.length === 1 && cleaned[0].cards?.[0]?.icon === CLIMATE_ICON) {
    cleaned[0] = { ...cleaned[0], column_span: 2 };
  }
  return { ...view, sections: cleaned };
}

export function install(registry = globalThis.customElements, getRegistry = () => globalThis.customElements ?? registry) {
  for (const tag of STRATEGIES) {
    const wrap = () => {
      try {
        const strategy = [getRegistry()?.get(tag), registry.get(tag)]
          .find((candidate) => typeof candidate?.generate === "function");
        if (typeof strategy?.generate !== "function" || strategy.generate[WRAPPED]) return;
        const original = strategy.generate;
        const generate = async function (config, hass, ...rest) {
          const room = ROOM_STRATEGIES.includes(tag);
          const input = room ? hass : climateGroupingHass(hass);
          const view = await original.call(this, config, input, ...rest);
          try {
            return room ? moveToClimate(view, hass) : view;
          } catch (error) {
            console.warn("Vakio KIV Local: Overview extension skipped", error);
            return view;
          }
        };
        generate[WRAPPED] = true;
        strategy.generate = generate;
      } catch (error) {
        console.warn("Vakio KIV Local: unsupported Overview strategy", error);
      }
    };
    if (registry.get(tag)) wrap();
    else registry.whenDefined(tag).then(wrap).catch((error) =>
      console.warn("Vakio KIV Local: unsupported Overview strategy", error));
  }
}

export function start(getRegistry = () => globalThis.customElements, events = globalThis) {
  const refresh = () => install(getRegistry(), getRegistry);
  const initial = getRegistry();
  install(initial, getRegistry);
  // Panels load strategies on demand. Reconnect subscriptions to the current
  // registry before each navigation, without replacing registry methods.
  events.addEventListener?.("location-changed", refresh);
  events.addEventListener?.("popstate", refresh);
  // HA's app entrypoint installs the scoped-registry polyfill after extra
  // modules may already have run. Resolve strategy classes in the app's
  // current registry, not the earlier registry's native stand-in classes.
  initial.whenDefined("home-assistant").then(() => {
    refresh();
  }).catch((error) => console.warn("Vakio KIV Local: app initialization failed", error));
}

if (typeof customElements !== "undefined") start();
