// Tests dels palets editables de les etiquetes. Executar: `node --test tests/test_etiquetes.mjs`
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { ajustaPalets, sumaSacs } = require("../static/js/etiquetes.js");

const proposta = [
    { sacs: 40, articles: [{ art_codi: "A" }], tipus_palet: "EU" },
    { sacs: 40, articles: [{ art_codi: "A" }], tipus_palet: "EU" },
    { sacs: 25, articles: [{ art_codi: "B" }], tipus_palet: "EU" },
];

test("de 3 a 4 palets: el nou copia l'últim", () => {
    const r = ajustaPalets(proposta, 4);
    assert.equal(r.length, 4);
    assert.equal(r[3].sacs, 25);
    assert.deepEqual(r[3].articles, [{ art_codi: "B" }]);
    assert.notEqual(r[3].articles, proposta[2].articles);   // còpia, no la mateixa llista
});

test("de 3 a 2 palets: es treu l'últim", () => {
    assert.deepEqual(ajustaPalets(proposta, 2).map(p => p.sacs), [40, 40]);
});

test("no toca la proposta original", () => {
    const r = ajustaPalets(proposta, 3);
    r[0].sacs = 1;
    assert.equal(proposta[0].sacs, 40);
});

test("com a mínim 1 palet i com a màxim 99", () => {
    assert.equal(ajustaPalets(proposta, 0).length, 1);
    assert.equal(ajustaPalets(proposta, "abc").length, 1);
    assert.equal(ajustaPalets(proposta, 500).length, 99);
});

test("sumaSacs", () => {
    assert.equal(sumaSacs(proposta), 105);
});
