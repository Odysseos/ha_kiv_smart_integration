// SPDX-License-Identifier: GPL-3.0-only
// Browser lifecycle regression with the same scoped-registry polyfill as HA.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const dependencies = resolve(process.argv[2] ?? ".deps/browser/node_modules");
const { firefox } = require(require.resolve("playwright", { paths: [dependencies] }));
const shim = await readFile(process.argv[3] ?? resolve(dependencies,
  "@webcomponents/scoped-custom-element-registry/scoped-custom-element-registry.min.js"), "utf8");
const source = await readFile(new URL("../custom_components/vakio_kiv_local/www/overview.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const browser = await firefox.launch({
  headless: true,
  firefoxUserPrefs: { "security.sandbox.content.level": 0 },
});
try {
  for (const early of [true, false]) {
    const page = await browser.newPage();
    if (early) await page.evaluate(async (url) => { await import(url); }, moduleUrl);
    await page.addScriptTag({ content: shim });
    await page.evaluate(() => {
      customElements.define("home-assistant", class extends HTMLElement {});
      customElements.define("home-area-view-strategy", class extends HTMLElement {
        static async generate() {
          return { type: "sections", sections: [{ type: "grid", cards: [
            { type: "heading", heading: "Valve" },
            { type: "tile", entity: "cover.valve", features: [{ type: "cover-open-close" }] },
          ] }] };
        }
      });
    });
    if (!early) await page.evaluate(async (url) => { await import(url); }, moduleUrl);
    const result = await page.evaluate(async () => {
      const hass = { states: { "cover.valve": {
        entity_id: "cover.valve", state: "open",
        attributes: { device_class: "damper", vakio_kiv_local_overview_climate: true },
      } }, entities: {}, localize: () => "Climate" };
      // Lazy loading of the global Climate strategy after app initialization.
      customElements.define("climate-view-strategy", class extends HTMLElement {
        static async generate(config, input) {
          return { cards: Object.values(input.states).filter((s) =>
            s.entity_id.startsWith("cover.") && !s.attributes.device_class
          ).map((s) => ({ type: "tile", entity: s.entity_id })) };
        }
      });
      await Promise.resolve();
      const room = customElements.get("home-area-view-strategy");
      const view = await room.generate({}, hass);
      const climate = await customElements.get("climate-view-strategy").generate({}, hass);
      return {
        patched: !!room.generate[Symbol.for("vakio_kiv_local.overview.wrapper")],
        heading: view.sections[0].cards[0].icon,
        entities: view.sections.flatMap((s) => s.cards).filter((c) => c.entity).map((c) => c.entity),
        features: view.sections[0].cards[1].features,
        globalEntities: climate.cards.map((c) => c.entity),
        realClass: hass.states["cover.valve"].attributes.device_class,
      };
    });
    assert.equal(result.patched, true);
    assert.equal(result.heading, "mdi:home-thermometer");
    assert.deepEqual(result.entities, ["cover.valve"]);
    assert.deepEqual(result.globalEntities, ["cover.valve"]);
    assert.deepEqual(result.features, [{ type: "cover-open-close" }]);
    assert.equal(result.realClass, "damper");
    await page.close();
    console.log(`PASS: Firefox ${await browser.version()}; module ${early ? "before" : "after"} scoped registry; automatic wrapping; room move; lazy Climate panel; class and controls retained`);
  }
} finally {
  await browser.close();
}
