(() => {
"use strict";

// ============================================================
// Constants i utilitats
// ============================================================
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const fmt = new Intl.NumberFormat("ca-ES");
const fmtKg = new Intl.NumberFormat("ca-ES", { maximumFractionDigits: 0 });

// "SAP/-1/97" -> "#97": el número de la càrrega, com a la preparació.
// L'identificador sencer queda al title.
function numCarrega(carregaId) {
    const ultim = String(carregaId || "").split("/").pop() || "";
    return `#${ultim.replace(/^0+/, "") || ultim}`;
}
function codiCarregaHTML(carregaId) {
    return `<code title="${escapeHtml(carregaId)}">${escapeHtml(numCarrega(carregaId))}</code>`;
}

// fmtData i fmtDataHora venen carregades des de fmt.js abans d'aquest fitxer.

const STORAGE_KEY = "agrupacioCarregues.prefs.v1";

// Paleta de 16 colors per identificar càrregues (estil Tableau 10 + addicionals).
// Els primers són els més contrastats entre si i NO fan servir vermell,
// taronja ni verd: són els colors d'estat (pendent / a mitges / fet) i una
// càrrega verda al costat d'un "fet" verd es confonia. Aquests van al final.
// La mateixa paleta i el mateix ordre que PALETA_MAG (magatzem.js).
const PALETA = [
    { color: "#1f77b4", bg: "#e8f0f7" },  // 1  blau
    { color: "#9467bd", bg: "#f1ebf7" },  // 2  lila
    { color: "#17becf", bg: "#e0f5f7" },  // 3  cian
    { color: "#e377c2", bg: "#fbe6f3" },  // 4  rosa
    { color: "#8c564b", bg: "#efe1de" },  // 5  marró
    { color: "#000000", bg: "#eeeeee" },  // 6  negre
    { color: "#4b0082", bg: "#ece0f0" },  // 7  indigo
    { color: "#bcbd22", bg: "#f6f6d8" },  // 8  oliva-lima
    { color: "#7f7f7f", bg: "#f0f0f0" },  // 9  gris
    { color: "#ff1493", bg: "#ffe2ee" },  // 10 magenta intens
    { color: "#a52a2a", bg: "#f4dada" },  // 11 borgonya
    { color: "#daa520", bg: "#fbf0d4" },  // 12 or
    { color: "#ff7f0e", bg: "#fff0db" },  // 13 taronja
    { color: "#2ca02c", bg: "#e8f5e6" },  // 14 verd
    { color: "#d62728", bg: "#fce6e6" },  // 15 vermell
    { color: "#00875a", bg: "#d8f0e6" },  // 16 verd-blau bandera
];

function colorPerCarrega(carregaId, idx) {
    return PALETA[idx % PALETA.length];
}

// ============================================================
// Estat
// ============================================================
const state = {
    carregues: [],
    seleccio: new Set(),
    lastClickedIndex: -1,
    filtreText: "",
    ordenacio: { col: "car_fecsalida", dir: "desc" },
    ordenacioProductes: { col: "total_sacs", dir: "desc" },
    paginacio: { limit: 500, offset: 0, total: 0 },
    filtresAvancats: { estat: null, art_codi: null, art_descrip: "" },
    resultat: null,
    agrupacioActualId: null,    // id de l'agrupació desada que estem mirant (null si és nova)
    agrupacioActual: null,      // {nom, plantilla} de l'agrupació desada, per canviar-los
    colorsCarrega: new Map(),  // carrega_id -> {color, bg}
    abortCerca: null,
    abortAgrupar: null,
    plantilles: [],            // llista de plantilles desades (GET /api/plantilles)
    plantillesTancades: new Set(),  // ids tancades per l'usuari en aquesta cerca
    // Quan obrim el modal des d'una agrupació desada, guardem l'estat
    // de la cerca actual per restaurar-lo al tancar (l'usuari espera
    // tornar a la pàgina principal tal com l'havia deixat).
    backupAbansAgrupacio: null,
    modalDesAgrupacioDesada: false,
    // art_codis preparats al magatzem per a l'agrupació actualment oberta al modal
    productesPreparats: new Set(),
    // Polling de canvis a les agrupacions (refresc automatic de la llista
    // principal quan algu marca un producte com a preparat al magatzem).
    agrupacionsVersion: null,
    agrupacionsPollId: null,
    agrupacionsRefreshInFlight: false,
    // % pistolejat a l'SGA de cada càrrega pendent (agrupada o no), per
    // DocEntry: {estat, percent, kg_total, kg_fets}. Ve de
    // /api/pistolejat/carregues, a part de la llista perquè va a SAP.
    pistolejat: new Map(),
    pistolejatInFlight: false,
};

// Cada quant es torna a llegir el pistolejat de les càrregues de la llista.
const PISTOLEJAT_POLL_MS = 30_000;
const PISTOLEJAT_MAX_IDS = 300;   // el mateix límit que el servidor

const PLANTILLA_MIN_COMPATIBLES = 2;  // llindar per mostrar el banner

let _storageWarned = false;
function carregarPrefs() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return {};
        return JSON.parse(raw) || {};
    } catch { return {}; }
}
function guardarPrefs(patch) {
    try {
        const cur = carregarPrefs();
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cur, ...patch }));
    } catch {
        if (!_storageWarned) {
            _storageWarned = true;
            // showToast pot no existir encara durant el bootstrap inicial; sigues defensiu
            try { showToast("warning", "Preferències no desades", "El navegador no permet guardar les preferències. Es perdran en tancar."); } catch {}
        }
    }
}

// ============================================================
// Utilitats genèriques
// ============================================================
function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}
function escapeId(s) {
    return String(s ?? "").replace(/[^a-zA-Z0-9_-]/g, "_");
}
function debounce(fn, ms) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), ms);
    };
}
function getCsrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
}

async function fetchJson(url, options = {}) {
    let resp;
    // Afegim el header CSRF automàticament a totes les peticions que
    // modifiquen estat. Els GETs no el necessiten (no els valida el backend).
    const method = (options.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
        const tok = getCsrfToken();
        if (tok) {
            const headers = new Headers(options.headers || {});
            if (!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", tok);
            options = { ...options, headers };
        }
    }
    try {
        resp = await fetch(url, options);
    } catch (e) {
        // Error de xarxa abans d'arribar al servidor (offline, DNS, timeout)
        if (e.name === "AbortError") throw e;
        const err = new Error("Sembla que no hi ha connexió. Comprova que estàs en línia i torna a provar.");
        err.kind = "network";
        throw err;
    }
    if (!resp.ok) {
        let missatge = null;
        try { const j = await resp.json(); if (j.error) missatge = j.error; } catch (_) {}
        // Per als 503 (DB o motor caigut) afegim suggerència
        if (resp.status === 503 && !missatge) {
            missatge = "Un servei intern no respon ara. Reintenta en uns segons; si persisteix, avisa IT.";
        }
        if (!missatge) missatge = `Resposta inesperada del servidor (${resp.status}).`;
        const err = new Error(missatge);
        err.kind = "http";
        err.status = resp.status;
        throw err;
    }
    try {
        return await resp.json();
    } catch {
        const err = new Error("El servidor ha respost amb dades incorrectes. Avisa IT.");
        err.kind = "parse";
        throw err;
    }
}

// ============================================================
// Toasts
// ============================================================
const TOAST_ICONS = { success: "✓", error: "✕", warning: "⚠", info: "ℹ" };
const TOAST_TTL = { success: 4500, error: 9000, warning: 7000, info: 5000 };

function showToast(type, title, body) {
    const wrap = $("#toasts");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.innerHTML = `
        <span class="toast-icon">${TOAST_ICONS[type] || ""}</span>
        <div class="toast-body">${title ? `<strong>${escapeHtml(title)}</strong>` : ""}${body ? escapeHtml(body) : ""}</div>
        <button class="toast-close" aria-label="Tanca">×</button>
    `;
    wrap.appendChild(t);
    const dismiss = () => {
        t.classList.add("is-leaving");
        setTimeout(() => t.remove(), 220);
    };
    t.querySelector(".toast-close").addEventListener("click", dismiss);
    setTimeout(dismiss, TOAST_TTL[type] || 5000);
    return t;
}
function tancaTotsToasts() {
    $$(".toast").forEach(t => {
        t.classList.add("is-leaving");
        setTimeout(() => t.remove(), 220);
    });
}

// ============================================================
// Botó amb spinner
// ============================================================
function btnLoading(btn, loading, labelOnLoad) {
    const lbl = btn.querySelector(".btn-label");
    const sp = btn.querySelector(".btn-spinner");
    if (loading) {
        btn.classList.add("is-loading");
        btn.disabled = true;
        if (lbl && labelOnLoad) lbl.dataset.orig = lbl.textContent, lbl.textContent = labelOnLoad;
        if (sp) sp.hidden = false;
    } else {
        btn.classList.remove("is-loading");
        btn.disabled = false;
        if (lbl && lbl.dataset.orig) lbl.textContent = lbl.dataset.orig, delete lbl.dataset.orig;
        if (sp) sp.hidden = true;
    }
}

// ============================================================
// Filtres ràpids de dates
// ============================================================
function toISO(d) {
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function calcRang(tipus) {
    const avui = new Date();
    avui.setHours(0,0,0,0);
    const d = new Date(avui);
    let desde, fins;
    switch (tipus) {
        case "today":
            desde = fins = toISO(avui); break;
        case "yesterday":
            d.setDate(d.getDate() - 1);
            desde = fins = toISO(d); break;
        case "this-week": {
            const dia = (avui.getDay() + 6) % 7; // dilluns=0
            const dl = new Date(avui); dl.setDate(avui.getDate() - dia);
            desde = toISO(dl); fins = toISO(avui); break;
        }
        case "last-week": {
            const dia = (avui.getDay() + 6) % 7;
            const dlAct = new Date(avui); dlAct.setDate(avui.getDate() - dia);
            const dlAnt = new Date(dlAct); dlAnt.setDate(dlAct.getDate() - 7);
            const dgAnt = new Date(dlAct); dgAnt.setDate(dlAct.getDate() - 1);
            desde = toISO(dlAnt); fins = toISO(dgAnt); break;
        }
        case "this-month": {
            const inici = new Date(avui.getFullYear(), avui.getMonth(), 1);
            desde = toISO(inici); fins = toISO(avui); break;
        }
        case "last-30": {
            const a = new Date(avui); a.setDate(a.getDate() - 30);
            desde = toISO(a); fins = toISO(avui); break;
        }
        default: return null;
    }
    return { desde, fins };
}
function aplicaFiltreRapid(tipus) {
    const r = calcRang(tipus);
    if (!r) return;
    $("#desde").value = r.desde;
    $("#fins").value = r.fins;
    validarFormulari();
    marcaFiltreActiu(tipus);
    buscarCarregues();
}
function marcaFiltreActiu(tipus) {
    $$(".chip-btn").forEach(b => b.classList.toggle("active", b.dataset.range === tipus));
}

// ============================================================
// Validació formulari
// ============================================================
function validarFormulari() {
    const desde = $("#desde").value;
    const fins = $("#fins").value;
    const inpD = $("#desde"), inpF = $("#fins");
    const errD = $("#err-desde"), errF = $("#err-fins");
    inpD.classList.remove("is-invalid");
    inpF.classList.remove("is-invalid");
    errD.hidden = true; errF.hidden = true;
    let ok = true;
    if (!desde) {
        inpD.classList.add("is-invalid");
        errD.textContent = "Tria una data.";
        errD.hidden = false;
        ok = false;
    }
    if (!fins) {
        inpF.classList.add("is-invalid");
        errF.textContent = "Tria una data.";
        errF.hidden = false;
        ok = false;
    }
    if (ok && desde > fins) {
        inpD.classList.add("is-invalid");
        inpF.classList.add("is-invalid");
        errF.textContent = "Ha de ser igual o posterior a 'Des de'.";
        errF.hidden = false;
        ok = false;
    }
    $("#btn-buscar").disabled = !ok;
    return ok;
}

// ============================================================
// Transportistes
// ============================================================
// ============================================================
// Component MultiSelect: chips + dropdown cercable
// ============================================================
function crearMultiSelect(rootSel, {
    onChange = () => {},
    emptyLabel = "Sense resultats",
} = {}) {
    const root = $(rootSel);
    if (!root) return null;
    const control = root.querySelector(".ms-control");
    const chipsBox = root.querySelector(".ms-chips");
    const search = root.querySelector(".ms-search");
    const dropdown = root.querySelector(".ms-dropdown");
    let items = [];           // {value, label, code}
    const selected = new Set();
    let focusedIdx = -1;

    const isOpen = () => !dropdown.hidden;
    const obre = () => {
        if (isOpen()) return;
        dropdown.hidden = false;
        root.classList.add("is-open");
        control.setAttribute("aria-expanded", "true");
        renderDropdown();
    };
    const tanca = () => {
        dropdown.hidden = true;
        root.classList.remove("is-open");
        control.setAttribute("aria-expanded", "false");
        focusedIdx = -1;
        if (search) { search.value = ""; }
        renderDropdown();
    };

    function visibles() {
        const q = (search.value || "").toLowerCase().trim();
        if (!q) return items;
        return items.filter(it =>
            (it.label || "").toLowerCase().includes(q) ||
            (it.code || "").toLowerCase().includes(q)
        );
    }

    function renderChips() {
        chipsBox.innerHTML = "";
        for (const v of selected) {
            const it = items.find(x => x.value === v);
            const lbl = it ? (it.label || it.value) : v;
            const chip = document.createElement("span");
            chip.className = "ms-chip";
            chip.innerHTML = `<span class="ms-chip-label">${escapeHtml(lbl)}</span>` +
                             `<button type="button" class="ms-chip-x" aria-label="Treu ${escapeHtml(lbl)}">×</button>`;
            chip.querySelector(".ms-chip-x").addEventListener("click", (ev) => {
                ev.stopPropagation();
                selected.delete(v);
                renderChips();
                renderDropdown();
                onChange([...selected]);
            });
            chipsBox.appendChild(chip);
        }
    }

    function renderDropdown() {
        const v = visibles();
        dropdown.innerHTML = "";
        if (!v.length) {
            const li = document.createElement("li");
            li.className = "ms-empty";
            li.textContent = emptyLabel;
            dropdown.appendChild(li);
            return;
        }
        v.forEach((it, i) => {
            const li = document.createElement("li");
            li.className = "ms-option" + (selected.has(it.value) ? " is-selected" : "") + (i === focusedIdx ? " is-focused" : "");
            li.setAttribute("role", "option");
            li.setAttribute("aria-selected", selected.has(it.value) ? "true" : "false");
            li.innerHTML = `<span class="ms-option-check" aria-hidden="true"></span>` +
                           (it.code ? `<code>${escapeHtml(it.code)}</code>` : "") +
                           `<span>${escapeHtml(it.label || it.value)}</span>`;
            li.addEventListener("click", (ev) => {
                ev.stopPropagation();
                toggleVal(it.value);
            });
            dropdown.appendChild(li);
        });
    }

    function toggleVal(v) {
        if (selected.has(v)) selected.delete(v);
        else selected.add(v);
        renderChips();
        renderDropdown();
        onChange([...selected]);
    }

    control.addEventListener("click", () => {
        if (!isOpen()) obre();
        search.focus();
    });
    search.addEventListener("input", () => { focusedIdx = -1; renderDropdown(); });
    search.addEventListener("keydown", (e) => {
        const v = visibles();
        if (e.key === "ArrowDown") { e.preventDefault(); focusedIdx = Math.min(v.length - 1, focusedIdx + 1); renderDropdown(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); focusedIdx = Math.max(0, focusedIdx - 1); renderDropdown(); }
        else if (e.key === "Enter") {
            if (focusedIdx >= 0 && v[focusedIdx]) { e.preventDefault(); toggleVal(v[focusedIdx].value); }
        }
        else if (e.key === "Escape") { tanca(); }
        else if (e.key === "Backspace" && !search.value) {
            const arr = [...selected];
            if (arr.length) {
                selected.delete(arr[arr.length - 1]);
                renderChips(); renderDropdown(); onChange([...selected]);
            }
        }
    });
    document.addEventListener("click", (e) => {
        if (!root.contains(e.target)) tanca();
    });

    return {
        setItems(arr) {
            items = arr || [];
            renderChips();
            renderDropdown();
        },
        setSelected(values) {
            selected.clear();
            for (const v of (values || [])) selected.add(v);
            renderChips();
            renderDropdown();
        },
        getSelected() { return [...selected]; },
    };
}

let msTransportistes = null;
async function carregarTransportistes() {
    msTransportistes = crearMultiSelect("#ms-transportistes", {
        onChange: () => {
            // Persistir i refrescar al canviar selecció
            guardarPrefs({ tra_codis: msTransportistes.getSelected() });
            buscarCarregues();
        },
        emptyLabel: "No s'ha trobat cap transportista",
    });
    if (!msTransportistes) return;
    try {
        const llista = await fetchJson("/api/transportistes");
        msTransportistes.setItems(llista.map(t => ({
            value: t.tra_codi,
            code: t.tra_codi,
            label: t.tra_nom,
        })));
        const prefs = carregarPrefs();
        const desats = Array.isArray(prefs.tra_codis) ? prefs.tra_codis
                      : (prefs.tra_codi ? [prefs.tra_codi] : []);
        msTransportistes.setSelected(desats);
    } catch (e) {
        showToast("error", "No s'han pogut carregar transportistes", e.message);
    }
}

// ============================================================
// Skeleton durant la cerca
// ============================================================
function pintaSkeleton(n = 5) {
    const tbody = $("#taula-carregues tbody");
    tbody.innerHTML = "";
    for (let i = 0; i < n; i++) {
        const tr = document.createElement("tr");
        tr.className = "skeleton-row";
        tr.innerHTML = `<td colspan="9"><span class="skeleton-bar" style="width:${60 + Math.random()*30}%"></span></td>`;
        tbody.appendChild(tr);
    }
    $("#empty-inicial").hidden = true;
    $("#seccio-llista").hidden = false;
    $("#msg-llista-buida").hidden = true;
}

// ============================================================
// Cerca de càrregues
// ============================================================
async function buscarCarregues(append = false) {
    if (!validarFormulari()) return;
    const desde = $("#desde").value;
    const fins = $("#fins").value;
    const traCodis = msTransportistes ? msTransportistes.getSelected() : [];

    if (!append) {
        guardarPrefs({ desde, fins, tra_codis: traCodis });
        state.paginacio.offset = 0;
    }

    if (state.abortCerca) state.abortCerca.abort();
    state.abortCerca = new AbortController();

    const btn = append ? $("#btn-carrega-mes") : $("#btn-buscar");
    btnLoading(btn, true, append ? "Carregant…" : "Cercant…");
    if (!append) pintaSkeleton();
    try {
        const params = new URLSearchParams({
            desde, fins,
            limit: String(state.paginacio.limit),
            offset: String(state.paginacio.offset),
        });
        for (const c of traCodis) params.append("tra_codi", c);
        const { estat, art_codi } = state.filtresAvancats;
        if (estat !== null && estat !== undefined && estat !== "") params.set("estat", String(estat));
        if (art_codi) params.set("art_codi", art_codi);
        const resp = await fetchJson(`/api/carregues?${params}`, {
            signal: state.abortCerca.signal,
        });
        // Compatibilitat: el backend retorna {items,total,limit,offset}
        const items = Array.isArray(resp) ? resp : resp.items;
        const total = Array.isArray(resp) ? items.length : resp.total;
        if (append) {
            state.carregues = state.carregues.concat(items);
        } else {
            state.carregues = items;
            state.seleccio.clear();
            state.lastClickedIndex = -1;
            state.filtreText = "";
            $("#filtre-taula").value = "";
        }
        state.paginacio.total = total;
        state.paginacio.offset = state.carregues.length;
        // Nova cerca: oblidem els banners tancats prèviament
        if (!append) state.plantillesTancades.clear();
        renderLlistaCarregues();
        actualitzarBannerPlantilles();
        refrescaPistolejat();
        if (!append) aplicaFocusPendent();
        // Prefetch del detall de les primeres N visibles en idle (només si
        // és cerca nova, no append: l'append típicament afegeix files fora
        // de la vista immediata).
        if (!append) prefetchDetallsCarregues(state.carregues);
    } catch (e) {
        if (e.name !== "AbortError") {
            showToast("error", "Error cercant càrregues", e.message);
            if (!append) $("#taula-carregues tbody").innerHTML = "";
        }
    } finally {
        btnLoading(btn, false);
    }
}

// ============================================================
// Deep-link des de /calendari: ?focus=carrega_id
// Si arriba un id, scroll a la fila i flash visual un cop renderitzada.
// ============================================================
function aplicaFocusPendent() {
    // El valor ve com a data-attr al <body> (evita inline script i compleix CSP)
    const target = (document.body.dataset.focusCarrega || "").trim();
    if (!target) return;
    document.body.dataset.focusCarrega = "";  // consumeix-lo: només una vegada per pàgina
    requestAnimationFrame(() => {
        const tr = document.querySelector(`#taula-carregues tbody tr[data-carrega-id="${CSS.escape(target)}"]`);
        if (!tr) return;
        tr.scrollIntoView({ behavior: "smooth", block: "center" });
        tr.classList.add("row-focus-flash");
        setTimeout(() => tr.classList.remove("row-focus-flash"), 2200);
    });
}

// ============================================================
// Renderitzar llista de càrregues
// ============================================================
function llistaVisible() {
    let llista = state.carregues.slice();
    // Filtre text
    if (state.filtreText) {
        const q = state.filtreText.toLowerCase();
        llista = llista.filter(c =>
            (c.carrega_id || "").toLowerCase().includes(q) ||
            (c.car_descripcion || "").toLowerCase().includes(q) ||
            (c.transportista || "").toLowerCase().includes(q) ||
            (c.tra_codi || "").toLowerCase().includes(q) ||
            (c.car_matricula || "").toLowerCase().includes(q) ||
            (c.car_nomconductor || "").toLowerCase().includes(q) ||
            (c.car_observaciones || "").toLowerCase().includes(q) ||
            ((c.agrupacions || []).some(a => (a.nom || "").toLowerCase().includes(q)))
        );
    }
    // Ordenació
    const { col, dir } = state.ordenacio;
    if (col) {
        const sign = dir === "asc" ? 1 : -1;
        const valorOrdre = (c) => {
            if (col === "agrupacio_nom") {
                const e = estatAgrupacio(c);
                return e ? e.info.nom : "";
            }
            if (col === "car_fecsalida") {
                // Ordena per data + hora (ISO és lexicogràficament ordenable)
                return (c.car_fecsalida || "") + (c.car_fecsalida_hora ? " " + c.car_fecsalida_hora : "");
            }
            return c[col];
        };
        llista.sort((a, b) => {
            const va = valorOrdre(a) ?? "";
            const vb = valorOrdre(b) ?? "";
            if (typeof va === "number" && typeof vb === "number") return (va - vb) * sign;
            return String(va).localeCompare(String(vb), "ca", { numeric: true }) * sign;
        });
    }
    return llista;
}

function actualitzarPeuPaginacio() {
    const peu = $("#peu-paginacio");
    if (!peu) return;
    const txt = $("#peu-paginacio-text");
    const btn = $("#btn-carrega-mes");
    const carregats = state.carregues.length;
    const total = state.paginacio.total || carregats;
    if (total > carregats) {
        peu.hidden = false;
        if (txt) txt.textContent = `Mostrant ${fmt.format(carregats)} de ${fmt.format(total)}`;
        if (btn) btn.disabled = false;
    } else {
        peu.hidden = true;
    }
}

// Resol l'estat d'agrupació d'una càrrega: null o info de l'agrupació.
// Tres estats possibles:
//   - "activa"         → agrupada però cap producte preparat encara
//   - "en_preparacio"  → ja s'ha produït algun producte (el pistolejat és expedició i no compta)
//   - "finalitzada"    → tots els productes preparats
// (una càrrega només pot estar en una agrupació activa al mateix temps)
function estatAgrupacio(c) {
    const ags = c.agrupacions || [];
    if (!ags.length) return null;
    const activa = ags.find(a => !a.finalitzada);
    if (activa) {
        const tipus = (activa.n_preparats || 0) > 0 ? "en_preparacio" : "activa";
        return { tipus, info: activa, totes: ags };
    }
    return { tipus: "finalitzada", info: ags[0], totes: ags };
}

function badgeAgrupacioHTML(estat) {
    if (!estat) return "";
    let cls, txt;
    if (estat.tipus === "finalitzada") {
        cls = "badge-grouped badge-grouped--done";
        txt = "✓ Acabada";
    } else if (estat.tipus === "en_preparacio") {
        cls = "badge-grouped badge-grouped--progress";
        const np = estat.info.n_preparats || 0;
        const nt = estat.info.n_productes || 0;
        // Primer la producció (marcada a mà) i després el % pistolejat a l'SGA
        // (expedició, informatiu; null si encara no s'ha llegit).
        const pct = estat.info.pct_pistolejat;
        const parts = [nt > 0 ? `${np}/${nt} produïts` : "", pct ? `${pct}% pist.` : ""].filter(Boolean);
        txt = parts.length ? `◐ ${parts.join(" · ")}` : "◐ Produint";
    } else {
        cls = "badge-grouped";
        txt = "Ja agrupada";
    }
    const tip = `Agrupació "${estat.info.nom}" · ${fmtData(estat.info.ts) || ""}` +
        (estat.tipus === "en_preparacio" ? " · productes produïts / total · % de kg pistolejats (expedició)" : "") +
        " · Toca per obrir-la";
    return ` <button type="button" class="${cls}" title="${escapeHtml(tip)}" data-act="obrir-agrupacio" data-id="${escapeHtml(estat.info.id)}">${txt}</button>`;
}

// Etiqueta del pistolejat a l'SGA (expedició) d'una càrrega pendent, estigui
// agrupada o no. Res si encara no s'ha pistolejat res.
function badgePistolejatHTML(c) {
    const p = state.pistolejat.get(String(c.car_numero));
    if (!p || p.estat === "pendent" || p.estat === "sense_dades") return "";
    const complet = p.estat === "complet";
    const txt = complet ? "✓ Pistolejada" : `◐ ${p.percent}% pist.`;
    const tip = complet
        ? "L'SGA ja ha pistolejat (o fet l'albarà de) tota la càrrega"
        : `Pistolejat a l'SGA: ${p.percent}% dels kg de la càrrega`;
    return ` <span class="badge-pist${complet ? " badge-pist--done" : ""}" title="${escapeHtml(tip)}">${txt}</span>`;
}

function crearFilaCarrega(c) {
    const tr = document.createElement("tr");
    tr.dataset.carregaId = c.carrega_id;
    tr.classList.add("row-clickable");
    if (c.palletitzable === false) {
        tr.classList.add("not-palletitzable");
        tr.title = "No es pot palletitzar (granel o unitats soltes): l'agrupació no la compta";
    }

    const tdCheck = document.createElement("td");
    tdCheck.className = "col-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.role = "carrega-check";
    tdCheck.appendChild(cb);
    tr.appendChild(tdCheck);

    const tdExpand = document.createElement("td");
    tdExpand.className = "col-expand";
    const btnExpand = document.createElement("button");
    btnExpand.type = "button";
    btnExpand.className = "toggle-btn";
    btnExpand.dataset.role = "carrega-expand";
    btnExpand.innerHTML = `<span aria-hidden="true">▶</span>`;
    btnExpand.title = "Veure comandes i articles de la càrrega";
    btnExpand.setAttribute("aria-label", "Mostra les comandes de la càrrega");
    btnExpand.setAttribute("aria-expanded", "false");
    tdExpand.appendChild(btnExpand);
    tr.appendChild(tdExpand);

    const estat = estatAgrupacio(c);
    tr.insertAdjacentHTML("beforeend", `
        <td data-col="carrega_id">${codiCarregaHTML(c.carrega_id)}${badgeAgrupacioHTML(estat)}${badgePistolejatHTML(c)}</td>
        <td data-col="car_descripcion" class="cell-truncate" title="${escapeHtml(c.car_descripcion)}">${escapeHtml(c.car_descripcion || "—")}</td>
        <td data-col="car_fecsalida" class="col-data">${escapeHtml(((fmtData(c.car_fecsalida || c.car_fecha) || "") + (c.car_fecsalida_hora ? " " + c.car_fecsalida_hora : "")) || "—")}</td>
        <td data-col="transportista" class="cell-truncate" title="${escapeHtml(c.transportista || c.tra_codi)}">${escapeHtml(c.transportista || c.tra_codi)}</td>
        <td data-col="car_matricula" class="cell-truncate" title="${escapeHtml(c.car_matricula)}">${escapeHtml(c.car_matricula)}</td>
        <td data-col="car_observaciones" class="cell-truncate" title="${escapeHtml(c.car_observaciones)}">${escapeHtml(c.car_observaciones)}</td>
        <td data-col="agrupacio_nom" class="col-agrupacio">${cellAgrupacioHTML(estat)}</td>
    `);
    return tr;
}

function cellAgrupacioHTML(estat) {
    if (!estat) return `<span class="muted">—</span>`;
    const dataStr = fmtData(estat.info.ts) || "";
    let cls = "cell-agrupacio";
    let dot = "●";
    if (estat.tipus === "finalitzada") { cls += " cell-agrupacio--done"; dot = "✓"; }
    else if (estat.tipus === "en_preparacio") { cls += " cell-agrupacio--progress"; dot = "◐"; }
    return `<button type="button" class="${cls}" data-act="obrir-agrupacio" data-id="${escapeHtml(estat.info.id)}" title="Veure resultat · ${escapeHtml(estat.info.nom)}">
        <span class="cell-agrupacio-dot">${dot}</span>
        <span class="cell-agrupacio-nom">${escapeHtml(estat.info.nom)}</span>
        <span class="cell-agrupacio-data">${escapeHtml(dataStr)}</span>
    </button>`;
}

function actualitzaFilaCarrega(tr, c, idx) {
    tr.dataset.idx = idx;
    const cb = tr.querySelector('input[data-role="carrega-check"]');
    const estat = estatAgrupacio(c);
    const bloquejada = estat != null;
    const seleccionada = state.seleccio.has(c.carrega_id);
    if (cb) {
        cb.disabled = bloquejada;
        if (cb.checked !== seleccionada) cb.checked = seleccionada;
    }
    tr.classList.toggle("row-selected", seleccionada);
    tr.classList.toggle("row-grouped", bloquejada && estat?.tipus === "activa");
    tr.classList.toggle("row-grouped-progress", estat?.tipus === "en_preparacio");
    tr.classList.toggle("row-grouped-done", estat?.tipus === "finalitzada");

    // Refresca el badge d'agrupació (3a td) i la cel·la d'agrupació (última td)
    // — necessari perquè quan refresquem via polling, l'estat (n_preparats,
    // finalitzada) pot haver canviat i el badge "(4/15)" hauria de reflectir-ho.
    const novaBadgeTd = `${codiCarregaHTML(c.carrega_id)}${badgeAgrupacioHTML(estat)}${badgePistolejatHTML(c)}`;
    const novaAgrupTd = cellAgrupacioHTML(estat);
    const tdBadge = tr.children[2];
    const tdAgrup = tr.children[tr.children.length - 1];
    if (tdBadge && tdBadge.innerHTML !== novaBadgeTd) tdBadge.innerHTML = novaBadgeTd;
    if (tdAgrup && tdAgrup.innerHTML !== novaAgrupTd) tdAgrup.innerHTML = novaAgrupTd;
}

function renderLlistaCarregues() {
    const tbody = $("#taula-carregues tbody");
    $("#empty-inicial").hidden = true;
    $("#seccio-llista").hidden = false;

    const llista = llistaVisible();
    const carregats = state.carregues.length;
    const llegendaNP = $("#llegenda-np");
    if (llegendaNP) llegendaNP.hidden = !state.carregues.some(c => c.palletitzable === false);
    const total = state.paginacio.total || carregats;
    const nAgrupades = state.carregues.filter(c => estatAgrupacio(c) != null).length;
    const sufixAgrup = nAgrupades > 0 ? ` · ${nAgrupades} ja agrupades` : "";
    $("#count-carregues").textContent = `(${total > carregats ? `${carregats} de ${total}` : total}${sufixAgrup})`;
    if (state.filtreText) {
        $("#count-filtre").hidden = false;
        $("#count-filtre").textContent = `mostrant ${llista.length} de ${carregats}`;
    } else {
        $("#count-filtre").hidden = true;
    }
    actualitzarPeuPaginacio();

    // Marca columna ordenada
    $$("#taula-carregues thead th[data-sort]").forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.sort === state.ordenacio.col) {
            th.classList.add(state.ordenacio.dir === "asc" ? "sort-asc" : "sort-desc");
        }
    });

    if (state.carregues.length === 0) {
        tbody.innerHTML = "";
        $("#msg-llista-buida").hidden = false;
        actualitzarBotoAgrupar();
        actualitzarCheckAll();
        return;
    }
    if (llista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="muted" style="text-align:center;padding:1.5rem;">Cap càrrega coincideix amb el filtre "${escapeHtml(state.filtreText)}".</td></tr>`;
        $("#msg-llista-buida").hidden = true;
        actualitzarBotoAgrupar();
        actualitzarCheckAll();
        return;
    }
    $("#msg-llista-buida").hidden = true;

    // Neteja files no-data (skeleton, missatges de filtre buit, etc.) abans del diff
    for (const tr of Array.from(tbody.children)) {
        if (!tr.dataset.carregaId && !tr.classList.contains("row-detall-carrega")) {
            tr.remove();
        }
    }
    // Diff render: reutilitza files existents per carrega_id, mou-les a la posició correcta
    const existents = new Map();
    for (const tr of tbody.querySelectorAll('tr[data-carrega-id]')) {
        existents.set(tr.dataset.carregaId, tr);
    }
    let anterior = null;
    llista.forEach((c, idx) => {
        let tr = existents.get(c.carrega_id);
        if (!tr) {
            tr = crearFilaCarrega(c);
            tbody.appendChild(tr);
        } else {
            existents.delete(c.carrega_id);
        }
        actualitzaFilaCarrega(tr, c, idx);
        // Garanteix l'ordre desitjat
        if (anterior) {
            if (anterior.nextSibling !== tr) tbody.insertBefore(tr, anterior.nextSibling);
        } else {
            if (tbody.firstChild !== tr) tbody.insertBefore(tr, tbody.firstChild);
        }
        anterior = tr;
    });
    // Elimina files sobrants (ja no a la vista)
    for (const [, tr] of existents) {
        const next = tr.nextElementSibling;
        if (next && next.classList.contains("row-detall-carrega")) next.remove();
        tr.remove();
    }

    actualitzarBotoAgrupar();
    actualitzarCheckAll();
}

// ============================================================
// Gestió de selecció (amb shift+click per rang)
// ============================================================
function gestionaSeleccio(carregaId, idx, shift, checked) {
    const bloquejada = (c) => estatAgrupacio(c) != null;
    if (shift && state.lastClickedIndex >= 0) {
        const visibles = llistaVisible();
        const start = Math.min(state.lastClickedIndex, idx);
        const end = Math.max(state.lastClickedIndex, idx);
        for (let i = start; i <= end; i++) {
            const c = visibles[i];
            if (!c || bloquejada(c)) continue;
            if (checked) state.seleccio.add(c.carrega_id);
            else state.seleccio.delete(c.carrega_id);
        }
    } else {
        const c = state.carregues.find(x => x.carrega_id === carregaId);
        if (c && bloquejada(c)) {
            showToast("warning", "Càrrega ja agrupada", `Aquesta càrrega ja és en una agrupació. Elimina-la primer si vols tornar-la a agrupar.`);
            return;
        }
        if (checked) state.seleccio.add(carregaId);
        else state.seleccio.delete(carregaId);
    }
    state.lastClickedIndex = idx;
    renderLlistaCarregues();
}

function marcarTotes(valor) {
    const bloquejada = (c) => estatAgrupacio(c) != null;
    if (valor) {
        for (const c of llistaVisible()) {
            if (!bloquejada(c)) state.seleccio.add(c.carrega_id);
        }
    } else {
        state.seleccio.clear();
        state.lastClickedIndex = -1;
    }
    renderLlistaCarregues();
}

function actualitzarCheckAll() {
    const cb = $("#check-all");
    if (!cb) return;
    const visibles = llistaVisible();
    const sel = visibles.filter(c => state.seleccio.has(c.carrega_id)).length;
    cb.checked = visibles.length > 0 && sel === visibles.length;
    cb.indeterminate = sel > 0 && sel < visibles.length;
}

function actualitzarBotoAgrupar() {
    const n = state.seleccio.size;
    const btn = $("#btn-agrupar");
    const bar = $("#action-bar");
    const cnt = $("#action-count");
    const meta = $("#action-meta");
    const btnDesel = $("#btn-desselecciona");
    if (cnt) cnt.textContent = n;
    if (btnDesel) btnDesel.hidden = n === 0;
    const btnEtq = $("#btn-etiquetes");
    if (btnEtq) btnEtq.disabled = n === 0;

    // Estimació ràpida de pes total seleccionat
    if (meta) {
        if (n > 0) {
            const pes = state.carregues
                .filter(c => state.seleccio.has(c.carrega_id))
                .reduce((acc, c) => acc + (Number(c.car_pesonetocarga) || 0), 0);
            meta.textContent = pes > 0 ? `· ~${fmt.format(pes)} kg` : "";
        } else {
            meta.textContent = "";
        }
    }

    if (n === 0) {
        btn.disabled = true;
        btn.title = "Selecciona almenys una càrrega";
    } else if (n > 50) {
        btn.disabled = true;
        btn.title = `Màxim 50 càrregues — actualment ${n} seleccionades`;
    } else {
        btn.disabled = false;
        btn.title = `Agrupar ${n} càrregues`;
    }

    // Mostra/amaga barra d'acció
    if (bar) {
        const visible = n > 0;
        bar.hidden = !visible;
        document.body.classList.toggle("has-action-bar", visible);
    }
}

// ============================================================
// Detall de càrrega
// ============================================================
const detallCache = new Map();

// Prefetch silenciós del detall de les primeres N càrregues visibles.
// S'executa en idle del navegador: si l'operari expandeix una càrrega
// llavors el render és instantani (sense spinner de "Carregant contingut…").
// Errors es silencien — si fallen, l'expansió manual ja farà el seu camí.
const PREFETCH_TOP_N = 8;
let _prefetchAbort = null;
function prefetchDetallsCarregues(carregues) {
    if (!Array.isArray(carregues) || carregues.length === 0) return;
    if (_prefetchAbort) _prefetchAbort.abort();
    _prefetchAbort = new AbortController();
    const sig = _prefetchAbort.signal;
    const pending = carregues
        .slice(0, PREFETCH_TOP_N)
        .filter(c => c && c.carrega_id && !detallCache.has(c.carrega_id));
    if (pending.length === 0) return;

    const run = () => {
        // Seqüencial per no saturar el motor d'embalatges del backend.
        (async () => {
            for (const c of pending) {
                if (sig.aborted) return;
                if (detallCache.has(c.carrega_id)) continue;
                try {
                    const params = new URLSearchParams({
                        eje: c.eje_ejercicio, sca: c.sca_serie, car: c.car_numero,
                    });
                    const data = await fetch(`/api/carrega-detall?${params}`, {
                        credentials: "same-origin", signal: sig,
                    }).then(r => r.ok ? r.json() : null);
                    if (data) detallCache.set(c.carrega_id, data);
                } catch { /* silent — el botó d'expandir caurà al GET normal */ }
            }
        })();
    };
    if ("requestIdleCallback" in window) {
        requestIdleCallback(run, { timeout: 2000 });
    } else {
        setTimeout(run, 50);
    }
}

async function toggleDetallCarrega(c, tr, btn) {
    const existing = tr.nextElementSibling;
    if (existing && existing.classList.contains("row-detall-carrega")) {
        existing.remove();
        btn.innerHTML = `<span aria-hidden="true">▶</span>`;
        btn.setAttribute("aria-expanded", "false");
        return;
    }
    btn.innerHTML = `<span aria-hidden="true">▼</span>`;
    btn.setAttribute("aria-expanded", "true");

    const detall = document.createElement("tr");
    detall.className = "row-detall row-detall-carrega";
    const td = document.createElement("td");
    td.colSpan = 9;
    td.innerHTML = `<span class="loading-inline"><span class="spinner-inline"></span>Carregant contingut…</span>`;
    detall.appendChild(td);
    tr.parentNode.insertBefore(detall, tr.nextSibling);

    try {
        let data;
        if (detallCache.has(c.carrega_id)) {
            data = detallCache.get(c.carrega_id);
        } else {
            const params = new URLSearchParams({ eje: c.eje_ejercicio, sca: c.sca_serie, car: c.car_numero });
            data = await fetchJson(`/api/carrega-detall?${params}`);
            detallCache.set(c.carrega_id, data);
        }
        td.innerHTML = renderDetallCarrega(data);
    } catch (e) {
        td.innerHTML = `<span class="error-inline">Error: ${escapeHtml(e.message)}</span>`;
    }
}

function renderDetallCarrega(data) {
    if (!data.comandes || data.comandes.length === 0) {
        return `<span class="muted">Aquesta càrrega no té comandes associades a Detcargas.</span>`;
    }
    const blocks = data.comandes.map(a => {
        const linies = a.linies.map(l => {
            const np = l.palletitzable === false;
            const cls = np ? ' class="not-palletitzable"' : '';
            const tip = np ? ' title="No palletitzable: el motor d\'embalatges ignora aquesta línia"' : '';
            return `
            <tr${cls}${tip}>
                <td><code>${escapeHtml(l.art_codi)}</code></td>
                <td>${escapeHtml(l.art_descrip)}</td>
                <td>${escapeHtml(l.tunitat)}</td>
                <td class="num">${fmt.format(l.sacs)}</td>
                <td class="num">${fmtKg.format(l.kg)}</td>
            </tr>
        `;
        }).join("");
        const tipoBadge = a.det_tipo === "P"
            ? `<span class="badge badge-warn" title="Comanda pendent">P</span>`
            : `<span class="badge badge-ok" title="Comanda">A</span>`;
        const poblaHtml = a.pobla
            ? ` · <span class="comanda-pobla" title="Població d'enviament"><span aria-hidden="true">📍</span> ${escapeHtml(a.pobla)}</span>`
            : "";
        return `
            <div class="comanda-block">
                <h4>
                    <span><code>${escapeHtml(a.comanda)}</code> ${tipoBadge} · ${escapeHtml(a.cli_codi)} ${escapeHtml(a.cli_nom)}${poblaHtml}</span>
                    <span class="muted">${fmt.format(a.total_sacs)} sacs · ${fmtKg.format(a.total_kg)} kg</span>
                </h4>
                <table class="data-table data-table-mini">
                    <thead><tr><th>Article</th><th>Descripció</th><th>Envàs</th><th class="num">Sacs</th><th class="num">Kg</th></tr></thead>
                    <tbody>${linies || `<tr><td colspan="5" class="muted">Sense línies</td></tr>`}</tbody>
                </table>
            </div>
        `;
    }).join("");
    return `
        <div class="detall-resum muted">
            ${data.comandes.length} comandes · <strong>${fmt.format(data.total_sacs)}</strong> sacs · <strong>${fmtKg.format(data.total_kg)}</strong> kg
        </div>
        ${blocks}
    `;
}

// ============================================================
// Etiquetes de palet de les càrregues seleccionades
// ============================================================
// Les càrregues passen a la pantalla /etiquetes per localStorage (no hi
// caben a la URL) i s'obre en una pestanya nova per no perdre la selecció.
function obrirEtiquetes() {
    const carregues = state.carregues.filter(c => state.seleccio.has(c.carrega_id));
    if (!carregues.length) return;
    try {
        localStorage.setItem("etiquetes-carregues", JSON.stringify({ ts: Date.now(), carregues }));
    } catch (e) {
        showToast("error", "No s'han pogut preparar les etiquetes", "El navegador no deixa desar dades temporals.");
        return;
    }
    window.open("/etiquetes", "_blank");
}

// ============================================================
// Agrupar
// ============================================================
function actualitzarBotoMagatzem() {
    const a = $("#btn-veure-magatzem");
    if (!a) return;
    const desa = $("#btn-desar-agrupacio");
    const desada = !!state.agrupacioActualId;
    if (desada) {
        a.hidden = false;
        a.href = `/magatzem/${encodeURIComponent(state.agrupacioActualId)}`;
    } else {
        a.hidden = true;
        a.removeAttribute("href");
    }
    if (desa) {
        desa.classList.toggle("btn-primary", !desada);
        desa.classList.toggle("btn-ghost", desada);
        desa.textContent = desada ? "✎ Nom / plantilla" : "⭐ Desa";
        desa.title = desada ? "Ja està desada. Canvia'n el nom o marca-la com a plantilla recurrent."
                            : "No s'ha pogut desar sola: desa-la perquè el magatzem la pugui preparar";
    }
}

async function agrupar() {
    const sel = state.carregues.filter(c => state.seleccio.has(c.carrega_id));
    if (sel.length === 0) return;
    if (sel.length > 50) {
        showToast("warning", "Massa càrregues", `Selecciona com a màxim 50 (actualment ${sel.length}).`);
        return;
    }

    if (state.abortAgrupar) state.abortAgrupar.abort();
    state.abortAgrupar = new AbortController();

    const btn = $("#btn-agrupar");
    btnLoading(btn, true, `Agrupant ${sel.length} ${sel.length === 1 ? "càrrega" : "càrregues"}…`);

    // Feedback per a agrupacions llargues
    const t3s = setTimeout(() => {
        const lbl = btn.querySelector(".btn-label");
        if (lbl) lbl.textContent = `Agrupant ${sel.length} càrregues, pot trigar uns segons…`;
    }, 3000);
    const t20s = setTimeout(() => {
        showToast("warning", "Encara processant", "L'agrupació triga més del normal. Prem Esc per cancel·lar si cal.");
    }, 20000);

    try {
        const resp = await fetch("/api/agrupar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ carregues: sel }),
            signal: state.abortAgrupar.signal,
        });
        if (resp.status === 409) {
            const data = await resp.json().catch(() => ({}));
            mostrarConflicteDuplicats(data.duplicats || []);
            return;
        }
        if (!resp.ok) {
            let missatge = null;
            try { const j = await resp.json(); if (j.error) missatge = j.error; } catch (_) {}
            if (!missatge && resp.status === 503) {
                missatge = "El motor d'embalatges no respon ara. Reintenta en uns segons.";
            }
            if (!missatge) missatge = `Resposta inesperada del servidor (${resp.status}).`;
            throw new Error(missatge);
        }
        const resultat = await resp.json();
        state.resultat = resultat;
        state.productesPreparats = new Set();  // agrupació nova: cap producte preparat encara
        state.agrupacioActualId = null;   // resultat nou, encara no desat
        state.agrupacioActual = null;
        state.modalDesAgrupacioDesada = false;
        state.backupAbansAgrupacio = null;
        renderResultat(resultat);
        actualitzarBotoMagatzem();
        obrirModalResultat();
        const palets = resultat.total_palets_fisics || 0;
        const resumPalets = (resultat.tipus_palets || []).slice(0, 3)
            .map(t => `${t.quantitat} ${t.tipus_palet_descrip}`).join(", ");
        const resum = `${resultat.carregues.length} càrregues, ${resultat.productes.length} productes, ${palets} palets físics${resumPalets ? ` (${resumPalets})` : ""}.`;
        // Es desa sola: el magatzem la veu de seguida sense prémer "Desa".
        const nom = await desarAutomatic(sel, resultat);
        if (nom) {
            showToast("success", "Agrupació feta i desada", `"${nom}": ${resum}`);
        } else {
            showToast("success", "Agrupació completada", resum);
        }
    } catch (e) {
        if (e.name === "AbortError") {
            showToast("info", "Agrupació cancel·lada", "Has aturat el procés.");
        } else if (e.message && (e.message.includes("Failed to fetch") || e.name === "TypeError")) {
            showToast("error", "Sense connexió", "No s'ha pogut contactar amb el servidor. Comprova la xarxa.");
        } else {
            showToast("error", "No s'ha pogut agrupar", e.message);
        }
    } finally {
        clearTimeout(t3s);
        clearTimeout(t20s);
        state.abortAgrupar = null;
        btnLoading(btn, false);
        actualitzarBotoAgrupar();
    }
}

function mostrarConflicteDuplicats(duplicats) {
    // Una càrrega només pot estar en una agrupació. El diàleg llista les
    // conflictives amb dos accions per cada agrupació afectada: "Veure"
    // (la carrega al modal de resultat per inspeccionar-la) i "Eliminar"
    // (acció ràpida amb confirmació, perquè l'operari pugui desbloquejar
    // l'agrupació sense canviar de pantalla).
    let dlg = $("#duplicats-dialog");
    if (!dlg) {
        dlg = document.createElement("dialog");
        dlg.id = "duplicats-dialog";
        dlg.className = "help-dialog";
        document.body.appendChild(dlg);
    }
    const files = duplicats.map(d => {
        const ag = d.agrupacions[0];
        const estat = ag.finalitzada ? '<span class="dup-estat dup-estat-fin">FINALITZADA</span>' : '<span class="dup-estat dup-estat-act">EN PREPARACIÓ</span>';
        const data = ag.ts ? `<span class="dup-data">${escapeHtml(fmtData(ag.ts))}</span>` : "";
        return `
            <li class="dup-row">
                <div class="dup-info">
                    <code class="dup-carrega">${escapeHtml(d.carrega_id)}</code>
                    <span class="dup-arrow" aria-hidden="true">→</span>
                    <span class="dup-nom">${escapeHtml(ag.nom)}</span>
                    ${estat}
                    ${data}
                </div>
                <div class="dup-actions">
                    <button type="button" class="btn btn-sm" data-act="veure" data-id="${escapeHtml(ag.id)}">Veure</button>
                    <button type="button" class="btn btn-sm btn-danger" data-act="eliminar" data-id="${escapeHtml(ag.id)}" data-nom="${escapeHtml(ag.nom)}" data-cid="${escapeHtml(d.carrega_id)}">Eliminar</button>
                </div>
            </li>`;
    }).join("");
    dlg.innerHTML = `
        <header>
            <h3>Càrregues ja agrupades</h3>
            <button class="dialog-close" data-close aria-label="Tanca">×</button>
        </header>
        <div style="padding: 1rem 1.25rem">
            <p>Les següents càrregues ja són en una agrupació. Una càrrega només pot estar en una agrupació:</p>
            <ul class="dup-list">${files}</ul>
            <p class="muted" style="font-size:.85rem">Per agrupar-les de nou, elimina l'agrupació existent.</p>
            <div style="display:flex; gap:.5rem; justify-content:flex-end; margin-top:.75rem">
                <button type="button" class="btn" data-close>Tanca</button>
            </div>
        </div>
    `;
    dlg.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => dlg.close()));
    dlg.querySelectorAll('[data-act="veure"]').forEach(b => {
        b.addEventListener("click", () => {
            dlg.close();
            const id = b.dataset.id;
            if (id) carregarAgrupacioDesada(id);
        });
    });
    dlg.querySelectorAll('[data-act="eliminar"]').forEach(b => {
        b.addEventListener("click", async () => {
            const id = b.dataset.id;
            const nom = b.dataset.nom;
            const cid = b.dataset.cid;
            if (!id) return;
            const ok = await window.mostrarConfirmacio({
                titol: "Eliminar agrupació",
                missatge: `Eliminar "${nom}"? Les seves càrregues tornaran a estar disponibles per agrupar.`,
                btnOk: "Sí, elimina-la",
                btnCancel: "No",
                tipus: "danger",
            });
            if (!ok) return;
            try {
                await fetchJson(`/api/agrupacions/${encodeURIComponent(id)}`, { method: "DELETE" });
                showToast("success", "Agrupació eliminada", nom);
                // Treu visualment la fila i tanca el modal si era l'última
                const row = b.closest("li.dup-row");
                if (row) row.remove();
                if (!dlg.querySelector("li.dup-row")) {
                    dlg.close();
                    showToast("info", "Pots tornar a agrupar", "Totes les agrupacions conflictives s'han eliminat.");
                }
            } catch (e) {
                showToast("error", "Error eliminant", e.message);
            }
        });
    });
    if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
}

// Genera el desglós inline de palets per cada càrrega, en format "N×M" amb color
function palletsInlinePerProducte(p) {
    // Ordre per índex de càrrega (mateix ordre de la llegenda)
    const ordreIdx = new Map();
    if (state.resultat) {
        state.resultat.carregues.forEach((c, i) => ordreIdx.set(c.carrega_id, i));
    }
    const pcOrdenats = (p.per_carrega || []).slice().sort((a, b) =>
        (ordreIdx.get(a.carrega_id) ?? 999) - (ordreIdx.get(b.carrega_id) ?? 999)
    );

    const trossos = [];
    for (const pc of pcOrdenats) {
        const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#000" };
        // Agrupa palets idèntics (mateix nombre de sacs)
        const agg = new Map();
        for (const pd of (pc.palets || [])) {
            const k = `${pd.sacs}`;
            agg.set(k, (agg.get(k) || 0) + 1);
        }
        const peces = [...agg.entries()]
            .sort((a, b) => Number(b[0]) - Number(a[0]))
            .map(([sacs, n]) => `${n}×${sacs}`)
            .join(" ");
        if (peces) {
            trossos.push(`<span class="print-palets-grp" style="color:${col.color}">${peces}</span>`);
        }
    }
    return trossos.join(" ");
}

function omplirCapçaleraPrint() {
    if (!state.resultat) return;
    const r = state.resultat;
    const ara = new Date();
    const data = fmtData(ara);
    const hora = ara.toLocaleTimeString("ca-ES");
    const dt = $("#print-datetime");
    if (dt) dt.innerHTML = `${data}<br>${hora}`;

    // Data: si totes les càrregues tenen la mateixa data de sortida la mostrem,
    // sino mostrem el rang del filtre actual.
    const dates = [...new Set(r.carregues.map(c => c.data_sortida).filter(Boolean))];
    const desde = $("#desde")?.value, fins = $("#fins")?.value;
    let textData;
    if (dates.length === 1) {
        textData = fmtData(dates[0]);
    } else if (desde && fins) {
        textData = `${fmtData(desde)} → ${fmtData(fins)}`;
    } else {
        textData = "—";
    }
    const elD = $("#print-data-sortida");
    if (elD) elD.textContent = textData;

    // Transportista: si totes tenen el mateix el mostrem, sino "Diversos"
    const trans = [...new Set(r.carregues.map(c => c.transportista || c.tra_codi).filter(Boolean))];
    const textTr = trans.length === 1 ? trans[0] : (trans.length === 0 ? "—" : "Diversos");
    const elT = $("#print-transportista");
    if (elT) elT.textContent = textTr;

    // Llegenda de càrregues: nom_curt (color)
    const leg = $("#print-leg");
    if (leg) {
        leg.innerHTML = r.carregues.map((c, i) => {
            const col = state.colorsCarrega.get(c.carrega_id) || { color: "#000" };
            const nom = (c.descripcio || c.carrega_id).trim() || c.carrega_id;
            return `<span class="print-leg-item" style="color:${col.color}"><strong>${escapeHtml(nom)}</strong></span>`;
        }).join("");
    }
}

// Genera l'HTML d'impressió de l'oficina amb el mateix layout que el magatzem
// (cards d'article, número curt #NNN, [N×M TIPUS], capçalera i footer amb totals).
function generaImpressioOficina(r) {
    const fmtN = fmt;

    // Capçalera
    const ara = new Date();
    const desdeIso = $("#desde")?.value, finsIso = $("#fins")?.value;
    const desdeFmt = desdeIso ? fmtData(desdeIso) : "—";
    const finsFmt = finsIso ? fmtData(finsIso) : "—";
    const traNoms = [...new Set(r.carregues.map(c => (c.descripcio || c.transportista || "").trim()).filter(Boolean))];
    const carrsTxt = traNoms.slice(0, 6).join(" · ") + (traNoms.length > 6 ? ` · +${traNoms.length - 6}` : "");
    const titol = `Agrupació ${desdeFmt} → ${finsFmt}`;
    const meta = `${carrsTxt ? carrsTxt + " · " : ""}${fmtN.format(r.carregues.length)} càrregues · ${fmtN.format(r.total_sacs)} sacs · ${fmtN.format(r.total_palets_fisics)} palets · Imprès ${fmtData(ara)}`;
    const headerHtml = `
        <div class="mag-print-header">
            <div class="mag-print-title">${escapeHtml(titol)}</div>
            <div class="mag-print-meta">${escapeHtml(meta)}</div>
        </div>`;

    // Ordre de càrregues per a colors estables (mateix que la pantalla)
    const ordreIdx = new Map();
    r.carregues.forEach((c, i) => ordreIdx.set(c.carrega_id, i));

    // Símbol geomètric únic per càrrega (●, ■, ▲, ◆, ★, ...) — clau per
    // distingir-les en una impressió B&W on els colors no s'aprecien.
    // 20 símbols distints; si una agrupació n'usa més, es cicla.
    const SIMBOLS_CARREGA = [
        "●", "■", "▲", "◆", "★",
        "○", "□", "△", "◇", "☆",
        "▼", "◀", "▶", "⬟", "⬢",
        "♠", "♣", "♥", "♦", "✚",
    ];
    const simbolCarrega = (i) => SIMBOLS_CARREGA[i % SIMBOLS_CARREGA.length];
    const lletraPerCarrega = new Map();
    r.carregues.forEach((c, i) => lletraPerCarrega.set(c.carrega_id, simbolCarrega(i)));

    // Articles (ordenats com a la taula)
    const prods = productesOrdenats();
    const cardsHtml = prods.map(p => {
        const pcOrdenats = (p.per_carrega || []).slice().sort((a, b) =>
            (ordreIdx.get(a.carrega_id) ?? 999) - (ordreIdx.get(b.carrega_id) ?? 999)
        );
        const carregesHtml = pcOrdenats.map(pc => {
            const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096" };
            const lletra = lletraPerCarrega.get(pc.carrega_id) || "·";
            const peces = detallPaletsCarrega(pc);
            const carrega = r.carregues.find(c => c.carrega_id === pc.carrega_id);
            const nomCar = (carrega?.descripcio || pc.carrega_id).trim() || pc.carrega_id;
            const numFinal = String(pc.carrega_id).split("/").pop() || "";
            const numCurt = numFinal.replace(/^0+/, "") || numFinal;
            return `<span class="mag-carrega-row" style="--cb-color:${col.color}">
                        <span class="dot" aria-hidden="true">${escapeHtml(lletra)}</span>
                        <span class="nom">${escapeHtml(nomCar)}</span>
                        <span class="num">#${escapeHtml(numCurt)}</span>
                        <span class="detall">${escapeHtml(peces)} · ${fmtN.format(pc.total_sacs)} sacs</span>
                    </span>`;
        }).join("");
        return `
            <li class="mag-card">
                <div class="mag-art">
                    <div class="mag-art-top">
                        <span class="mag-art-descrip">${escapeHtml(p.art_descrip)}</span>
                        <span class="mag-art-codi">${escapeHtml(p.art_codi)}</span>
                        <span class="mag-art-sacs-big">${fmtN.format(p.total_sacs)} <span class="mag-art-sacs-lbl">sacs</span><span class="mag-art-sacs-kg">${fmtKg.format(p.total_kg)} kg</span></span>
                    </div>
                    <div class="mag-art-carregues">${carregesHtml}</div>
                </div>
                <button type="button" class="mag-prep-check" aria-hidden="true"></button>
            </li>`;
    }).join("");

    // Footer: totals palets per tipus + pes per càrrega.
    // Mostrem el descrip complet (sense abreviar) — és millor per al paper.
    const tipusHtml = (r.tipus_palets || []).map(t => {
        const nom = t.tipus_palet_descrip || t.tipus_palet || "";
        return `<span>${fmtN.format(t.quantitat)} ${escapeHtml(nom)}</span>`;
    }).join(" · ");
    const pesPerCar = new Map();
    for (const p of (r.productes || [])) {
        for (const pc of (p.per_carrega || [])) {
            pesPerCar.set(pc.carrega_id, (pesPerCar.get(pc.carrega_id) || 0) + (pc.total_kg || 0));
        }
    }
    const pesHtml = (r.carregues || []).map(c => {
        const col = state.colorsCarrega.get(c.carrega_id) || { color: "#000" };
        const lletra = lletraPerCarrega.get(c.carrega_id) || "·";
        const pes = pesPerCar.get(c.carrega_id) || 0;
        const nomCar = (c.descripcio || c.carrega_id).trim() || c.carrega_id;
        const numFinal = String(c.carrega_id).split("/").pop() || "";
        const numCurt = numFinal.replace(/^0+/, "") || numFinal;
        return `<span class="mag-pf-c" style="--cb-color:${col.color}" data-lletra="${escapeHtml(lletra)}">${escapeHtml(nomCar)} #${escapeHtml(numCurt)} · ${fmtKg.format(pes)} kg</span>`;
    }).join(" · ");
    const footerHtml = `
        <footer class="mag-print-footer">
            ${tipusHtml ? `<div class="mag-pf-row mag-pf-palets"><strong>Total palets:</strong> ${tipusHtml}</div>` : ""}
            ${pesHtml ? `<div class="mag-pf-row mag-pf-pes"><strong>Pes per càrrega:</strong> ${pesHtml}</div>` : ""}
        </footer>`;

    return `${headerHtml}<ul class="mag-articles">${cardsHtml}</ul>${footerHtml}`;
}

async function imprimirInforme() {
    if (!state.resultat) return;

    // Registra la impressió en segon pla: si l'operari no ha desat manualment,
    // l'agrupació queda persistida amb origen='impresa' i és consultable a
    // /control. Si ja hi havia un id (desat manual previ), només audit log.
    // Cap error de traçabilitat no ha de bloquejar la impressió real.
    try {
        const carregues = state.carregues.filter(c => state.seleccio.has(c.carrega_id));
        const data = await fetchJson("/api/agrupacions/imprimir", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                carregues,
                resultat: state.resultat,
                agrupacio_existent_id: state.agrupacioActualId || null,
            }),
        });
        if (data && data.creada && data.id) {
            state.agrupacioActualId = data.id;
            actualitzarBotoMagatzem();
        }
    } catch (e) {
        console.warn("No s'ha pogut registrar la impressió:", e && e.message);
    }

    omplirCapçaleraPrint();

    // Injecta el contenidor d'impressió amb el layout del magatzem
    const old = document.getElementById("oficina-print");
    if (old) old.remove();
    const root = document.createElement("div");
    root.id = "oficina-print";
    root.className = "mag-body";   // perquè magatzem.css @media print apliqui font-size etc.
    root.innerHTML = generaImpressioOficina(state.resultat);
    document.body.appendChild(root);

    window.print();

    // Neteja després d'imprimir
    setTimeout(() => root.remove(), 400);
}

function obrirModalResultat() {
    const dlg = $("#resultat-dialog");
    if (!dlg) return;
    if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
    else dlg.setAttribute("open", "");
    // Mantenir scroll del modal a dalt
    const body = $(".resultat-body");
    if (body) body.scrollTop = 0;
}
function tancarModalResultat() {
    const dlg = $("#resultat-dialog");
    if (!dlg) return;
    if (typeof dlg.close === "function" && dlg.open) dlg.close();
    else { dlg.removeAttribute("open"); restaurarBackupSiCal(); }
}

function restaurarBackupSiCal() {
    if (!state.modalDesAgrupacioDesada || !state.backupAbansAgrupacio) return;
    const b = state.backupAbansAgrupacio;
    state.carregues = b.carregues;
    state.seleccio = b.seleccio;
    state.paginacio.total = b.paginacioTotal;
    state.paginacio.offset = b.paginacioOffset;
    state.filtreText = b.filtreText;
    state.backupAbansAgrupacio = null;
    state.modalDesAgrupacioDesada = false;
    state.agrupacioActualId = null;
    state.agrupacioActual = null;
    state.resultat = null;
    actualitzarBotoMagatzem();
    const filtreInput = $("#filtre-taula");
    if (filtreInput) filtreInput.value = state.filtreText || "";
    renderLlistaCarregues();
}

// ============================================================
// Render resultat (KPIs + Palets tipus + chips colorides + productes)
// ============================================================
function renderResultat(r) {
    // Assigna colors a cada càrrega
    state.colorsCarrega.clear();
    r.carregues.forEach((c, i) => {
        state.colorsCarrega.set(c.carrega_id, colorPerCarrega(c.carrega_id, i));
    });

    // Metadades de capçalera del resultat
    const desdeIso = $("#desde").value;
    const finsIso = $("#fins").value;
    const desdeFmt = desdeIso ? fmtData(desdeIso) : "—";
    const finsFmt = finsIso ? fmtData(finsIso) : "—";
    const codis = msTransportistes ? msTransportistes.getSelected() : [];
    const tra = codis.length === 0 ? "Tots" :
                codis.length <= 3 ? codis.join(", ") :
                `${codis.length} transportistes`;
    const araStr = fmtDataHora(new Date());
    const metaEl = $("#resultat-meta");
    if (metaEl) {
        metaEl.textContent = `Rang ${desdeFmt} → ${finsFmt} · Transportista: ${tra} · Generat ${araStr}`;
    }
    const printMeta = $("#print-meta");
    if (printMeta) {
        printMeta.textContent = `Informe d'agrupació · Rang ${desdeFmt} → ${finsFmt} · Transportista: ${tra} · Generat ${araStr}`;
    }

    // KPIs
    $("#kpis").innerHTML = `
        <div class="kpi"><div class="label">Càrregues</div><div class="value">${r.carregues.length}</div></div>
        <div class="kpi"><div class="label">Productes</div><div class="value">${r.productes.length}</div></div>
        <div class="kpi"><div class="label">Total sacs</div><div class="value">${fmt.format(r.total_sacs)}</div></div>
        <div class="kpi"><div class="label">Total kg</div><div class="value">${fmtKg.format(r.total_kg)}</div></div>
        <div class="kpi"><div class="label">Palets físics</div><div class="value">${fmt.format(r.total_palets_fisics)}</div></div>
    `;

    // Palets per tipus (amb desglós per càrrega colorit)
    const ulTipus = $("#palets-per-tipus");
    ulTipus.innerHTML = "";
    if (r.tipus_palets && r.tipus_palets.length > 0) {
        ulTipus.hidden = false;
        for (const t of r.tipus_palets) {
            const li = document.createElement("li");
            li.className = "palet-tipus-card";
            const dots = (t.per_carrega || []).map(pc => {
                const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096" };
                return `<span class="qt-dot" title="${escapeHtml(pc.carrega_id)}: ${pc.quantitat} palets" style="--dot-color:${col.color}">` +
                       `<span class="dot"></span><span class="dot-n">${fmt.format(pc.quantitat)}</span>` +
                       `</span>`;
            }).join("");
            li.innerHTML = `
                <div class="palet-tipus-top">
                    <span class="qt">${fmt.format(t.quantitat)}</span>
                    <span class="desc"><strong>${escapeHtml(t.tipus_palet_descrip)}</strong><br><span class="muted">${escapeHtml(t.tipus_palet)}</span></span>
                </div>
                ${dots ? `<div class="palet-tipus-dots">${dots}</div>` : ""}
            `;
            ulTipus.appendChild(li);
        }
    } else {
        ulTipus.hidden = true;
    }

    // Chips de càrregues incloses (amb color)
    const chips = $("#carregues-incloses");
    chips.innerHTML = "";
    for (const c of r.carregues) {
        const col = state.colorsCarrega.get(c.carrega_id) || { color: "#718096", bg: "#fff" };
        const ch = document.createElement("span");
        ch.className = "chip";
        ch.style.setProperty("--chip-color", col.color);
        ch.style.setProperty("--chip-bg", col.bg);
        ch.innerHTML = `<span class="chip-dot"></span><strong title="${escapeHtml(c.carrega_id)}">${escapeHtml(numCarrega(c.carrega_id))}</strong>` +
            (c.descripcio ? ` ${escapeHtml(c.descripcio)}` : "") + ` · ${escapeHtml(c.transportista || c.tra_codi)}` +
            (c.matricula ? ` · ${escapeHtml(c.matricula)}` : "");
        chips.appendChild(ch);
    }

    // Productes
    renderTaulaProductes();

    // Incidències / badge
    const inc = $("#incidencies");
    const ul = $("#llista-incidencies");
    const badge = $("#badge-incidencies");
    ul.innerHTML = "";
    if (r.incidencies.length > 0) {
        inc.hidden = false;
        $("#count-incidencies").textContent = `(${r.incidencies.length})`;
        badge.hidden = false;
        badge.className = "badge-danger";
        badge.textContent = `${r.incidencies.length} incidència${r.incidencies.length > 1 ? "s" : ""}`;
        for (const i of r.incidencies) {
            const li = document.createElement("li");
            li.className = i.tipus;
            li.innerHTML = `<strong>${escapeHtml(i.carrega_id)}</strong> ${i.comanda && i.comanda !== "-" ? `· ${escapeHtml(i.comanda)} ` : ""}— ${escapeHtml(i.missatge)}`;
            ul.appendChild(li);
        }
    } else {
        inc.hidden = true;
        badge.hidden = false;
        badge.className = "badge-success";
        badge.textContent = "Sense incidències";
    }
}

// abreviarTipusPalet i detallPaletsCarrega venen carregades des de palets.js abans d'aquest fitxer.

function productesOrdenats() {
    if (!state.resultat) return [];
    const llista = state.resultat.productes.slice();
    const { col, dir } = state.ordenacioProductes;
    if (!col) return llista;
    const sign = dir === "asc" ? 1 : -1;
    const numeric = (col === "total_sacs" || col === "total_kg");
    llista.sort((a, b) => {
        const va = a[col] ?? (numeric ? 0 : "");
        const vb = b[col] ?? (numeric ? 0 : "");
        if (numeric) return (Number(va) - Number(vb)) * sign;
        return String(va).localeCompare(String(vb), "ca", { numeric: true }) * sign;
    });
    return llista;
}

function renderTaulaProductes() {
    const tbody = $("#taula-productes tbody");
    if (!tbody) return;
    // Recorda quines files estaven expandides
    const oberts = new Set();
    tbody.querySelectorAll(".row-detall:not([hidden])").forEach(tr => oberts.add(tr.id));

    tbody.innerHTML = "";
    const llista = productesOrdenats();

    // Ordre de càrregues per índex (mateix ordre de la llegenda i KPIs)
    const ordreIdx = new Map();
    if (state.resultat) {
        state.resultat.carregues.forEach((c, i) => ordreIdx.set(c.carrega_id, i));
    }

    for (const p of llista) {
        const idRow = `prod-${escapeId(p.art_codi)}`;
        const pcOrdenats = (p.per_carrega || []).slice().sort((a, b) =>
            (ordreIdx.get(a.carrega_id) ?? 999) - (ordreIdx.get(b.carrega_id) ?? 999)
        );
        const dotsProd = pcOrdenats.map(pc => {
            const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096" };
            const detall = detallPaletsCarrega(pc);
            const tooltip = `${pc.carrega_id}${pc.transportista ? " · " + pc.transportista : ""}`;
            return `<div class="qt-dot-row" title="${escapeHtml(tooltip)}"
                          style="--dot-color:${col.color}">
                        <span class="dot"></span>
                        <span class="dot-n">${fmt.format(pc.total_sacs)}</span>
                        ${detall ? `<span class="dot-detall">(${escapeHtml(detall)})</span>` : ""}
                    </div>`;
        }).join("");
        const preparat = state.productesPreparats.has(p.art_codi);
        const tr = document.createElement("tr");
        if (preparat) tr.classList.add("row-preparat");
        const checkHTML = preparat
            ? `<span class="preparat-mark" title="Producte ja preparat al magatzem" aria-label="Preparat">✓</span>`
            : "";
        tr.innerHTML = `
            <td><button class="toggle-btn" data-target="${idRow}" aria-expanded="false">▶</button></td>
            <td>${checkHTML}<code>${escapeHtml(p.art_codi)}</code></td>
            <td>${escapeHtml(p.art_descrip)}</td>
            <td>${escapeHtml(p.tunitat)}</td>
            <td class="col-carregues-dots"><div class="col-carregues-dots-wrap">${dotsProd}</div></td>
            <td class="num"><strong>${fmt.format(p.total_sacs)}</strong></td>
            <td class="num">${fmtKg.format(p.total_kg)}</td>
        `;
        tbody.appendChild(tr);

        const detall = document.createElement("tr");
        detall.id = idRow;
        detall.className = "row-detall" + (preparat ? " row-detall-preparat" : "");
        detall.hidden = !oberts.has(idRow);
        detall.innerHTML = `<td></td><td colspan="6">${renderPerCarrega(p)}</td>`;
        tbody.appendChild(detall);

        if (oberts.has(idRow)) {
            const btn = tr.querySelector(".toggle-btn");
            btn.textContent = "▼";
            btn.setAttribute("aria-expanded", "true");
        }
    }
    tbody.querySelectorAll(".toggle-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const tgt = document.getElementById(btn.dataset.target);
            const open = !tgt.hidden;
            tgt.hidden = open;
            btn.textContent = open ? "▶" : "▼";
            btn.setAttribute("aria-expanded", String(!open));
        });
    });

    // Marca columna ordenada
    $$("#taula-productes thead th[data-sort]").forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.sort === state.ordenacioProductes.col) {
            th.classList.add(state.ordenacioProductes.dir === "asc" ? "sort-asc" : "sort-desc");
        }
    });
}

function ordenarProductesPer(col) {
    if (state.ordenacioProductes.col === col) {
        state.ordenacioProductes.dir = state.ordenacioProductes.dir === "asc" ? "desc" : "asc";
    } else {
        state.ordenacioProductes.col = col;
        // Per columnes numèriques per defecte més gran a més petit
        state.ordenacioProductes.dir = (col === "total_sacs" || col === "total_kg") ? "desc" : "asc";
    }
    guardarPrefs({ ordenacioProductes: { ...state.ordenacioProductes } });
    renderTaulaProductes();
}

function renderPerCarrega(p) {
    return p.per_carrega.map(pc => {
        const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096", bg: "#fff" };
        // Agrupar palets per (tipus_palet, sacs_x_base, sacs, comanda, det_tipo).
        // Palets idèntics de la mateixa comanda → "N × ...". Diferent comanda → línia separada.
        const agg = new Map();
        for (const pd of pc.palets) {
            const k = `${pd.tipus_palet}||${pd.sacs_x_base || 0}||${pd.sacs}||${pd.comanda || ""}||${pd.det_tipo || ""}`;
            const cur = agg.get(k) || {
                tipus_palet: pd.tipus_palet,
                tipus_descrip: pd.tipus_palet_descrip,
                sacs: pd.sacs,
                sacs_x_base: pd.sacs_x_base || 0,
                max_sacs: pd.max_sacs || 0,
                comanda: pd.comanda || "",
                det_tipo: pd.det_tipo || "",
                n: 0,
            };
            cur.n += 1;
            agg.set(k, cur);
        }
        const palets = [...agg.values()]
            .sort((a, b) => (a.comanda || "").localeCompare(b.comanda || "") || b.sacs - a.sacs)
            .map(x => {
                const baseTxt = x.sacs_x_base > 0
                    ? ` <span class="palet-base">base ${x.sacs_x_base}</span>`
                    : "";
                const pisos = x.sacs_x_base > 0 ? Math.ceil(x.sacs / x.sacs_x_base) : 0;
                const pisosTxt = pisos > 0 ? ` · ${pisos} pis${pisos > 1 ? "os" : ""}` : "";
                const comTxt = x.comanda
                    ? `<span class="palet-comanda" title="Comanda d'origen">Comanda <code>${escapeHtml(x.comanda)}</code></span>`
                    : "";
                return `<li class="palet-item" style="--palet-color:${col.color};--palet-bg:${col.bg};">
                    <span class="palet-main">${x.n} × ${escapeHtml(x.tipus_descrip || x.tipus_palet)}${baseTxt}${comTxt}</span>
                    <strong>${fmt.format(x.sacs)} sacs${pisosTxt}</strong>
                </li>`;
            })
            .join("");
        return `
            <div class="carrega-block" style="--cb-color:${col.color};--cb-bg:${col.bg};">
                <h4>
                    <span class="cb-title"><span class="cb-dot"></span><code>${escapeHtml(pc.carrega_id)}</code> · ${escapeHtml(pc.transportista || pc.tra_codi)}</span>
                    <span class="muted">${fmt.format(pc.total_sacs)} sacs · ${fmtKg.format(pc.total_kg)} kg</span>
                </h4>
                <ul class="palets-list">${palets}</ul>
            </div>
        `;
    }).join("");
}

// ============================================================
// Exportació CSV
// ============================================================
function exportarCsv() {
    if (!state.resultat) return;
    const r = state.resultat;
    const rows = [
        ["Article", "Descripció", "TUnitat", "Total sacs", "Total kg", "Càrrega", "Transportista", "Comanda", "Tipus doc", "Tipus palet", "Sacs palet", "Sacs x base", "Max sacs"],
    ];
    for (const p of r.productes) {
        for (const pc of p.per_carrega) {
            for (const pd of pc.palets) {
                rows.push([
                    p.art_codi, p.art_descrip, p.tunitat,
                    p.total_sacs, p.total_kg.toFixed(2),
                    pc.carrega_id, pc.transportista,
                    pd.comanda || "", pd.det_tipo === "P" ? "Comanda pendent" : (pd.det_tipo === "A" ? "Comanda" : ""),
                    pd.tipus_palet_descrip || pd.tipus_palet, pd.sacs,
                    pd.sacs_x_base || "", pd.max_sacs || "",
                ]);
            }
        }
    }
    // Resum global de palets per tipus
    if (r.tipus_palets && r.tipus_palets.length) {
        rows.push([]);
        rows.push(["Resum palets físics per tipus"]);
        rows.push(["Tipus palet", "Descripció", "Quantitat"]);
        for (const t of r.tipus_palets) {
            rows.push([t.tipus_palet, t.tipus_palet_descrip, t.quantitat]);
        }
    }
    const csv = rows.map(r => r.map(csvCell).join(";")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `agrupacio_${fmtData(new Date())}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    showToast("info", "CSV descarregat", `${a.download}`);
}
function csvCell(v) {
    const s = String(v ?? "");
    if (/[;"\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
}

// ============================================================
// Ordenació de columnes
// ============================================================
function ordenarPer(col) {
    if (state.ordenacio.col === col) {
        state.ordenacio.dir = state.ordenacio.dir === "asc" ? "desc" : "asc";
    } else {
        state.ordenacio.col = col;
        state.ordenacio.dir = "asc";
    }
    guardarPrefs({ ordenacio: { ...state.ordenacio } });
    renderLlistaCarregues();
}

// ============================================================
// Dreceres de teclat
// ============================================================
function setupKeyboard() {
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            tancaTotsToasts();
            if (state.abortCerca) state.abortCerca.abort();
            if (state.abortAgrupar) state.abortAgrupar.abort();
            const dlgRes = $("#resultat-dialog");
            if (dlgRes && dlgRes.open) dlgRes.close();
            return;
        }
        if (e.ctrlKey && (e.key === "a" || e.key === "A")) {
            const inField = e.target.closest("input,textarea,select");
            if (inField) return;
            if (!$("#seccio-llista").hidden && state.carregues.length > 0) {
                e.preventDefault();
                marcarTotes(true);
            }
        }
    });
}

// ============================================================
// Bootstrap
// ============================================================
async function comprovaHealth() {
    try {
        const resp = await fetch("/health");
        const data = await resp.json();
        if (!data.db?.ok) {
            showToast("warning", "Base de dades no disponible",
                "La connexió SQL no respon. Algunes funcions poden fallar.");
        }
        if (!data.motor?.ok) {
            showToast("warning", "Motor d'embalatges no disponible",
                "L'agrupació no funcionarà fins que es restableixi.");
        }
    } catch (_) {
        // Si /health falla, el servidor està caigut; ja es manifestarà en la propera petició.
    }
}

// ============================================================
// Filtres avançats: estats + autocompletar articles
// ============================================================
async function carregarEstats() {
    try {
        const llista = await fetchJson("/api/estats-carregues");
        const cont = $("#estats-chips");
        if (!cont) return;
        cont.innerHTML = "";
        const totsBtn = document.createElement("button");
        totsBtn.type = "button";
        totsBtn.className = "chip-toggle active";
        totsBtn.dataset.estat = "";
        totsBtn.textContent = "Tots";
        cont.appendChild(totsBtn);
        for (const e of llista) {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "chip-toggle";
            b.dataset.estat = String(e.estat ?? "");
            b.innerHTML = `Estat ${e.estat} <span class="n">${fmt.format(e.n)}</span>`;
            cont.appendChild(b);
        }
        cont.addEventListener("click", (ev) => {
            const b = ev.target.closest(".chip-toggle");
            if (!b) return;
            $$("#estats-chips .chip-toggle").forEach(x => x.classList.remove("active"));
            b.classList.add("active");
            const v = b.dataset.estat;
            state.filtresAvancats.estat = v === "" ? null : Number(v);
            guardarPrefs({ filtresAvancats: { ...state.filtresAvancats } });
            buscarCarregues();
        });
    } catch (_) {
        // Si falla, els filtres avançats queden sense estats; no és crític.
    }
}

let _autocompTimer = null;
function setupAutocompleteArticle() {
    const inp = $("#filtre-article");
    const ul = $("#filtre-article-suggs");
    const sel = $("#filtre-article-sel");
    if (!inp || !ul) return;

    const triar = (codi, descrip) => {
        state.filtresAvancats.art_codi = codi;
        state.filtresAvancats.art_descrip = descrip || "";
        if (sel) {
            sel.hidden = false;
            sel.innerHTML = `Filtrant per <code>${escapeHtml(codi)}</code> — ${escapeHtml(descrip)} <a href="#" id="art-clear" style="margin-left:.4rem">[×]</a>`;
            $("#art-clear")?.addEventListener("click", (ev) => {
                ev.preventDefault();
                state.filtresAvancats.art_codi = null;
                state.filtresAvancats.art_descrip = "";
                sel.hidden = true;
                inp.value = "";
                guardarPrefs({ filtresAvancats: { ...state.filtresAvancats } });
                buscarCarregues();
            });
        }
        inp.value = "";
        ul.hidden = true;
        ul.innerHTML = "";
        guardarPrefs({ filtresAvancats: { ...state.filtresAvancats } });
        buscarCarregues();
    };

    inp.addEventListener("input", () => {
        const q = inp.value.trim();
        clearTimeout(_autocompTimer);
        if (q.length < 2) {
            ul.hidden = true; ul.innerHTML = "";
            return;
        }
        _autocompTimer = setTimeout(async () => {
            try {
                const llista = await fetchJson(`/api/articles?q=${encodeURIComponent(q)}`);
                ul.innerHTML = "";
                if (!llista.length) {
                    ul.hidden = true;
                    return;
                }
                for (const a of llista) {
                    const li = document.createElement("li");
                    li.innerHTML = `<code>${escapeHtml(a.art_codi)}</code> ${escapeHtml(a.art_descrip)}`;
                    li.addEventListener("click", () => triar(a.art_codi, a.art_descrip));
                    ul.appendChild(li);
                }
                ul.hidden = false;
            } catch { ul.hidden = true; }
        }, 200);
    });
    document.addEventListener("click", (ev) => {
        if (!ev.target.closest(".autocomplete")) {
            ul.hidden = true;
        }
    });
}

// ============================================================
// Agrupacions desades
// ============================================================
// En agrupar, l'agrupació es desa sola amb un nom automàtic. Retorna el nom,
// o null si no s'ha pogut desar (aleshores el botó "Desa" ho deixa fer a mà).
async function desarAutomatic(carregues, resultat) {
    const nom = `Agrupació ${fmtDataHora(new Date())}`;
    try {
        const info = await fetchJson("/api/agrupacions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nom, carregues, resultat, plantilla: false }),
        });
        if (state.resultat !== resultat || !info?.id) return null;   // ja se n'ha fet una altra
        state.agrupacioActualId = info.id;
        state.agrupacioActual = { nom: info.nom || nom, plantilla: false };
        actualitzarBotoMagatzem();
        return state.agrupacioActual.nom;
    } catch (e) {
        showToast("warning", "No s'ha pogut desar", `${e.message}. Prem "Desa" per tornar-ho a provar.`);
        return null;
    }
}

// Ja desada: canvia el nom i la marca de plantilla.
async function reanomenarAgrupacioActual() {
    const actual = state.agrupacioActual || { nom: "", plantilla: false };
    const resp = await window.mostrarInput({
        titol: "Nom de l'agrupació",
        etiqueta: "Nom de l'agrupació",
        defecte: actual.nom,
        placeholder: "Ex: Càrregues dilluns matí",
        btnOk: "Desa",
        checkbox: {
            label: "⭐ Plantilla recurrent (l'app suggerirà aplicar-la quan trobi càrregues similars)",
            checked: actual.plantilla,
            tooltip: "Marca-ho si aquesta agrupació es repeteix sovint amb els mateixos transportistes",
        },
    });
    if (resp === null) return;
    const nom = (resp.valor || "").trim();
    if (!nom) {
        showToast("warning", "Cal un nom", "Posa un nom per identificar l'agrupació.");
        return;
    }
    const plantilla = !!resp.marcat;
    try {
        const info = await fetchJson(`/api/agrupacions/${encodeURIComponent(state.agrupacioActualId)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nom, plantilla }),
        });
        state.agrupacioActual = { nom: info.nom, plantilla: info.plantilla };
        showToast("success", "Agrupació actualitzada",
            plantilla ? `"${info.nom}" és una plantilla recurrent.` : `Ara es diu "${info.nom}".`);
        if (plantilla !== actual.plantilla) await carregarPlantilles();
    } catch (e) {
        showToast("error", "Error desant", e.message);
    }
}

async function desarAgrupacioActual() {
    if (!state.resultat) return;
    if (state.agrupacioActualId) return reanomenarAgrupacioActual();
    const resp = await window.mostrarInput({
        titol: "Desa l'agrupació",
        etiqueta: "Nom de l'agrupació",
        defecte: `Agrupació ${fmtDataHora(new Date())}`,
        placeholder: "Ex: Càrregues dilluns matí",
        btnOk: "Desa",
        checkbox: {
            label: "⭐ Plantilla recurrent (l'app suggerirà aplicar-la quan trobi càrregues similars)",
            checked: false,
            tooltip: "Marca-ho si aquesta agrupació es repeteix sovint amb els mateixos transportistes",
        },
    });
    if (resp === null) return;
    const nom = (resp.valor || "").trim();
    if (!nom) {
        showToast("warning", "Cal un nom", "Posa un nom per identificar l'agrupació.");
        return;
    }
    const plantilla = !!resp.marcat;
    const carregues = state.carregues.filter(c => state.seleccio.has(c.carrega_id));
    try {
        const info = await fetchJson("/api/agrupacions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nom, carregues, resultat: state.resultat, plantilla }),
        });
        state.agrupacioActualId = info?.id || null;
        state.agrupacioActual = info?.id ? { nom: info.nom || nom, plantilla } : null;
        actualitzarBotoMagatzem();
        showToast("success", "Agrupació desada",
            plantilla ? `"${nom}" guardada com a plantilla recurrent.` : `"${nom}" guardada correctament.`);
        // Refresca plantilles per al banner de suggeriment
        if (plantilla) await carregarPlantilles();
    } catch (e) {
        showToast("error", "Error desant", e.message);
    }
}

async function carregarAgrupacioDesada(id) {
    try {
        const obj = await fetchJson(`/api/agrupacions/${encodeURIComponent(id)}`);
        // Guardem l'estat de la cerca actual perquè en tancar el modal
        // l'usuari torni a veure-la tal com l'havia deixat (no afectada
        // per haver mirat una agrupació desada).
        state.backupAbansAgrupacio = {
            carregues: state.carregues,
            seleccio: new Set(state.seleccio),
            paginacioTotal: state.paginacio.total,
            paginacioOffset: state.paginacio.offset,
            filtreText: state.filtreText,
        };
        state.modalDesAgrupacioDesada = true;
        state.carregues = obj.carregues || [];
        state.seleccio = new Set(state.carregues.map(c => c.carrega_id));
        state.resultat = obj.resultat;
        state.productesPreparats = new Set(obj.productes_preparats || []);
        state.agrupacioActualId = id;
        state.agrupacioActual = { nom: obj.nom || "", plantilla: !!obj.plantilla };
        renderLlistaCarregues();
        renderResultat(state.resultat);
        actualitzarBotoMagatzem();
        obrirModalResultat();
        showToast("info", "Agrupació recuperada", obj.nom);
    } catch (e) {
        showToast("error", "Error carregant l'agrupació", e.message);
    }
}

// ============================================================
// Plantilles d'agrupació recurrents
// ============================================================
async function carregarPlantilles() {
    try {
        state.plantilles = await fetchJson("/api/plantilles");
    } catch {
        state.plantilles = [];
    }
}

function carregaCompatible(carrega, plantilla) {
    const codis = new Set((plantilla.transportistes || []).map(t => t.tra_codi));
    return codis.has((carrega.tra_codi || "").trim());
}

function actualitzarBannerPlantilles() {
    const banner = $("#plantilles-banner");
    if (!banner) return;
    if (!state.plantilles.length || !state.carregues.length) {
        banner.innerHTML = "";
        banner.hidden = true;
        return;
    }
    const suggeriments = [];
    for (const p of state.plantilles) {
        if (state.plantillesTancades.has(p.id)) continue;
        const compatibles = state.carregues.filter(c => carregaCompatible(c, p));
        if (compatibles.length >= PLANTILLA_MIN_COMPATIBLES) {
            suggeriments.push({ plantilla: p, compatibles });
        }
    }
    if (!suggeriments.length) {
        banner.innerHTML = "";
        banner.hidden = true;
        return;
    }
    // Render màxim 3 suggeriments
    banner.innerHTML = suggeriments.slice(0, 3).map(s => {
        const tras = (s.plantilla.transportistes || []).map(t => t.tra_nom || t.tra_codi).join(", ");
        return `
            <div class="plantilla-suggeriment" data-plantilla-id="${escapeHtml(s.plantilla.id)}">
                <span class="icon" aria-hidden="true">💡</span>
                <div class="text">
                    Hi ha <strong>${s.compatibles.length}</strong> càrregues que encaixen amb la plantilla
                    <strong>${escapeHtml(s.plantilla.nom)}</strong>.
                    <span class="meta">${escapeHtml(tras)}</span>
                </div>
                <div class="actions">
                    <button type="button" class="btn-aplicar" data-act="aplicar">Aplicar</button>
                    <button type="button" class="btn-tanca" data-act="tancar" aria-label="Tancar suggeriment">×</button>
                </div>
            </div>
        `;
    }).join("");
    banner.hidden = false;
}

function aplicarPlantilla(plantillaId) {
    const p = state.plantilles.find(x => x.id === plantillaId);
    if (!p) return;
    const compatibles = state.carregues.filter(c => carregaCompatible(c, p));
    if (!compatibles.length) {
        showToast("warning", "Sense compatibles", "Cap càrrega encaixa amb aquesta plantilla.");
        return;
    }
    // Pre-selecciona les compatibles (afegeix a la selecció actual, no la reemplaça)
    let afegides = 0;
    for (const c of compatibles) {
        // No seleccionar les ja agrupades (bloquejades)
        if (estatAgrupacio(c) != null) continue;
        if (!state.seleccio.has(c.carrega_id)) {
            state.seleccio.add(c.carrega_id);
            afegides++;
        }
    }
    renderLlistaCarregues();
    showToast("success", "Plantilla aplicada",
        `${afegides} càrrega${afegides === 1 ? "" : "s"} seleccionada${afegides === 1 ? "" : "s"} de la plantilla "${p.nom}".`);
    // Amaga el banner per a aquesta sessió
    state.plantillesTancades.add(plantillaId);
    actualitzarBannerPlantilles();
}

// ============================================================
// Resize de columnes a la taula de càrregues
// ============================================================
const COL_WIDTHS_DEFAULT = {
    "carrega_id": 170,
    "car_descripcion": 180,
    "car_fecsalida": 145,
    "transportista": 180,
    "car_matricula": 110,
    "car_observaciones": 220,
    "agrupacio_nom": 220,
};

function setupColumnResize() {
    const table = $("#taula-carregues");
    if (!table) return;
    table.classList.add("is-resizable");

    const prefs = carregarPrefs();
    const saved = prefs.colWidths || {};
    const ths = $$("thead th", table);
    for (const th of ths) {
        const col = th.dataset.col;
        if (!col) continue;
        const w = saved[col] || COL_WIDTHS_DEFAULT[col];
        if (w) th.style.width = w + "px";
        if (col === "check" || col === "expand") continue;
        const handle = document.createElement("span");
        handle.className = "th-resizer";
        handle.addEventListener("mousedown", (e) => iniciaResizeColumna(e, th));
        // Evita que el click al handle dispari l'ordenació
        handle.addEventListener("click", (e) => e.stopPropagation());
        th.appendChild(handle);
    }
}

function restablirAmpladesColumnes() {
    const table = $("#taula-carregues");
    if (!table) return;
    // Esborra preferència desada
    const cur = carregarPrefs();
    delete cur.colWidths;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cur)); } catch {}
    // Reaplica amplades per defecte
    for (const th of $$("thead th", table)) {
        const col = th.dataset.col;
        if (!col) continue;
        const w = COL_WIDTHS_DEFAULT[col];
        if (w) th.style.width = w + "px";
        else th.style.width = "";
    }
    showToast("info", "Amplades restablertes", "Les columnes han tornat a la seva mida per defecte.");
}

function iniciaResizeColumna(ev, th) {
    ev.preventDefault();
    ev.stopPropagation();
    const startX = ev.clientX;
    const startW = th.getBoundingClientRect().width;
    const col = th.dataset.col;
    const handle = th.querySelector(".th-resizer");
    document.body.classList.add("is-resizing-col");
    handle?.classList.add("is-active");

    const move = (e) => {
        const w = Math.max(40, Math.round(startW + (e.clientX - startX)));
        th.style.width = w + "px";
    };
    const up = () => {
        document.body.classList.remove("is-resizing-col");
        handle?.classList.remove("is-active");
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        const w = parseInt(th.style.width, 10);
        if (col && w) {
            const cur = carregarPrefs();
            const colWidths = { ...(cur.colWidths || {}), [col]: w };
            guardarPrefs({ colWidths });
        }
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
}

function netejaFiltresAvancats() {
    state.filtresAvancats = { estat: null, art_codi: null, art_descrip: "" };
    guardarPrefs({ filtresAvancats: { ...state.filtresAvancats } });
    // Reset UI
    $$("#estats-chips .chip-toggle").forEach((b, i) => {
        b.classList.toggle("active", i === 0);
    });
    const inp = $("#filtre-article"); if (inp) inp.value = "";
    const sel = $("#filtre-article-sel"); if (sel) sel.hidden = true;
    buscarCarregues();
}

// ============================================================
// Polling lleuger de canvis a les agrupacions
// El backend manté un comptador (version) que s'incrementa cada cop que
// algú desa/elimina una agrupació o marca/desmarca un producte. Cada 5s
// preguntem aquesta versió; si ha canviat, refresquem la llista visible
// sense reiniciar selecció, filtres, scroll ni dialogs oberts.
// ============================================================
async function comprovaVersionAgrupacions() {
    if (document.hidden) return;
    // Evitem refrescos enmig d'un dialog/modal obert (no interrompre l'usuari)
    if (document.querySelector("dialog[open]")) return;
    if (state.agrupacionsRefreshInFlight) return;
    try {
        const r = await fetch("/api/agrupacions/version", { credentials: "same-origin" });
        if (!r.ok) return;
        const data = await r.json();
        const v = data && data.v;
        if (typeof v !== "number") return;
        if (state.agrupacionsVersion === null) {
            // Primer poll: només memoritzem el valor inicial
            state.agrupacionsVersion = v;
            console.log("[poll] versió inicial:", v);
            return;
        }
        if (v !== state.agrupacionsVersion) {
            console.log("[poll] canvi detectat:", state.agrupacionsVersion, "→", v, "— refrescant llista");
            state.agrupacionsVersion = v;
            await refrescarLlistaSilenciosament();
            console.log("[poll] refresc completat");
        }
    } catch { /* silent — el polling reintenta al següent tick */ }
}

async function refrescarLlistaSilenciosament() {
    // Només si l'usuari ja ha buscat algun cop
    if (!state.carregues || state.carregues.length === 0) return;
    const desde = $("#desde")?.value;
    const fins = $("#fins")?.value;
    if (!desde || !fins) return;
    const traCodis = msTransportistes ? msTransportistes.getSelected() : [];

    state.agrupacionsRefreshInFlight = true;
    try {
        const params = new URLSearchParams({
            desde, fins,
            limit: String(Math.max(state.carregues.length, state.paginacio.limit)),
            offset: "0",
        });
        for (const c of traCodis) params.append("tra_codi", c);
        const { estat, art_codi } = state.filtresAvancats;
        if (estat !== null && estat !== undefined && estat !== "") params.set("estat", String(estat));
        if (art_codi) params.set("art_codi", art_codi);
        const resp = await fetchJson(`/api/carregues?${params}`);
        const items = Array.isArray(resp) ? resp : resp.items;
        const total = Array.isArray(resp) ? items.length : resp.total;
        // Conservem la selecció (només per als carrega_id que continuen presents)
        const idsActuals = new Set(items.map(c => c.carrega_id));
        for (const id of [...state.seleccio]) {
            if (!idsActuals.has(id)) state.seleccio.delete(id);
        }
        state.carregues = items;
        state.paginacio.total = total;
        state.paginacio.offset = items.length;
        renderLlistaCarregues();
        actualitzarBannerPlantilles();
        refrescaPistolejat();
        // Refresc silenciós — l'usuari veu només el canvi de color/estat
        // a les files afectades (groc → ambar → verd).
    } catch { /* silent */ }
    finally {
        state.agrupacionsRefreshInFlight = false;
    }
}

// % pistolejat de les càrregues pendents de la llista. Va a SAP (el servidor
// ho reaprofita uns segons), així que no frena la cerca: es pinta quan arriba.
async function refrescaPistolejat() {
    if (state.pistolejatInFlight || document.hidden) return;
    const ids = [...new Set(state.carregues
        .filter(c => c.car_estat === 1 && /^\d+$/.test(String(c.car_numero)))
        .map(c => String(c.car_numero)))].slice(0, PISTOLEJAT_MAX_IDS);
    if (!ids.length) return;
    state.pistolejatInFlight = true;
    try {
        const j = await fetchJson(`/api/pistolejat/carregues?ids=${ids.join(",")}`);
        const nou = new Map(Object.entries(j.carregues || {}));
        const canvia = nou.size !== state.pistolejat.size ||
            [...nou].some(([k, v]) => {
                const a = state.pistolejat.get(k);
                return !a || a.estat !== v.estat || a.percent !== v.percent;
            });
        state.pistolejat = nou;
        if (canvia) renderLlistaCarregues();
    } catch { /* informatiu: si SAP no respon, la llista funciona igual */ }
    finally {
        state.pistolejatInFlight = false;
    }
}

function iniciaPollingAgrupacions() {
    if (state.agrupacionsPollId) clearInterval(state.agrupacionsPollId);
    state.agrupacionsPollId = setInterval(comprovaVersionAgrupacions, 5000);
    // El pistolejat no mou la versió de les agrupacions (i hi ha càrregues
    // sense agrupar): es llegeix a part, cada 30 s amb la pestanya visible.
    setInterval(refrescaPistolejat, PISTOLEJAT_POLL_MS);
    // Primera comprovació immediata per inicialitzar la versió de referència
    setTimeout(comprovaVersionAgrupacions, 300);
    // En tornar a la pestanya, comprovem un cop de seguida (sense esperar 5s)
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) { comprovaVersionAgrupacions(); refrescaPistolejat(); }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    // Polling de canvis a les agrupacions: el cridem al principi per
    // assegurar que arrenca encara que alguna inicialització posterior
    // llanci una excepció.
    try { iniciaPollingAgrupacions(); } catch (e) { console.error("Polling init error:", e); }

    const prefs = carregarPrefs();
    if (prefs.desde) $("#desde").value = prefs.desde;
    if (prefs.fins) $("#fins").value = prefs.fins;
    if (prefs.ordenacio && prefs.ordenacio.col) {
        state.ordenacio = { ...prefs.ordenacio };
    }
    if (prefs.ordenacioProductes && prefs.ordenacioProductes.col) {
        state.ordenacioProductes = { ...prefs.ordenacioProductes };
    }

    comprovaHealth();
    carregarTransportistes();
    carregarPlantilles();
    setupColumnResize();

    // Click delegation al banner de plantilles
    const banner = $("#plantilles-banner");
    if (banner) {
        banner.addEventListener("click", (ev) => {
            const sug = ev.target.closest(".plantilla-suggeriment");
            if (!sug) return;
            const id = sug.dataset.plantillaId;
            if (ev.target.closest('[data-act="aplicar"]')) {
                aplicarPlantilla(id);
            } else if (ev.target.closest('[data-act="tancar"]')) {
                state.plantillesTancades.add(id);
                actualitzarBannerPlantilles();
            }
        });
    }
    // Filtres ràpids
    $$(".chip-btn").forEach(b => {
        b.addEventListener("click", () => aplicaFiltreRapid(b.dataset.range));
    });

    // Validació viva
    $("#desde").addEventListener("input", validarFormulari);
    $("#fins").addEventListener("input", validarFormulari);
    validarFormulari();

    // Formulari
    $("#form-filtres").addEventListener("submit", (e) => {
        e.preventDefault();
        buscarCarregues();
    });

    // Botó "Carrega'n més" (paginació)
    const btnMes = $("#btn-carrega-mes");
    if (btnMes) btnMes.addEventListener("click", () => buscarCarregues(true));

    // Event delegation al tbody de càrregues (substitueix listeners individuals per fila)
    const tbCarregues = $("#taula-carregues tbody");
    if (tbCarregues) {
        tbCarregues.addEventListener("click", (ev) => {
            const tr = ev.target.closest("tr[data-carrega-id]");
            if (!tr) return;
            const carregaId = tr.dataset.carregaId;
            const idx = +tr.dataset.idx;
            const carrega = state.carregues.find(c => c.carrega_id === carregaId);
            if (!carrega) return;
            // Badge / cel·la "Agrupació": obre el modal Resultat amb l'agrupació desada
            const btnAgrup = ev.target.closest('[data-act="obrir-agrupacio"]');
            if (btnAgrup) {
                ev.stopPropagation();
                const id = btnAgrup.dataset.id;
                if (id) carregarAgrupacioDesada(id);
                return;
            }
            const cb = ev.target.closest('input[data-role="carrega-check"]');
            const btnExp = ev.target.closest('button[data-role="carrega-expand"]');
            if (cb) {
                ev.stopPropagation();
                gestionaSeleccio(carregaId, idx, ev.shiftKey, cb.checked);
                return;
            }
            if (btnExp) {
                ev.stopPropagation();
                toggleDetallCarrega(carrega, tr, btnExp);
                return;
            }
            if (ev.target.closest("input,button,a,code")) return;
            gestionaSeleccio(carregaId, idx, ev.shiftKey, !state.seleccio.has(carregaId));
        });
    }

    // Botons selecció / agrupar
    $("#check-all").addEventListener("change", (e) => marcarTotes(e.target.checked));
    $("#btn-agrupar").addEventListener("click", agrupar);
    $("#btn-etiquetes")?.addEventListener("click", obrirEtiquetes);
    $("#btn-desselecciona").addEventListener("click", () => marcarTotes(false));
    $("#btn-exportar-csv").addEventListener("click", exportarCsv);
    $("#btn-imprimir").addEventListener("click", imprimirInforme);
    $("#btn-desar-agrupacio")?.addEventListener("click", desarAgrupacioActual);
    $("#btn-tanca-resultat").addEventListener("click", tancarModalResultat);

    // Tancar modal en clicar fora
    const dlgRes = $("#resultat-dialog");
    if (dlgRes) {
        dlgRes.addEventListener("click", (e) => {
            const rect = dlgRes.querySelector("#seccio-resultat").getBoundingClientRect();
            if (e.clientX < rect.left || e.clientX > rect.right ||
                e.clientY < rect.top || e.clientY > rect.bottom) {
                tancarModalResultat();
            }
        });
        // Qualsevol forma de tancament (X, Esc, clic fora, programàtic):
        // restaura la cerca prèvia si vam obrir el modal des d'una agrupació
        // desada. Es dispara una sola vegada per cada close natiu.
        dlgRes.addEventListener("close", restaurarBackupSiCal);
    }

    // Filtre live taula
    const filtreInput = $("#filtre-taula");
    const aplicaFiltre = debounce(() => {
        state.filtreText = filtreInput.value.trim();
        renderLlistaCarregues();
    }, 150);
    filtreInput.addEventListener("input", aplicaFiltre);

    // Toggle "Amaga no-palletitzables" — persistit a localStorage.
    // Posa la classe `hide-not-palletitzable` a la secció del llistat;
    // el CSS s'encarrega d'amagar tant files (TR) com línies de detall.
    const toggleNP = $("#toggle-amaga-no-palletitzables");
    const seccioLlista = $("#seccio-llista");
    if (toggleNP && seccioLlista) {
        const TOGGLE_KEY = "agrupacio_amaga_no_palletitzables";
        try { toggleNP.checked = localStorage.getItem(TOGGLE_KEY) === "1"; } catch (e) {}
        const aplicaToggleNP = () => {
            seccioLlista.classList.toggle("hide-not-palletitzable", toggleNP.checked);
            try { localStorage.setItem(TOGGLE_KEY, toggleNP.checked ? "1" : "0"); } catch (e) {}
        };
        aplicaToggleNP();
        toggleNP.addEventListener("change", aplicaToggleNP);
    }

    // Ordenació amb suport teclat
    const sortable = (sel, fn) => {
        $$(sel).forEach(th => {
            th.setAttribute("role", "button");
            th.setAttribute("tabindex", "0");
            th.addEventListener("click", () => fn(th.dataset.sort));
            th.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    fn(th.dataset.sort);
                }
            });
        });
    };
    sortable("#taula-carregues thead th[data-sort]", ordenarPer);
    sortable("#taula-productes thead th[data-sort]", ordenarProductesPer);

    // Empty state - ampliar setmana
    const btnAmplia = $("#btn-amplia-setmana");
    if (btnAmplia) btnAmplia.addEventListener("click", () => aplicaFiltreRapid("last-week"));

    // El botó '?' del header és un enllaç directe a /ajuda; cap handler JS necessari.
    $("#btn-reset-amplades")?.addEventListener("click", restablirAmpladesColumnes);

    setupKeyboard();

    // Auto-cerca en obrir: les dates ja venen posades (del servidor o de
    // l'última cerca), i un peó no ha de saber que encara cal prémer Cerca.
    // "Reimprimir" de Gestió d'agrupacions porta aquí amb ?agrupacio=<id>:
    // primer la cerca de sempre i després el resultat d'aquella agrupació, de
    // manera que en tancar-lo es torna a la llista de càrregues normal.
    const agrupacioEnllac = new URLSearchParams(location.search).get("agrupacio");
    if (agrupacioEnllac) history.replaceState(null, "", location.pathname);
    if (validarFormulari()) {
        // petit retard perquè es vegi la UI inicial
        setTimeout(async () => {
            await buscarCarregues();
            if (agrupacioEnllac) carregarAgrupacioDesada(agrupacioEnllac);
        }, 100);
    } else if (agrupacioEnllac) {
        carregarAgrupacioDesada(agrupacioEnllac);
    }

    // Eines de depuració en localhost (no exposem a producció)
    if (location.hostname === "127.0.0.1" || location.hostname === "localhost") {
        window.__app = { state, comprovaVersionAgrupacions, refrescarLlistaSilenciosament };
    }
});

})();
