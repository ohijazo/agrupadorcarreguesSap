// Pantalla "Etiquetes de palet" (/etiquetes). Una etiqueta per palet físic,
// amb el format que el magatzem feia amb Word. D'on surten les càrregues:
//   - /etiquetes?agrupacio=<id>  → les d'una agrupació desada;
//   - si no, les que la pàgina principal ha deixat a localStorage
//     ("etiquetes-carregues") en prémer "Etiquetes" amb càrregues seleccionades.
// Destí, Nº client i transport es poden corregir abans d'imprimir; no es desen.
// El nombre de palets i els sacs de cada palet els proposa el motor
// d'embalatges, però el magatzem els pot canviar: si un client passa de 3 a 4
// palets, surten 4 etiquetes "de 4".
"use strict";

const HANDOFF_KEY = "etiquetes-carregues";

// Capçalera de l'empresa (la mateixa que l'etiqueta de Word).
const EMPRESA = [
    "Carrer Girona, 155 · 17820 BANYOLES",
    "Tel. 972 58 00 58 · Fax 972 58 17 97",
    "comercial@agrienergia.com",
    "www.agrienergia.com",
];

const est = { clients: [], etiquetes: [], transport: {} };

function escE(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
}

function getCsrfTok() {
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
}

async function fetchJ(url, opts = {}) {
    const headers = new Headers(opts.headers || {});
    if (opts.method && opts.method !== "GET") headers.set("X-CSRF-Token", getCsrfTok());
    const r = await fetch(url, { credentials: "same-origin", ...opts, headers });
    if (r.status === 401) { window.location.href = "/login"; throw new Error("Sessió caducada"); }
    let j = null;
    try { j = await r.json(); } catch { /* sense cos */ }
    if (!r.ok) throw new Error((j && j.error) || `HTTP ${r.status}`);
    return j;
}

// Càrregues passades per la pàgina principal (vàlides 10 minuts).
function llegeixHandoff() {
    try {
        const raw = localStorage.getItem(HANDOFF_KEY);
        if (!raw) return null;
        const d = JSON.parse(raw);
        if (!d || !Array.isArray(d.carregues) || Date.now() - (d.ts || 0) > 10 * 60_000) return null;
        return d.carregues;
    } catch { return null; }
}

async function carrega() {
    const agr = new URLSearchParams(location.search).get("agrupacio");
    if (agr) return fetchJ(`/api/agrupacions/${encodeURIComponent(agr)}/etiquetes`);
    const carregues = llegeixHandoff();
    if (!carregues || !carregues.length) {
        throw new Error("No hi ha càrregues triades. Selecciona-les a Agrupar càrregues i prem \"Etiquetes\", o obre-les des d'una agrupació.");
    }
    return fetchJ("/api/etiquetes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ carregues }),
    });
}

// ---- Palets editables -------------------------------------------------------
// Ajusta la llista de palets d'un client a `n`: si puja, els nous copien els
// sacs i els articles de l'últim; si baixa, es treuen els últims. Pura.
function ajustaPalets(palets, n) {
    const m = Math.max(1, Math.min(99, Math.trunc(Number(n)) || 1));
    const out = palets.slice(0, m).map(p => ({ ...p }));
    const model = palets[palets.length - 1] || { sacs: 0, articles: [], tipus_palet: "" };
    while (out.length < m) out.push({ ...model, articles: [...(model.articles || [])] });
    return out;
}

function sumaSacs(palets) {
    return palets.reduce((t, p) => t + (Number(p.sacs) || 0), 0);
}

function htmlTotalSacs(c) {
    const total = sumaSacs(c.palets);
    const avis = total !== c.sacs_proposats
        ? ` <span class="etq-avis-sacs" title="El càlcul proposava ${c.sacs_proposats} sacs">(proposats: ${c.sacs_proposats})</span>`
        : "";
    return `Total ${total} sacs${avis}`;
}

function htmlPalets(c) {
    return `
        <div class="etq-palets">
            ${c.palets.map((p, i) => `
                <label class="etq-palet">P${i + 1}
                    <input type="number" inputmode="numeric" min="0" max="9999" step="1"
                           data-sacs="${escE(c.clau)}" data-i="${i}" value="${escE(p.sacs)}"
                           aria-label="Sacs del palet ${i + 1} de ${escE(c.cli_nom)}">
                </label>`).join("")}
            <span class="etq-total-sacs">${htmlTotalSacs(c)}</span>
            <button type="button" class="btn btn-sm etq-restaura" data-restaura="${escE(c.clau)}" ${c.editat ? "" : "hidden"}>Restaura</button>
        </div>`;
}

function marcaEditat(c) {
    c.editat = c.palets.length !== c.proposta.length
        || c.palets.some((p, i) => Number(p.sacs) !== Number(c.proposta[i].sacs));
}

// ---- Editor (taula per client) ------------------------------------------
function pintaTaula() {
    const perCarrega = new Map();
    for (const c of est.clients) {
        if (!perCarrega.has(c.carrega_id)) perCarrega.set(c.carrega_id, []);
        perCarrega.get(c.carrega_id).push(c);
    }
    let html = "";
    for (const [cid, clients] of perCarrega) {
        const c0 = clients[0];
        html += `
        <section class="etq-carrega">
            <header class="etq-carrega-cap">
                <strong>Càrrega #${escE(c0.carrega_num)}</strong> ${escE(c0.carrega_nom)}
                <label class="etq-camp etq-camp-transport">Transport
                    <input type="text" data-transport="${escE(cid)}" value="${escE(est.transport[cid])}" maxlength="40">
                </label>
            </header>
            <table class="etq-clients">
                <thead><tr><th></th><th>Client</th><th>Destí</th><th>Nº client</th><th class="num">Palets</th></tr></thead>
                <tbody>
                ${clients.map(c => `
                    <tr class="${c.inclou ? "" : "is-fora"}">
                        <td><input type="checkbox" data-inclou="${escE(c.clau)}" ${c.inclou ? "checked" : ""} aria-label="Treu etiquetes de ${escE(c.cli_nom)}"></td>
                        <td><div class="etq-cli">${escE(c.cli_nom)}</div><div class="etq-carrer">${escE(c.carrer)}</div></td>
                        <td><input type="text" data-desti="${escE(c.clau)}" value="${escE(c.desti)}" maxlength="30"></td>
                        <td><input type="text" inputmode="numeric" class="etq-num" data-nclient="${escE(c.clau)}" value="${escE(c.n_client_txt)}" maxlength="4"></td>
                        <td class="num"><input type="number" inputmode="numeric" class="etq-num" min="1" max="99" step="1"
                            data-npalets="${escE(c.clau)}" value="${c.palets.length}" aria-label="Palets de ${escE(c.cli_nom)}"></td>
                    </tr>
                    <tr class="etq-fila-palets ${c.inclou ? "" : "is-fora"}" data-palets-de="${escE(c.clau)}">
                        <td></td>
                        <td colspan="4">${htmlPalets(c)}</td>
                    </tr>`).join("")}
                </tbody>
            </table>
        </section>`;
    }
    document.getElementById("etq-taula").innerHTML = html;
}

// ---- Etiquetes ------------------------------------------------------------
function htmlEtiqueta(e, c, total) {
    const logo = document.body.dataset.logo;
    const marca = logo
        ? `<img class="etq-logo" src="${escE(logo)}" alt="Farinera Coromina">`
        : `<div class="etq-logo-text"><span>FARINERA</span><span>COROMINA</span></div>`;
    const nClient = (c.n_client_txt || "").trim();
    const articles = e.articles.map(a => `${a.art_codi} ${a.art_descrip}`).join(" · ");
    return `
    <article class="etq">
        <div class="etq-cap">
            <div class="etq-marca">${marca}</div>
            <div class="etq-desti">${escE(c.desti)}</div>
            <div class="etq-empresa">${EMPRESA.map(escE).join("<br>")}</div>
        </div>
        <div class="etq-label">CLIENT:</div>
        <div class="etq-caixa etq-client">
            <div class="etq-client-nom">${escE(c.cli_nom)}</div>
            <div class="etq-client-carrer">${escE(c.carrer)}</div>
        </div>
        <div class="etq-fila">
            ${nClient ? `<div class="etq-caixa etq-mig">Nº CLIENT: ${escE(nClient)}</div>` : ""}
            <div class="etq-caixa etq-mig etq-transport">${escE(est.transport[c.carrega_id] || "")}</div>
        </div>
        <div class="etq-caixa etq-sacs">Nº SACS: ${e.sacs}</div>
        <div class="etq-peu">Càrrega #${escE(c.carrega_num)} · Palet ${e.palet_n} de ${total} · ${escE(articles)}</div>
    </article>`;
}

// Torna a pintar la fila de palets d'un client.
function pintaPaletsDe(c) {
    const td = document.querySelector(`tr[data-palets-de="${CSS.escape(c.clau)}"] > td:last-child`);
    if (td) td.innerHTML = htmlPalets(c);
}

function pintaPrevia() {
    const html = [];
    let n = 0;
    for (const c of est.clients) {
        if (!c.inclou) continue;
        c.palets.forEach((p, i) => {
            html.push(htmlEtiqueta({ ...p, palet_n: i + 1 }, c, c.palets.length));
            n++;
        });
    }
    document.getElementById("etq-previa").innerHTML = html.join("");
    document.getElementById("etq-titol-previa").hidden = n === 0;
    document.getElementById("etq-resum").textContent =
        `${n} etiquetes · ${Math.ceil(n / 2)} fulls A4`;
    document.getElementById("etq-imprimir").disabled = n === 0;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { ajustaPalets, sumaSacs };
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", async () => {
    const err = document.getElementById("etq-error");
    try {
        const d = await carrega();
        est.etiquetes = d.etiquetes || [];
        est.clients = (d.clients || []).map(c => {
            // La proposta del motor: un palet per etiqueta calculada.
            const proposta = est.etiquetes
                .filter(e => e.clau === c.clau)
                .map(e => ({ sacs: e.sacs, articles: e.articles || [], tipus_palet: e.tipus_palet }));
            return {
                ...c,
                inclou: true,
                desti: (c.poblacio || "").toUpperCase(),
                n_client_txt: String(c.n_client ?? ""),
                proposta,
                palets: proposta.map(p => ({ ...p })),
                sacs_proposats: sumaSacs(proposta),
                editat: false,
            };
        }).filter(c => c.palets.length);
        for (const c of est.clients) {
            if (!(c.carrega_id in est.transport)) est.transport[c.carrega_id] = c.transportista || "";
        }
        if (d.incidencies && d.incidencies.length) {
            const box = document.getElementById("etq-incidencies");
            box.textContent = `${d.incidencies.length} comandes no s'han pogut calcular i no tenen etiqueta: `
                + d.incidencies.map(i => `${i.comanda} (${i.missatge})`).join("; ");
            box.hidden = false;
        }
        if (!est.etiquetes.length) throw new Error("Aquestes càrregues no tenen cap palet per etiquetar.");
        document.getElementById("etq-editor").hidden = false;
        pintaTaula();
        pintaPrevia();
    } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
    } finally {
        document.getElementById("etq-carregant").hidden = true;
    }

    const taula = document.getElementById("etq-taula");
    const clientDe = clau => est.clients.find(x => x.clau === clau);
    taula.addEventListener("input", ev => {
        const t = ev.target;
        if (t.dataset.sacs !== undefined) {
            const c = clientDe(t.dataset.sacs);
            const p = c && c.palets[Number(t.dataset.i)];
            if (!p) return;
            p.sacs = Math.max(0, Math.trunc(Number(t.value)) || 0);
            marcaEditat(c);
            // Només el total i el botó: no es repinta l'input on s'escriu.
            const fila = t.closest(".etq-palets");
            fila.querySelector(".etq-total-sacs").innerHTML = htmlTotalSacs(c);
            fila.querySelector(".etq-restaura").hidden = !c.editat;
            pintaPrevia();
            return;
        }
        if (t.dataset.npalets !== undefined) {
            const c = clientDe(t.dataset.npalets);
            if (!c || t.value === "") return;   // s'està esborrant per escriure'n un altre
            c.palets = ajustaPalets(c.palets, t.value);
            marcaEditat(c);
            pintaPaletsDe(c);
            pintaPrevia();
            return;
        }
        const c = clientDe(t.dataset.desti || t.dataset.nclient || t.dataset.inclou);
        if (t.dataset.transport !== undefined) est.transport[t.dataset.transport] = t.value;
        else if (c && t.dataset.desti !== undefined) c.desti = t.value;
        else if (c && t.dataset.nclient !== undefined) c.n_client_txt = t.value;
        pintaPrevia();
    });
    taula.addEventListener("change", ev => {
        const t = ev.target;
        // En sortir d'un camp numèric, s'hi posa el valor que compta (buit -> 1, -3 -> 0...).
        if (t.dataset.npalets !== undefined) {
            const c = clientDe(t.dataset.npalets);
            if (c) t.value = c.palets.length;
            return;
        }
        if (t.dataset.sacs !== undefined) {
            const c = clientDe(t.dataset.sacs);
            const p = c && c.palets[Number(t.dataset.i)];
            if (p) t.value = p.sacs;
            return;
        }
        if (t.dataset.inclou === undefined) return;
        const c = clientDe(t.dataset.inclou);
        if (c) c.inclou = t.checked;
        const tr = t.closest("tr");
        tr?.classList.toggle("is-fora", !t.checked);
        tr?.nextElementSibling?.classList.toggle("is-fora", !t.checked);
        pintaPrevia();
    });
    taula.addEventListener("click", ev => {
        const b = ev.target.closest("[data-restaura]");
        const c = b && clientDe(b.dataset.restaura);
        if (!c) return;
        c.palets = c.proposta.map(p => ({ ...p }));
        c.editat = false;
        const inp = taula.querySelector(`input[data-npalets="${CSS.escape(c.clau)}"]`);
        if (inp) inp.value = c.palets.length;
        pintaPaletsDe(c);
        pintaPrevia();
    });
    document.getElementById("etq-imprimir").addEventListener("click", () => window.print());
});
