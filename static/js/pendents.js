// Pantalla "Pendents de pistolejar" (tablet de magatzem). Només lectura:
// llegeix /api/pistolejat/pendents i refresca cada 15 s amb la pestanya visible.
"use strict";

const POLL_MS = 15_000;
const RANG_KEY = "pend-rang";
const TOTS_KEY = "pend-tots";

const pendState = { rang: "avui", tots: false, timer: null, carregant: false };

const fmtKg = new Intl.NumberFormat("ca-ES", { maximumFractionDigits: 0 });
const fmtSacs = new Intl.NumberFormat("ca-ES", { maximumFractionDigits: 1 });

const ETIQUETA_ESTAT = { pendent: "Pendent", parcial: "A mitges", complet: "Fet" };

function escP(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
}

function llegeix(clau, perDefecte) {
    try { return localStorage.getItem(clau) ?? perDefecte; } catch { return perDefecte; }
}
function desa(clau, valor) {
    try { localStorage.setItem(clau, valor); } catch { /* navegador sense storage */ }
}

function isoLocal(d) {
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${mm}-${dd}`;
}

function rangDates(rang) {
    const avui = new Date();
    const mes = n => { const d = new Date(avui); d.setDate(d.getDate() + n); return d; };
    switch (rang) {
        case "dema": return [mes(1), mes(1)];
        case "avui-dema": return [avui, mes(1)];
        case "setmana": return [avui, mes(6)];
        default: return [avui, avui];
    }
}

// Quantitat principal d'una línia: sacs (o unitats) si en té, si no kg.
function quantitat(l, camp) {
    const sacs = l[`sacs_${camp}`];
    if (sacs != null) {
        const u = l.unitat && l.unitat !== "UNI" ? "sacs" : "u.";
        return `${fmtSacs.format(sacs)} ${u}`;
    }
    return `${fmtKg.format(l[`kg_${camp}`])} kg`;
}

function pintaLinia(l) {
    const fet = l.kg_oberts > 0 ? Math.min(100, Math.round(100 * l.kg_pistolejats / l.kg_oberts)) : 100;
    // Els kg només diuen alguna cosa als sacs; en unitats (palets) són soroll.
    const kgDetall = l.sacs_pendents != null && l.unitat !== "UNI" ?`<span class="pend-kg">${fmtKg.format(l.kg_pendents)} kg</span>` : "";
    return `
        <li class="pend-linia is-${l.estat}">
            <div class="pend-art">
                <div class="pend-art-descrip">${escP(l.art_descrip)}</div>
                <div class="pend-art-codi">${escP(l.art_codi)}</div>
            </div>
            <div class="pend-qtat">
                <div class="pend-qtat-big">${l.estat === "complet" ? "✓" : escP(quantitat(l, "pendents"))}</div>
                <div class="pend-qtat-lbl">
                    ${l.estat === "complet" ? "" : `falten de ${escP(quantitat(l, "oberts"))}`} ${kgDetall}
                </div>
                <div class="pend-barra"><div class="pend-barra-fill" style="width:${fet}%"></div></div>
            </div>
            <span class="pend-estat pend-estat-${l.estat}">${ETIQUETA_ESTAT[l.estat] || escP(l.estat)}</span>
        </li>`;
}

function pintaComanda(cm) {
    const estat = cm.estat_comanda
        ? `<span class="pend-badge-comanda">${escP(cm.estat_comanda.toLowerCase())}</span>` : "";
    return `
        <div class="pend-comanda">
            <div class="pend-comanda-cap">
                <span class="pend-client">${escP(cm.cli_nom || cm.cli_codi)}</span>
                <span class="pend-comanda-num">Comanda ${escP(cm.docnum)}</span>
                ${estat}
            </div>
            <ul class="pend-linies">${cm.linies.map(pintaLinia).join("")}</ul>
        </div>`;
}

function pintaCarrega(c) {
    const quan = [c.data_sortida ? fmtData(c.data_sortida) : "", c.hora_sortida || ""]
        .filter(Boolean).join(" ");
    const meta = [c.transportista, c.matricula].filter(Boolean).map(escP).join(" · ");
    const t = c.totals;
    return `
        <section class="pend-carrega ${t.n_pendents === 0 ? "is-acabada" : ""}">
            <header class="pend-carrega-cap">
                <div>
                    <div class="pend-carrega-nom">${escP(c.nom || `Càrrega ${c.docentry}`)} <span class="pend-carrega-num">#${c.docentry}</span></div>
                    <div class="pend-carrega-meta">🕒 ${escP(quan || "sense hora")}${meta ? ` · ${meta}` : ""}</div>
                </div>
                <div class="pend-carrega-progres">
                    <div class="pend-carrega-pct">${t.percent}%</div>
                    <div class="pend-carrega-falten">${t.n_pendents} de ${t.n_linies} línies per fer</div>
                </div>
            </header>
            ${c.comandes.map(pintaComanda).join("")}
        </section>`;
}

function pintaResum(totals) {
    const text = document.getElementById("pend-resum-text");
    const fill = document.getElementById("pend-resum-fill");
    const box = document.getElementById("pend-resum-box");
    text.textContent = totals.n_linies ? `${totals.n_pendents} línies · ${totals.percent}%` : "—";
    fill.style.width = `${totals.percent}%`;
    box.classList.toggle("is-acabada", totals.n_linies > 0 && totals.n_pendents === 0);
}

async function refrescar() {
    if (pendState.carregant) return;
    pendState.carregant = true;
    const [d, f] = rangDates(pendState.rang);
    const qs = new URLSearchParams({ desde: isoLocal(d), fins: isoLocal(f) });
    if (pendState.tots) qs.set("tots", "1");
    const errBox = document.getElementById("pend-error");
    try {
        const r = await fetch(`/api/pistolejat/pendents?${qs}`, { credentials: "same-origin" });
        if (r.status === 401) { window.location.href = "/login"; return; }
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || `Error ${r.status}`);
        document.getElementById("pend-llista").innerHTML = j.carregues.map(pintaCarrega).join("");
        document.getElementById("pend-buit").hidden = j.carregues.length > 0;
        pintaResum(j.totals);
        errBox.hidden = true;
        document.getElementById("pend-actualitzat").textContent =
            `Actualitzat a les ${new Date().toLocaleTimeString("ca-ES", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (e) {
        // Es manté l'última llista bona a la pantalla: és millor que buidar-la.
        errBox.textContent = `No s'han pogut carregar les dades de SAP (${e.message}). Es tornarà a provar.`;
        errBox.hidden = false;
    } finally {
        pendState.carregant = false;
    }
}

function programa() {
    clearTimeout(pendState.timer);
    if (document.hidden) return;
    pendState.timer = setTimeout(async () => { await refrescar(); programa(); }, POLL_MS);
}

function marcaRang() {
    document.querySelectorAll(".pend-rang").forEach(b => {
        const on = b.dataset.rang === pendState.rang;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
    });
}

document.addEventListener("DOMContentLoaded", () => {
    pendState.rang = llegeix(RANG_KEY, "avui");
    pendState.tots = llegeix(TOTS_KEY, "0") === "1";
    marcaRang();
    const tots = document.getElementById("pend-tots");
    tots.checked = pendState.tots;

    document.querySelectorAll(".pend-rang").forEach(b => b.addEventListener("click", () => {
        pendState.rang = b.dataset.rang;
        desa(RANG_KEY, pendState.rang);
        marcaRang();
        refrescar().then(programa);
    }));
    tots.addEventListener("change", () => {
        pendState.tots = tots.checked;
        desa(TOTS_KEY, pendState.tots ? "1" : "0");
        refrescar().then(programa);
    });
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) clearTimeout(pendState.timer);
        else refrescar().then(programa);
    });

    refrescar().then(programa);
});
