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

// El mateix llenguatge de progrés a totes les pantalles: primer el % de kg
// pistolejats per l'SGA, després els productes fets. `pct` és null si
// l'agrupació encara no s'ha sincronitzat mai amb el pistolejat.
function textProgres(pct, fets, total) {
    const prod = `${fets} de ${total} productes fets`;
    return pct == null ? prod : `${pct}% pistolejat · ${prod}`;
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

// ---- Vista LLISTA ------------------------------------------------------
const _isAcabada = (it) => (it.n_productes || 0) > 0 && (it.n_preparats || 0) >= (it.n_productes || 0);
const _isTancada = (it) => !!it.finalitzada_manual_at;
const _isFinalitzada = (it) => _isTancada(it) || _isAcabada(it);

function _pintaLlistaItems(items) {
    const ul = $m("#mag-llista");
    ul.innerHTML = "";
    for (const it of items) {
        const li = document.createElement("li");
        const tancada = _isTancada(it);
        const acabada = !tancada && _isAcabada(it);
        const finalitzada = tancada || acabada;
        let badge = "";
        if (tancada) badge = '<span class="badge-tancada">TANCADA</span>';
        else if (acabada) badge = '<span class="badge-acabada">ACABADA</span>';
        const creador = it.created_by_nom
            ? `<span class="mag-llista-creador">· ${escapeM(it.created_by_nom)}</span>`
            : "";
        li.innerHTML = `
            <a href="/magatzem/${encodeURIComponent(it.id)}" class="${finalitzada ? "is-acabada" : ""}">
                <div class="nom">
                    ${escapeM(it.nom)}
                    ${badge}
                </div>
                <div class="meta">
                    ${escapeM(fmtData(it.ts))} ${creador} · ${it.n_carregues} càrregues · ${it.n_productes} productes · ${fmtN.format(it.total_palets_fisics)} palets
                </div>
                <div class="meta progres">${textProgres(it.pct_pistolejat, it.n_preparats || 0, it.n_productes || 0)}</div>
            </a>`;
        ul.appendChild(li);
    }
}

window.magatzemLlista = async function magatzemLlista() {
    let items = [];
    try {
        items = await fetchJ("/api/agrupacions");
    } catch (e) {
        toast("error", "No s'ha pogut carregar el llistat: " + e.message);
        return;
    }
    const buit = $m("#mag-buit");
    const totesAcabades = $m("#mag-totes-acabades");
    const bar = $m("#mag-llista-bar");
    const countEl = $m("#mag-acabades-count");
    const toggle = $m("#mag-mostra-acabades");

    if (!items.length) {
        buit.hidden = false;
        bar.hidden = true;
        return;
    }

    const finalitzades = items.filter(_isFinalitzada);
    const obertes = items.filter(it => !_isFinalitzada(it));

    // Sempre mostrem la barra amb el comptador (per recuperar les finalitzades)
    bar.hidden = false;
    countEl.textContent = finalitzades.length;

    const refresca = () => {
        const mostrar = toggle.checked;
        const llista = mostrar ? items : obertes;
        if (llista.length === 0) {
            $m("#mag-llista").innerHTML = "";
            buit.hidden = true;
            // Si totes són finalitzades i no es mostren, ho indiquem
            totesAcabades.hidden = !(finalitzades.length > 0);
        } else {
            totesAcabades.hidden = true;
            buit.hidden = true;
            _pintaLlistaItems(llista);
        }
    };

    toggle.addEventListener("change", refresca);
    refresca();
};

// ---- Vista PREPARACIÓ --------------------------------------------------
// Només lectura: el que està fet ho diu el pistolejat de l'SGA
// (/api/agrupacions/<id>/pistolejat), no l'operari. Vegeu preparacio_sga.py.
let magState = {
    id: null,
    obj: null,
    progres: null,           // resposta de /pistolejat (null fins a la primera)
    ocultarPrep: false,
    colorsCarrega: new Map(),
    pollTimer: null,
    lastAcabada: null,       // si estava tota feta al darrer render (null = abans del primer)
};

// Cada refresc va a SAP: cada 15 s n'hi ha prou (com a "Pendents del dia").
const POLL_PREP_MS = 15_000;

const ETIQUETA_ESTAT_PREP = {
    pendent: "Pendent", parcial: "A mitges", complet: "Fet", sense_dades: "Sense dades a SAP",
};

function colorPerCarregaIdx(i) {
    return PALETA_MAG[i % PALETA_MAG.length];
}

function progresDe(artCodi) {
    return magState.progres?.productes?.[artCodi] || null;
}

// Els fets els decideix el servidor: inclou els "sense dades a SAP" (vegeu
// dades/pistolejat.py:progres_agrupacio).
function esFet(artCodi) {
    return (magState.progres?.fets || []).includes(artCodi);
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
    const total = (magState.obj?.resultat?.productes || []).length;
    const fets = magState.progres ? magState.progres.n_fets : 0;
    const pct = magState.progres ? magState.progres.percent : 0;
    // El número gran és el % pistolejat (el que omple la barra); a sota, els
    // productes fets. Abans "0 / 3 fets" sobre una barra al 35% es contradeien.
    $m("#mag-progres-pct").textContent = magState.progres ? `${pct}%` : "—";
    $m("#mag-progres-sub").textContent = magState.progres
        ? textProgres(null, fets, total) : "";
    const fill = $m("#mag-progres-fill");
    if (fill) fill.style.width = `${pct}%`;
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
        toast("success", `Agrupació completada — ${total} productes pistolejats`);
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
    // Ordre: pendents primer (ordenats per total_sacs desc), fets al final
    prods.sort((a, b) => {
        const pa = esFet(a.art_codi) ? 1 : 0;
        const pb = esFet(b.art_codi) ? 1 : 0;
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
        const isFet = esFet(p.art_codi);
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
                    <span class="mag-pist-text">Pistolejat: ${escapeM(textPistolejat(pr))}</span>
                    <div class="pend-barra"><div class="pend-barra-fill" style="width:${pr.percent}%"></div></div>
                </div>`;
        }
        let prepMetaHtml = "";
        if (isFet) {
            const d = (magState.obj?.preparats_detall || {})[p.art_codi] || {};
            const txt = [d.per_nom || "SGA", fmtHoraCurta(d.ts)].filter(Boolean).join(" · ");
            prepMetaHtml = `<div class="mag-prep-meta">✓ ${escapeM(txt)}</div>`;
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
                ${prepMetaHtml}
            </div>
            <div class="mag-estat-col">
                ${estat}
                <span class="mag-prep-check" aria-hidden="true"></span>
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
        // Primer el pistolejat (que de pas desa els fets) i després
        // l'agrupació, perquè l'hora "✓ SGA · hh:mm" ja vingui actualitzada.
        const progres = await fetchJ(`/api/agrupacions/${id}/pistolejat`).catch(e => ({ _error: e }));
        magState.obj = await fetchJ(`/api/agrupacions/${id}`);
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

window.magatzemPrep = async function magatzemPrep(id) {
    magState.id = id;
    await refrescar();

    // Toggle "amaga els fets"
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
