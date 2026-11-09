// Pantalla "Gestió d'albarans" (oficina). Llista els albarans de l'SGA per
// dates (/api/albarans), obre el PDF del Crystal de SAP i, si està activat,
// els cancel·la a SAP. No fa polling: cada consulta va a SAP.
"use strict";

const RANG_KEY = "alb-rang";
const MAX_DIES = 31;

const albState = { rang: "avui", albarans: [], pdf: false, carregant: false };

function escA(s) {
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
        case "ahir": return [mes(-1), mes(-1)];
        case "setmana": return [mes(-6), avui];
        case "mes": return [mes(-29), avui];
        default: return [avui, avui];
    }
}

function toast(type, msg) {
    const wrap = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span class="toast-icon">${type === "error" ? "✕" : "✓"}</span>
                    <div class="toast-body">${escA(msg)}</div>
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
    const r = await fetch(url, { credentials: "same-origin", ...opts });
    if (r.status === 401) { window.location.href = "/login"; throw new Error("Sessió caducada"); }
    if (!r.ok) {
        let err = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j.error) err = j.error; } catch {}
        throw new Error(err);
    }
    return r.json();
}

function estat(a) {
    if (a.cancelat) return `<span class="alb-estat is-cancelat">Cancel·lat</span>`;
    if (a.obert) return `<span class="alb-estat is-obert">Obert</span>`;
    return `<span class="alb-estat is-tancat">Tancat</span>`;
}

function pintaFila(a) {
    const pdf = albState.pdf && !a.cancelat
        ? `<a class="btn btn-ghost alb-pdf" href="/albarans/${a.docentry}/pdf" target="_blank" rel="noopener"
              aria-label="Obre l'albarà ${escA(a.docnum)} en PDF">📄 PDF</a>`
        : "";
    const cancel = a.cancelable
        ? `<button type="button" class="btn btn-ghost alb-cancel" data-act="cancel-alb"
                   data-docentry="${a.docentry}" data-docnum="${escA(a.docnum)}"
                   aria-label="Cancel·la l'albarà ${escA(a.docnum)} a SAP">✖ Cancel·la</button>`
        : "";
    return `
        <tr class="${a.cancelat ? "is-cancelat" : ""}">
            <td data-lbl="Data">${escA(a.data ? fmtData(a.data) : "")}</td>
            <td data-lbl="Albarà" class="alb-num">${escA(a.docnum)}</td>
            <td data-lbl="Càrrega">#${escA(a.carrega)}</td>
            <td data-lbl="Client">
                <div class="alb-cli">${escA(a.cli_nom || a.cli_codi)}</div>
                <div class="alb-cli-codi">${escA(a.cli_codi)}</div>
            </td>
            <td data-lbl="Estat">${estat(a)}</td>
            <td class="alb-accions">${pdf}${cancel}</td>
        </tr>`;
}

function normalitza(s) {
    return String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function pinta() {
    const q = normalitza(document.getElementById("alb-cerca").value.trim());
    const files = q
        ? albState.albarans.filter(a => normalitza(`${a.docnum} ${a.carrega} ${a.cli_codi} ${a.cli_nom}`).includes(q))
        : albState.albarans;
    document.getElementById("alb-files").innerHTML = files.map(pintaFila).join("");
    document.getElementById("alb-taula").hidden = files.length === 0;
    const buit = document.getElementById("alb-buit");
    buit.hidden = files.length > 0;
    buit.textContent = albState.albarans.length && q
        ? "Cap albarà coincideix amb la cerca."
        : "No hi ha albarans en aquestes dates.";
}

function datesValides() {
    const desde = document.getElementById("alb-desde").value;
    const fins = document.getElementById("alb-fins").value;
    if (!desde || !fins) return "Cal indicar les dues dates.";
    if (desde > fins) return "La data d'inici és posterior a la de final.";
    const dies = (new Date(fins) - new Date(desde)) / 86_400_000;
    if (dies > MAX_DIES) return `El rang màxim és de ${MAX_DIES} dies.`;
    return null;
}

async function refrescar() {
    if (albState.carregant) return;
    const errBox = document.getElementById("alb-error");
    const err = datesValides();
    if (err) { errBox.textContent = err; errBox.hidden = false; return; }
    albState.carregant = true;
    const qs = new URLSearchParams({
        desde: document.getElementById("alb-desde").value,
        fins: document.getElementById("alb-fins").value,
    });
    try {
        const j = await fetchJ(`/api/albarans?${qs}`);
        albState.albarans = j.albarans || [];
        albState.pdf = !!j.pdf;
        pinta();
        errBox.hidden = true;
        document.getElementById("alb-actualitzat").textContent =
            `${albState.albarans.length} albarans · actualitzat a les ${new Date().toLocaleTimeString("ca-ES", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (e) {
        errBox.textContent = `No s'han pogut carregar els albarans de SAP (${e.message}).`;
        errBox.hidden = false;
    } finally {
        albState.carregant = false;
    }
}

// Cancel·la a SAP un albarà de l'SGA. Demana el motiu, que queda a
// l'auditoria de l'app (a SAP la cancel·lació la signa l'usuari del SL).
async function cancelaAlbara(btn) {
    const docnum = btn.dataset.docnum;
    const motiu = await window.mostrarInput({
        titol: `Cancel·lar l'albarà ${docnum} a SAP`,
        etiqueta: "Motiu de la cancel·lació (obligatori). Això no es pot desfer.",
        placeholder: "Ex.: lot equivocat, s'ha de tornar a pistolejar",
        btnOk: "Cancel·la l'albarà",
        btnCancel: "No",
        maxlength: 200,
    });
    if (motiu === null) return;
    if (motiu.trim().length < 5) {
        toast("error", "Cal escriure el motiu (mínim 5 caràcters).");
        return;
    }
    btn.disabled = true;
    btn.textContent = "Cancel·lant…";
    try {
        await fetchJ(`/api/albarans/${encodeURIComponent(btn.dataset.docentry)}/cancelar`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ motiu: motiu.trim() }),
        });
        toast("success", `Albarà ${docnum} cancel·lat a SAP`);
    } catch (e) {
        toast("error", e.message);
    }
    refrescar();
}

function posaRang(rang) {
    albState.rang = rang;
    const [d, f] = rangDates(rang);
    document.getElementById("alb-desde").value = isoLocal(d);
    document.getElementById("alb-fins").value = isoLocal(f);
    marcaRang();
}

function marcaRang() {
    document.querySelectorAll(".pend-rang").forEach(b => {
        const on = b.dataset.rang === albState.rang;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
    });
}

document.addEventListener("DOMContentLoaded", () => {
    posaRang(llegeix(RANG_KEY, "avui"));

    document.querySelectorAll(".pend-rang").forEach(b => b.addEventListener("click", () => {
        posaRang(b.dataset.rang);
        desa(RANG_KEY, albState.rang);
        refrescar();
    }));
    for (const id of ["alb-desde", "alb-fins"]) {
        document.getElementById(id).addEventListener("change", () => {
            albState.rang = "";
            marcaRang();
            refrescar();
        });
    }
    document.getElementById("alb-cerca").addEventListener("input", pinta);
    document.getElementById("alb-refresca").addEventListener("click", refrescar);
    document.getElementById("alb-files").addEventListener("click", ev => {
        const btn = ev.target.closest('[data-act="cancel-alb"]');
        if (btn && !btn.disabled) cancelaAlbara(btn);
    });

    refrescar();
});
