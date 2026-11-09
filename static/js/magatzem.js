// Mode magatzem — UI tàctil per al preparador.

const $m = (sel, r = document) => r.querySelector(sel);
const $mAll = (sel, r = document) => Array.from(r.querySelectorAll(sel));
const fmtN = new Intl.NumberFormat("ca-ES");
const fmtKgN = new Intl.NumberFormat("ca-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Mateixa paleta que l'app principal perquè els colors coincideixin
const PALETA_MAG = [
    { color: "#1f77b4", bg: "#e8f0f7" }, { color: "#ff7f0e", bg: "#fff0db" },
    { color: "#2ca02c", bg: "#e8f5e6" }, { color: "#d62728", bg: "#fce6e6" },
    { color: "#9467bd", bg: "#f1ebf7" }, { color: "#17becf", bg: "#e0f5f7" },
    { color: "#e377c2", bg: "#fbe6f3" }, { color: "#8c564b", bg: "#efe1de" },
    { color: "#bcbd22", bg: "#f6f6d8" }, { color: "#000000", bg: "#eeeeee" },
    { color: "#7f7f7f", bg: "#f0f0f0" }, { color: "#ff1493", bg: "#ffe2ee" },
    { color: "#daa520", bg: "#fbf0d4" }, { color: "#4b0082", bg: "#ece0f0" },
    { color: "#00875a", bg: "#d8f0e6" }, { color: "#a52a2a", bg: "#f4dada" },
];

function escapeM(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;",
    }[c]));
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
        const pendents = (it.n_productes || 0) - (it.n_preparats || 0);
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
                <div class="meta progres">${it.n_preparats || 0} preparats / ${pendents} pendents</div>
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
let magState = {
    id: null,
    obj: null,
    preparats: new Set(),
    ocultarPrep: false,
    colorsCarrega: new Map(),
    pollTimer: null,
    lastInteractionTs: 0,    // moment de l'últim tap (per no repintar enmig)
    pendingRefresh: null,    // objecte rebut durant interacció (s'aplica després)
    lastSig: null,           // signatura del darrer poll (n_preparats + finalitzada)
    consecutiveNoChange: 0,  // polls consecutius sense canvis (backoff)
    lastPct: null,           // % preparat del darrer render (null = abans del primer render)
};

const INTERACCIO_MS = 1200;  // marge per protegir tocs en curs del polling

// Backoff polling: si N polls consecutius sense canvis, allarguem l'interval
// per estalviar bateria/xarxa a la tablet. Reset immediat en qualsevol acció
// local o canvi detectat des del servidor.
function _calcPollDelay() {
    const n = magState.consecutiveNoChange;
    if (n < 2) return 5000;
    if (n < 4) return 10000;
    return 15000;
}

function _signaturaObj(obj) {
    if (!obj) return "";
    const np = (obj.productes_preparats || []).length;
    const fm = obj.finalitzada_manual_at || "";
    return `${np}|${fm}`;
}

function _resetPollBackoff() {
    magState.consecutiveNoChange = 0;
}

function colorPerCarregaIdx(i) {
    return PALETA_MAG[i % PALETA_MAG.length];
}

function calculaProgres() {
    const total = (magState.obj?.resultat?.productes || []).length;
    const prep = magState.preparats.size;
    $m("#mag-prep-count").textContent = prep;
    $m("#mag-total").textContent = total;
    const pct = total ? Math.round((prep / total) * 100) : 0;
    const fill = $m("#mag-progres-fill");
    if (fill) fill.style.width = `${pct}%`;
    const resum = magState.obj?.resultat;
    if (resum) {
        $m("#mag-resum").textContent =
            `${resum.carregues?.length || 0} càrregues · ${fmtN.format(resum.total_sacs || 0)} sacs · ${fmtN.format(resum.total_palets_fisics || 0)} palets`;
    }
    const creadorEl = $m("#mag-creador-nom");
    if (creadorEl) creadorEl.textContent = magState.obj?.created_by_nom || "—";
    const btnDesfes = $m("#mag-desfes");
    if (btnDesfes) btnDesfes.hidden = prep === 0;

    // Feedback unequívoc en arribar al 100% (toast + vibració distintiva +
    // estat visual). Només es dispara a la transició <100 → 100 — no a cada
    // render, ni si l'operari ja arriba a 100 des de polling inicial.
    const prev = magState.lastPct;
    magState.lastPct = pct;
    const wrap = $m(".mag-progres-box");
    if (wrap) wrap.classList.toggle("is-acabada", pct === 100 && total > 0);
    if (pct === 100 && total > 0 && prev < 100 && prev !== null) {
        toast("success", `Agrupació completada — ${total} productes preparats`);
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
    // Ordre: pendents primer (ordenats per total_sacs desc), preparats al final
    prods.sort((a, b) => {
        const pa = magState.preparats.has(a.art_codi) ? 1 : 0;
        const pb = magState.preparats.has(b.art_codi) ? 1 : 0;
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
        const isPrep = magState.preparats.has(p.art_codi);
        if (magState.ocultarPrep && isPrep) continue;

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
            return `<span class="mag-carrega-row" style="--cb-color:${col.color};--cb-bg:${col.bg}">
                        <span class="dot" aria-hidden="true"></span>
                        <span class="nom">${escapeM(nomCar)}</span>
                        <span class="num">#${escapeM(numCurt)}</span>
                        <span class="detall">${escapeM(peces)} · ${fmtN.format(pc.total_sacs)} sacs</span>
                    </span>`;
        }).join("");

        let prepMetaHtml = "";
        if (isPrep) {
            const d = (magState.obj?.preparats_detall || {})[p.art_codi] || {};
            const hora = fmtHoraCurta(d.ts);
            const qui = d.per_nom || "";
            const txt = [qui, hora].filter(Boolean).join(" · ");
            if (txt) prepMetaHtml = `<div class="mag-prep-meta">✓ ${escapeM(txt)}</div>`;
        }

        const li = document.createElement("li");
        li.className = "mag-card" + (isPrep ? " is-preparat" : "");
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
                ${prepMetaHtml}
            </div>
            <button type="button" class="mag-prep-check ${isPrep ? "is-on" : ""}"
                    data-act="toggle"
                    aria-label="${isPrep ? "Desmarca preparat" : "Marca com preparat"}">
                ${isPrep ? "✓" : ""}
            </button>
        `;
        ul.appendChild(li);
    }
    calculaProgres();
}

async function refrescar({ fromPolling = false } = {}) {
    try {
        const obj = await fetchJ(`/api/agrupacions/${encodeURIComponent(magState.id)}`);
        // Detecta canvis per a backoff polling (independentment del defer).
        if (fromPolling) {
            const sig = _signaturaObj(obj);
            if (magState.lastSig === sig) {
                magState.consecutiveNoChange += 1;
            } else {
                magState.consecutiveNoChange = 0;
                magState.lastSig = sig;
            }
        } else {
            magState.lastSig = _signaturaObj(obj);
        }
        const ara = Date.now();
        if (fromPolling && ara - magState.lastInteractionTs < INTERACCIO_MS) {
            // L'operari ha tocat fa molt poc: no repintem perquè no es perdi
            // l'enfocament del tap. Guardem el resultat i l'aplicarem més tard.
            magState.pendingRefresh = obj;
            return;
        }
        magState.obj = obj;
        magState.preparats = new Set(obj.productes_preparats || []);
        magState.pendingRefresh = null;
        renderArticles();
    } catch (e) {
        // Errors del polling silenciosos (no embrutim la UI cada 5s)
        if (!fromPolling) toast("error", "No s'ha pogut refrescar: " + e.message);
    }
}

async function togglePreparat(artCodi, nouEstat) {
    magState.lastInteractionTs = Date.now();
    _resetPollBackoff();  // hi ha activitat — torna a polls de 5s
    // Feedback tàctil immediat (vibració a tablet/mòbil).
    if (navigator.vibrate) {
        try { navigator.vibrate(nouEstat ? 60 : [30, 40, 30]); } catch {}
    }
    // Optimista: actualitza UI immediatament
    if (nouEstat) magState.preparats.add(artCodi);
    else magState.preparats.delete(artCodi);
    renderArticles();
    try {
        const r = await fetchJ(`/api/agrupacions/${encodeURIComponent(magState.id)}/producte`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ art_codi: artCodi, preparat: nouEstat }),
        });
        // Sincronitza el comptador si vol
        calculaProgres();
    } catch (e) {
        // Rollback
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
        titol: "Desfer preparats",
        missatge: `Es desmarcaran ${n} producte${n > 1 ? "s" : ""} com a preparat${n > 1 ? "s" : ""}. Vols continuar?`,
        btnOk: "Sí, desfés-los",
        btnCancel: "No",
        tipus: "danger",
    });
    if (!ok) return;
    _resetPollBackoff();  // hi ha activitat — torna a polls de 5s
    try {
        await fetchJ(`/api/agrupacions/${encodeURIComponent(magState.id)}/reset-preparats`, {
            method: "POST",
        });
        magState.preparats.clear();
        renderArticles();
        toast("success", `Desmarcats ${n} productes`);
    } catch (e) {
        toast("error", "No s'ha pogut desfer: " + e.message);
    }
}

window.magatzemPrep = async function magatzemPrep(id) {
    magState.id = id;
    await refrescar();

    // Delegació de clicks: checkbox preparat
    $m("#mag-articles").addEventListener("click", (ev) => {
        const btn = ev.target.closest('[data-act="toggle"]');
        if (!btn) return;
        const card = btn.closest(".mag-card");
        if (!card) return;
        const artCodi = card.dataset.artCodi;
        const isPrep = magState.preparats.has(artCodi);
        togglePreparat(artCodi, !isPrep);
    });

    // Toggle "amaga preparats"
    $m("#mag-ocultar-prep").addEventListener("change", (ev) => {
        magState.ocultarPrep = ev.target.checked;
        renderArticles();
    });

    // Botó refresca manual
    $m("#mag-refresca").addEventListener("click", refrescar);

    // Botó "Desfés preparats" — només visible quan n'hi ha algun
    $m("#mag-desfes")?.addEventListener("click", desferPreparats);

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

    // Polling de sincronització amb backoff (5s → 10s → 15s) si no hi ha
    // canvis. Només quan la pestanya és visible. Si hi ha hagut interacció
    // recent (tap a un check), el render es difereix perquè no s'esborri el
    // feedback visual mentre l'operari acaba el toc.
    function programaPoll() {
        clearTimeout(magState.pollTimer);
        if (document.hidden) return;
        magState.pollTimer = setTimeout(async () => {
            await refrescar({ fromPolling: true });
            // Si s'havia diferit per interacció, reintentem aviat (no
            // s'aplica el backoff perquè ens devem un render pendent)
            if (magState.pendingRefresh) {
                magState.pollTimer = setTimeout(programaPoll, 1500);
            } else {
                programaPoll();
            }
        }, _calcPollDelay());
    }
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) clearTimeout(magState.pollTimer);
        else programaPoll();
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
