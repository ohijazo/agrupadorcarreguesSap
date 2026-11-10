// Mode magatzem — UI tàctil per al preparador.

const $m = (sel, r = document) => r.querySelector(sel);
const $mAll = (sel, r = document) => Array.from(r.querySelectorAll(sel));
const fmtN = new Intl.NumberFormat("ca-ES");
// Kg sense decimals, com a la pàgina principal: ningú al magatzem necessita els cèntims.
const fmtKgN = new Intl.NumberFormat("ca-ES", { maximumFractionDigits: 0 });

// Mateixa paleta que l'app principal perquè els colors coincideixin
// Mateixa paleta i ordre que PALETA (app.js): vermell, taronja i verd al
// final perquè no es confonguin amb els colors d'estat.
const PALETA_MAG = [
    { color: "#1f77b4", bg: "#e8f0f7" }, { color: "#9467bd", bg: "#f1ebf7" },
    { color: "#17becf", bg: "#e0f5f7" }, { color: "#e377c2", bg: "#fbe6f3" },
    { color: "#8c564b", bg: "#efe1de" }, { color: "#000000", bg: "#eeeeee" },
    { color: "#4b0082", bg: "#ece0f0" }, { color: "#bcbd22", bg: "#f6f6d8" },
    { color: "#7f7f7f", bg: "#f0f0f0" }, { color: "#ff1493", bg: "#ffe2ee" },
    { color: "#a52a2a", bg: "#f4dada" }, { color: "#daa520", bg: "#fbf0d4" },
    { color: "#ff7f0e", bg: "#fff0db" }, { color: "#2ca02c", bg: "#e8f5e6" },
    { color: "#d62728", bg: "#fce6e6" }, { color: "#00875a", bg: "#d8f0e6" },
];

function escapeM(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;",
    }[c]));
}

// El mateix llenguatge a totes les pantalles: primer la PRODUCCIÓ (productes
// marcats com a produïts) i després l'EXPEDICIÓ (% de kg pistolejats a l'SGA,
// informatiu). `pct` és null si encara no s'ha llegit mai el pistolejat.
function textProgres(pct, fets, total) {
    const prod = `${fets} de ${total} produïts`;
    return pct == null ? prod : `${prod} · ${pct}% pistolejat`;
}

function fmtHoraCurta(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleTimeString("ca-ES", { hour: "2-digit", minute: "2-digit" });
}

function toast(type, msg) {
    const wrap = $m("#toasts");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span class="toast-icon">${type === "error" ? "✕" : "✓"}</span>
                    <div class="toast-body">${escapeM(msg)}</div>
                    <button class="toast-close" aria-label="Tanca">×</button>`;
    wrap.appendChild(el);
    el.querySelector(".toast-close").addEventListener("click", () => el.remove());
    setTimeout(() => el.remove(), 3500);
}

function getCsrfTok() {
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
}

async function fetchJ(url, opts = {}) {
    const method = (opts.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
        const tok = getCsrfTok();
        if (tok) {
            const headers = new Headers(opts.headers || {});
            if (!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", tok);
            opts = { ...opts, headers };
        }
    }
    const r = await fetch(url, opts);
    if (!r.ok) {
        let err = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j.error) err = j.error; } catch {}
        throw new Error(err);
    }
    return r.json();
}

// ---- Vista LLISTA: "Agrupacions" ---------------------------------------
// Una sola pantalla per a les agrupacions desades (abans n'hi havia tres:
// la finestra "Desades", aquesta llista i "Control d'agrupacions"). Cada
// targeta porta a la preparació i, per a admin i oficina, permet reimprimir,
// finalitzar/reobrir i eliminar. Dades: /api/agrupacions (llistar_control).
const LLISTA_POLL_MS = 30_000;
const FILTRE_KEY = "mag-filtre-estat";

const ESTAT_LLISTA = {
    pendent: { txt: "Pendent", cls: "ctrl-badge-pendent" },
    en_curs: { txt: "En curs", cls: "ctrl-badge-en-curs" },
    acabada: { txt: "Acabada", cls: "ctrl-badge-acabada" },
    tancada: { txt: "Tancada", cls: "ctrl-badge-tancada" },
};

const llistaState = { items: [], timer: null };

function fmtDuradaM(s) {
    if (s == null) return "";
    if (s < 60) return "<1 min";
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), mr = m % 60;
    return mr ? `${h}h ${mr}min` : `${h}h`;
}

function esOficina() {
    return document.body.dataset.oficina === "1";
}

function avuiISO() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function filtraLlista(items) {
    const estat = $m("#mag-filtre-estat").value;
    const avui = $m("#mag-nomes-avui").checked ? avuiISO() : null;
    return items.filter(it => {
        if (avui && !(it.ts || "").startsWith(avui)) return false;
        if (estat === "actives") return it.estat === "pendent" || it.estat === "en_curs";
        if (estat === "plantilla") return !!it.plantilla;
        return !estat || it.estat === estat;
    });
}

// Línia de temps: quan va començar i acabar el pistolejat (o qui la va tancar).
function textTemps(it) {
    if (it.estat === "tancada") {
        const qui = it.finalitzada_manual_per_nom ? ` per ${it.finalitzada_manual_per_nom}` : "";
        return `Tancada${qui} · ${fmtHoraCurta(it.finalitzada_manual_at)}`;
    }
    if (!it.prep_iniciat) return "";
    const fi = it.prep_finalitzat ? ` → ${fmtHoraCurta(it.prep_finalitzat)} (${fmtDuradaM(it.durada_s)})` : "";
    return `Pistolejat des de les ${fmtHoraCurta(it.prep_iniciat)}${fi} · ${it.prep_per_nom || "SGA"}`;
}

function accionsLlista(it) {
    const id = encodeURIComponent(it.id);
    let html = `<a class="btn btn-primary mag-agr-prep" href="/magatzem/${id}">Preparació</a>`
        + `<a class="btn btn-ghost" href="/etiquetes?agrupacio=${id}" target="_blank" rel="noopener">🏷 Etiquetes</a>`;
    if (!esOficina()) return html;
    html += `<a class="btn btn-ghost" href="/?agrupacio=${id}" title="Obre el resultat a Agrupar càrregues per tornar-lo a imprimir">Reimprimir</a>`;
    if (it.estat === "tancada") {
        html += `<button type="button" class="btn btn-ghost" data-act="reobrir" data-id="${escapeM(it.id)}">Reobrir</button>`;
    } else if (it.estat !== "acabada") {
        html += `<button type="button" class="btn btn-ghost" data-act="finalitzar" data-id="${escapeM(it.id)}" title="Tanca-la encara que no estigui tot pistolejat">Finalitza</button>`;
    }
    html += `<button type="button" class="btn btn-ghost mag-agr-elimina" data-act="eliminar" data-id="${escapeM(it.id)}">Elimina</button>`;
    return html;
}

function _pintaLlistaItems(items) {
    const ul = $m("#mag-llista");
    ul.innerHTML = items.map(it => {
        const e = ESTAT_LLISTA[it.estat] || { txt: it.estat, cls: "" };
        const badges = `<span class="ctrl-badge ${e.cls}">${escapeM(e.txt)}</span>`
            + (it.plantilla ? ` <span class="ctrl-badge ctrl-badge-origen-desada" title="Plantilla recurrent">Plantilla</span>` : "")
            + (it.origen === "impresa" ? ` <span class="ctrl-badge ctrl-badge-origen-impresa" title="Desada en imprimir-la">Impresa</span>` : "");
        const creador = it.created_by_nom ? ` · ${escapeM(it.created_by_nom)}` : "";
        const temps = textTemps(it);
        const fin = it.estat === "acabada" || it.estat === "tancada";
        return `
            <li class="mag-agr${fin ? " is-acabada" : ""}">
                <div class="mag-agr-cap">
                    <a class="nom" href="/magatzem/${encodeURIComponent(it.id)}">${escapeM(it.nom)}</a>
                    <span class="mag-agr-badges">${badges}</span>
                </div>
                <div class="meta">${escapeM(fmtData(it.ts))}${creador} · ${it.n_carregues} càrregues · ${fmtN.format(it.total_palets_fisics || 0)} palets</div>
                <div class="meta progres">${escapeM(textProgres(it.pct_pistolejat, it.n_preparats || 0, it.n_productes || 0))}</div>
                ${temps ? `<div class="meta temps">${escapeM(temps)}</div>` : ""}
                <div class="mag-agr-accions">${accionsLlista(it)}</div>
            </li>`;
    }).join("");
}

function pintaLlista() {
    const items = llistaState.items;
    const llista = filtraLlista(items);
    $m("#mag-buit").hidden = items.length > 0;
    $m("#mag-llista-bar").hidden = items.length === 0;
    $m("#mag-filtre-buit").hidden = !(items.length > 0 && llista.length === 0);
    $m("#mag-llista-count").textContent = items.length ? `${llista.length} de ${items.length}` : "";
    _pintaLlistaItems(llista);
}

async function carregaLlista({ silenciós = false } = {}) {
    try {
        llistaState.items = await fetchJ("/api/agrupacions");
        pintaLlista();
    } catch (e) {
        if (!silenciós) toast("error", "No s'ha pogut carregar el llistat: " + e.message);
    }
}

async function accioLlista(act, id) {
    const enc = encodeURIComponent(id);
    try {
        if (act === "eliminar") {
            const ok = await window.mostrarConfirmacio({
                titol: "Eliminar agrupació",
                missatge: "L'agrupació quedarà eliminada definitivament i les seves càrregues tornaran a estar disponibles per agrupar.",
                btnOk: "Sí, elimina-la",
                btnCancel: "No",
                tipus: "danger",
            });
            if (!ok) return;
            await fetchJ(`/api/agrupacions/${enc}`, { method: "DELETE" });
            toast("success", "Agrupació eliminada");
        } else if (act === "finalitzar" || act === "reobrir") {
            await fetchJ(`/api/agrupacions/${enc}/${act}`, { method: "POST" });
            toast("success", act === "finalitzar" ? "Agrupació tancada" : "Agrupació reoberta");
        }
    } catch (e) {
        toast("error", e.message);
    }
    carregaLlista();
}

window.magatzemLlista = async function magatzemLlista() {
    const sel = $m("#mag-filtre-estat");
    try { sel.value = localStorage.getItem(FILTRE_KEY) ?? "actives"; } catch { /* sense storage */ }
    if (sel.selectedIndex < 0) sel.value = "actives";   // valor desat que ja no existeix
    sel.addEventListener("change", () => {
        try { localStorage.setItem(FILTRE_KEY, sel.value); } catch { /* sense storage */ }
        pintaLlista();
    });
    $m("#mag-nomes-avui").addEventListener("change", pintaLlista);
    $m("#mag-llista").addEventListener("click", ev => {
        const btn = ev.target.closest("button[data-act]");
        if (btn && !btn.disabled) accioLlista(btn.dataset.act, btn.dataset.id);
    });

    await carregaLlista();
    // El pistolejat avança sol: refresquem amb la pestanya visible.
    const programa = () => {
        clearTimeout(llistaState.timer);
        if (document.hidden) return;
        llistaState.timer = setTimeout(async () => { await carregaLlista({ silenciós: true }); programa(); }, LLISTA_POLL_MS);
    };
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) clearTimeout(llistaState.timer);
        else carregaLlista({ silenciós: true }).then(programa);
    });
    programa();
};

// ---- Vista PREPARACIÓ --------------------------------------------------
// Agrupar és per PRODUIR i pistolejar és per EXPEDIR. L'operari marca cada
// producte com a "Produït" (botó gros, /producte). El pistolejat de l'SGA
// (/api/agrupacions/<id>/pistolejat) es mostra a part, com a informació
// d'expedició. Vegeu preparacio_sga.py.
let magState = {
    id: null,
    obj: null,
    preparats: new Set(),    // productes marcats com a produïts
    progres: null,           // resposta de /pistolejat (null fins a la primera)
    ocultarPrep: false,
    colorsCarrega: new Map(),
    pollTimer: null,
    lastInteractionTs: 0,    // últim toc: el polling no repinta enmig
    lastAcabada: null,       // si estava tot produït al darrer render (null = abans del primer)
};

const INTERACCIO_MS = 1200;

// Cada refresc va a SAP: cada 15 s n'hi ha prou (com a "Pendents del dia").
const POLL_PREP_MS = 15_000;

// Estat d'EXPEDICIÓ (pistolejat), no de producció.
const ETIQUETA_ESTAT_PREP = {
    pendent: "No pistolejat", parcial: "Pistolejant", complet: "Pistolejat", sense_dades: "Sense dades a SAP",
};

function colorPerCarregaIdx(i) {
    return PALETA_MAG[i % PALETA_MAG.length];
}

function progresDe(artCodi) {
    return magState.progres?.productes?.[artCodi] || null;
}

function esProduit(artCodi) {
    return magState.preparats.has(artCodi);
}

// Lectures de l'SGA d'un albarà que després es va cancel·lar: no compten
// (l'SGA demana tornar a pistolejar), però la mercaderia pot ser al palet.
function avisCancelat(c) {
    if (!c || !c.kg) return "";
    const albs = (c.albarans || []).join(", ");
    return `<div class="avis-cancelat" role="note">⚠ ${fmtKgN.format(c.kg)} kg ja pistolejats per a l'albarà ${escapeM(albs)}, cancel·lat. Poden ser al palet: torna'ls a pistolejar a l'SGA.</div>`;
}

// "10 de 40 sacs" o, si la línia no té sacs (granel), en kg.
function textPistolejat(pr) {
    if (!pr || pr.estat === "sense_dades") return "";
    if (pr.sacs_total != null) {
        return `${fmtN.format(Math.round(pr.sacs_fets))} de ${fmtN.format(Math.round(pr.sacs_total))} sacs`;
    }
    return `${fmtKgN.format(pr.kg_fets)} de ${fmtKgN.format(pr.kg_total)} kg`;
}

function calculaProgres() {
    const prods = magState.obj?.resultat?.productes || [];
    const total = prods.length;
    const fets = prods.filter(p => esProduit(p.art_codi)).length;
    // En gran, la producció (el que marca l'operari) i la seva barra; a sota,
    // l'expedició (% pistolejat a l'SGA), que és informativa.
    $m("#mag-progres-pct").textContent = `${fets} de ${total}`;
    $m("#mag-progres-sub").textContent = "produïts"
        + (magState.progres ? ` · ${magState.progres.percent}% pistolejat` : "");
    const fill = $m("#mag-progres-fill");
    if (fill) fill.style.width = `${total ? Math.round(100 * fets / total) : 0}%`;
    const btnDesfes = $m("#mag-desfes");
    if (btnDesfes) btnDesfes.hidden = fets === 0;
    const resum = magState.obj?.resultat;
    if (resum) {
        $m("#mag-resum").textContent =
            `${resum.carregues?.length || 0} càrregues · ${fmtN.format(resum.total_sacs || 0)} sacs · ${fmtN.format(resum.total_palets_fisics || 0)} palets`;
    }
    const creadorEl = $m("#mag-creador-nom");
    if (creadorEl) {
        // Sense nom (agrupacions d'abans de l'auth) no diem "Creada per —".
        creadorEl.textContent = magState.obj?.created_by_nom || "";
        const p = creadorEl.closest(".mag-creador");
        if (p) p.hidden = !magState.obj?.created_by_nom;
    }

    // Feedback en arribar a tot fet (toast + vibració). Només a la transició,
    // no a cada render ni si ja estava acabada en obrir la pantalla.
    const acabada = total > 0 && fets >= total;
    const prev = magState.lastAcabada;
    magState.lastAcabada = acabada;
    const wrap = $m(".mag-progres-box");
    if (wrap) wrap.classList.toggle("is-acabada", acabada);
    if (acabada && prev === false) {
        toast("success", `Agrupació produïda — ${total} productes`);
        if (navigator.vibrate) {
            try { navigator.vibrate([200, 80, 200]); } catch {}
        }
    }
}

function renderArticles() {
    const ul = $m("#mag-articles");
    const buit = $m("#mag-buit");
    ul.innerHTML = "";
    const prods = (magState.obj?.resultat?.productes || []).slice();
    if (!prods.length) {
        buit.hidden = false;
        return;
    }
    buit.hidden = true;
    // Ordre: per produir primer (ordenats per total_sacs desc), produïts al final
    prods.sort((a, b) => {
        const pa = esProduit(a.art_codi) ? 1 : 0;
        const pb = esProduit(b.art_codi) ? 1 : 0;
        if (pa !== pb) return pa - pb;
        return (b.total_sacs || 0) - (a.total_sacs || 0);
    });

    // Calcula ordre de càrregues per indexar colors igual que a l'app principal
    const ordreCar = new Map();
    (magState.obj.resultat.carregues || []).forEach((c, i) => {
        ordreCar.set(c.carrega_id, i);
        magState.colorsCarrega.set(c.carrega_id, colorPerCarregaIdx(i));
    });

    for (const p of prods) {
        const pr = progresDe(p.art_codi);
        const isFet = esProduit(p.art_codi);
        if (magState.ocultarPrep && isFet) continue;

        const pcOrdenats = (p.per_carrega || []).slice()
            .sort((a, b) => (ordreCar.get(a.carrega_id) ?? 999) - (ordreCar.get(b.carrega_id) ?? 999));
        const carregesHtml = pcOrdenats.map(pc => {
            const col = magState.colorsCarrega.get(pc.carrega_id) || { color: "#718096", bg: "#f7fafc" };
            // Format "[N×M] TIPUS" amb abreviació del tipus de palet (BASE, EU, PL...)
            const peces = detallPaletsCarrega(pc);
            const carrega = (magState.obj.resultat.carregues || []).find(c => c.carrega_id === pc.carrega_id);
            const nomCar = carrega?.descripcio || pc.carrega_id;
            // Número curt: últim segment del carrega_id sense zeros inicials
            const numFinal = String(pc.carrega_id).split("/").pop() || "";
            const numCurt = numFinal.replace(/^0+/, "") || numFinal;
            const prc = pr?.per_carrega?.[pc.carrega_id];
            const estatCar = prc
                ? `<span class="mag-carrega-estat is-${escapeM(prc.estat)}" title="${escapeM(ETIQUETA_ESTAT_PREP[prc.estat] || prc.estat)}">${prc.estat === "complet" ? "✓" : escapeM(textPistolejat(prc) || "—")}</span>`
                : "";
            return `<span class="mag-carrega-row" style="--cb-color:${col.color};--cb-bg:${col.bg}">
                        <span class="dot" aria-hidden="true"></span>
                        <span class="nom">${escapeM(nomCar)}</span>
                        <span class="num">#${escapeM(numCurt)}</span>
                        <span class="detall">${escapeM(peces)} · ${fmtN.format(pc.total_sacs)} sacs</span>
                        ${estatCar}
                    </span>`;
        }).join("");

        let pistHtml = "";
        if (pr && pr.estat !== "sense_dades") {
            pistHtml = `<div class="mag-pist">
                    <span class="mag-pist-text">Expedició: pistolejat ${escapeM(textPistolejat(pr))}</span>
                    <div class="pend-barra"><div class="pend-barra-fill" style="width:${pr.percent}%"></div></div>
                </div>`;
        }
        let prepMetaHtml = "";
        if (isFet) {
            const d = (magState.obj?.preparats_detall || {})[p.art_codi] || {};
            // "SGA": ho va marcar la sincronització del pistolejat del 9-11-2026.
            const txt = [d.per_nom || (d.sga ? "SGA" : ""), fmtHoraCurta(d.ts)].filter(Boolean).join(" · ");
            prepMetaHtml = `<div class="mag-prep-meta">✓ Produït${txt ? " · " + escapeM(txt) : ""}</div>`;
        }
        const estat = pr
            ? `<span class="pend-estat pend-estat-${escapeM(pr.estat)}">${escapeM(ETIQUETA_ESTAT_PREP[pr.estat] || pr.estat)}</span>`
            : "";

        const li = document.createElement("li");
        li.className = "mag-card" + (isFet ? " is-preparat" : "");
        li.dataset.artCodi = p.art_codi;
        li.innerHTML = `
            <div class="mag-art">
                <div class="mag-art-top">
                    <span class="mag-art-descrip">${escapeM(p.art_descrip)}</span>
                    <span class="mag-art-codi">${escapeM(p.art_codi)}</span>
                    <span class="mag-art-sacs-big">${fmtN.format(p.total_sacs)} <span class="mag-art-sacs-lbl">sacs</span><span class="mag-art-sacs-kg">${fmtKgN.format(p.total_kg)} kg</span></span>
                </div>
                <div class="mag-art-totals-sec">${fmtKgN.format(p.total_kg)} kg</div>
                <div class="mag-art-carregues">${carregesHtml}</div>
                ${pistHtml}
                ${avisCancelat(pr?.cancelat)}
                ${prepMetaHtml}
            </div>
            <div class="mag-estat-col">
                <button type="button" class="mag-prep-check ${isFet ? "is-on" : ""}" data-act="toggle"
                        aria-pressed="${isFet ? "true" : "false"}"
                        aria-label="${isFet ? "Desmarca com a produït" : "Marca com a produït"}">${isFet ? "✓" : ""}</button>
                <span class="mag-prep-lbl">${isFet ? "Produït" : "Produir"}</span>
                ${estat}
            </div>
        `;
        ul.appendChild(li);
    }
    calculaProgres();
}

async function refrescar({ fromPolling = false } = {}) {
    const id = encodeURIComponent(magState.id);
    const errBox = $m("#mag-pist-error");
    try {
        // L'agrupació (producció) i el pistolejat (expedició) en paral·lel.
        const [obj, progres] = await Promise.all([
            fetchJ(`/api/agrupacions/${id}`),
            fetchJ(`/api/agrupacions/${id}/pistolejat`).catch(e => ({ _error: e })),
        ]);
        magState.obj = obj;
        // Si l'operari acaba de tocar un botó, no trepitgem la seva marca amb
        // dades que potser van sortir del servidor abans del toc.
        if (!fromPolling || Date.now() - magState.lastInteractionTs > INTERACCIO_MS) {
            magState.preparats = new Set(obj.productes_preparats || []);
        }
        if (progres._error) {
            // Es manté l'últim pistolejat bo a la pantalla: és millor que buidar-la.
            if (errBox) {
                errBox.textContent = `No s'ha pogut llegir el pistolejat de SAP (${progres._error.message}). Es tornarà a provar.`;
                errBox.hidden = false;
            }
        } else {
            magState.progres = progres;
            if (errBox) errBox.hidden = true;
            const act = $m("#mag-actualitzat");
            if (act) act.textContent = `Actualitzat a les ${new Date().toLocaleTimeString("ca-ES", { hour: "2-digit", minute: "2-digit" })}`;
        }
        renderArticles();
    } catch (e) {
        // Errors del polling silenciosos (no embrutim la UI cada 15 s)
        if (!fromPolling) toast("error", "No s'ha pogut refrescar: " + e.message);
    }
}

async function togglePreparat(artCodi, nouEstat) {
    magState.lastInteractionTs = Date.now();
    // Feedback tàctil immediat (vibració a tablet/mòbil).
    if (navigator.vibrate) {
        try { navigator.vibrate(nouEstat ? 60 : [30, 40, 30]); } catch {}
    }
    // Optimista: actualitza la pantalla de seguida i desfà si falla.
    if (nouEstat) magState.preparats.add(artCodi);
    else magState.preparats.delete(artCodi);
    renderArticles();
    try {
        await fetchJ(`/api/agrupacions/${encodeURIComponent(magState.id)}/producte`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ art_codi: artCodi, preparat: nouEstat }),
        });
        magState.lastInteractionTs = Date.now();
    } catch (e) {
        if (nouEstat) magState.preparats.delete(artCodi);
        else magState.preparats.add(artCodi);
        renderArticles();
        toast("error", "No s'ha guardat: " + e.message);
    }
}

async function desferPreparats() {
    const n = magState.preparats.size;
    if (!n) return;
    const ok = await window.mostrarConfirmacio({
        titol: "Desfer produïts",
        missatge: `Es desmarcaran ${n} producte${n > 1 ? "s" : ""} com a produït${n > 1 ? "s" : ""}. Vols continuar?`,
        btnOk: "Sí, desfés-los",
        btnCancel: "No",
        tipus: "danger",
    });
    if (!ok) return;
    try {
        await fetchJ(`/api/agrupacions/${encodeURIComponent(magState.id)}/reset-preparats`, { method: "POST" });
        magState.preparats.clear();
        magState.lastInteractionTs = Date.now();
        renderArticles();
        toast("success", `Desmarcats ${n} productes`);
    } catch (e) {
        toast("error", "No s'ha pogut desfer: " + e.message);
    }
}

window.magatzemPrep = async function magatzemPrep(id) {
    magState.id = id;
    await refrescar();

    // Botó gros de cada targeta: marca o desmarca "Produït".
    $m("#mag-articles").addEventListener("click", (ev) => {
        const btn = ev.target.closest('[data-act="toggle"]');
        const card = btn?.closest(".mag-card");
        if (!card) return;
        togglePreparat(card.dataset.artCodi, !esProduit(card.dataset.artCodi));
    });
    $m("#mag-desfes")?.addEventListener("click", desferPreparats);

    // Toggle "amaga els produïts"
    $m("#mag-ocultar-prep").addEventListener("change", (ev) => {
        magState.ocultarPrep = ev.target.checked;
        renderArticles();
    });

    // Botó refresca manual
    $m("#mag-refresca").addEventListener("click", () => refrescar());

    // Botó imprimir: omple capçalera print-only i obre window.print()
    const btnImp = $m("#mag-imprimir");
    if (btnImp) {
        btnImp.addEventListener("click", () => {
            const r = magState.obj?.resultat;
            const hdr = $m("#mag-print-header");
            const ara = new Date();
            const nom = magState.obj?.nom || "Agrupació";
            const totalP = r?.total_palets_fisics || 0;
            const totalS = r?.total_sacs || 0;
            const carrs = (r?.carregues || [])
                .map(c => (c.descripcio || c.carrega_id).trim())
                .filter(Boolean).join(" · ");
            hdr.innerHTML = `
                <div class="mag-print-title">${escapeM(nom)}</div>
                <div class="mag-print-meta">
                    ${carrs ? escapeM(carrs) + " · " : ""}
                    ${fmtN.format(r?.carregues?.length || 0)} càrregues · ${fmtN.format(totalS)} sacs · ${fmtN.format(totalP)} palets
                    · Imprès ${fmtData(ara)}
                </div>`;

            // Footer: resum palets per tipus + pes total per càrrega
            const foot = $m("#mag-print-footer");
            if (foot && r) {
                // 1) Palets per tipus — al footer mostrem el descrip complet
                // (sense abreviar) perquè el reglament és més llegible en paper
                const tipusHtml = (r.tipus_palets || []).map(t => {
                    const nom = t.tipus_palet_descrip || t.tipus_palet || "";
                    return `<span>${fmtN.format(t.quantitat)} ${escapeM(nom)}</span>`;
                }).join(" · ");

                // 2) Pes per càrrega: agregació sobre productes[].per_carrega[]
                const pesPerCar = new Map();  // carrega_id → total_kg
                for (const p of (r.productes || [])) {
                    for (const pc of (p.per_carrega || [])) {
                        pesPerCar.set(pc.carrega_id, (pesPerCar.get(pc.carrega_id) || 0) + (pc.total_kg || 0));
                    }
                }
                // Mantenim l'ordre de r.carregues per coherència amb els colors
                const pesHtml = (r.carregues || []).map((c, i) => {
                    const col = (typeof colorPerCarregaIdx === "function")
                        ? colorPerCarregaIdx(i) : { color: "#000" };
                    const pes = pesPerCar.get(c.carrega_id) || 0;
                    const nomCar = (c.descripcio || c.carrega_id).trim() || c.carrega_id;
                    const numFinal = String(c.carrega_id).split("/").pop() || "";
                    const numCurt = numFinal.replace(/^0+/, "") || numFinal;
                    return `<span class="mag-pf-c" style="--cb-color:${col.color}">${escapeM(nomCar)} #${escapeM(numCurt)} · ${fmtKgN.format(pes)} kg</span>`;
                }).join(" · ");

                foot.innerHTML = `
                    ${tipusHtml ? `<div class="mag-pf-row mag-pf-palets"><strong>Total palets:</strong> ${tipusHtml}</div>` : ""}
                    ${pesHtml ? `<div class="mag-pf-row mag-pf-pes"><strong>Pes per càrrega:</strong> ${pesHtml}</div>` : ""}
                `;
            }

            window.print();
        });
    }

    // Polling cada 15 s, només amb la pestanya visible.
    function programaPoll() {
        clearTimeout(magState.pollTimer);
        if (document.hidden) return;
        magState.pollTimer = setTimeout(async () => {
            await refrescar({ fromPolling: true });
            programaPoll();
        }, POLL_PREP_MS);
    }
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) clearTimeout(magState.pollTimer);
        else refrescar({ fromPolling: true }).then(programaPoll);
    });
    programaPoll();
};

// Bootstrap automàtic: si el body té data-agrupacio-id és la pantalla de preparació;
// si no, és la llista. (CSP no permet scripts inline al template.)
document.addEventListener("DOMContentLoaded", () => {
    const id = document.body.dataset.agrupacioId;
    if (id) window.magatzemPrep(id);
    else window.magatzemLlista();
});
