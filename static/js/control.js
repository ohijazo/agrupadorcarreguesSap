// Pantalla /control, "Gestió d'agrupacions": totes les agrupacions desades
// (també les plantilles), amb el progrés del pistolejat i les accions
// d'oficina. Substitueix la finestra "Agrupacions desades" de la pàgina
// principal: "Reimprimir" obre el resultat allà (/?agrupacio=<id>).
(function () {
    "use strict";

    const POLL_MS = 15_000;

    const $ = (sel) => document.querySelector(sel);

    let dades = [];
    let pollTimer = null;

    function escapeM(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[c]));
    }

    function getCsrfTok() {
        const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : "";
    }

    function csrfHeaders(extra = {}) {
        const tok = getCsrfTok();
        const h = new Headers(extra);
        if (tok) h.set("X-CSRF-Token", tok);
        return h;
    }

    function fmtHoraCurta(iso) {
        if (!iso) return "—";
        const d = new Date(iso);
        if (isNaN(d)) return "—";
        return d.toLocaleTimeString("ca-ES", { hour: "2-digit", minute: "2-digit" });
    }

    function fmtDurada(s) {
        if (s == null) return "—";
        if (s < 60) return "<1 min";
        const m = Math.floor(s / 60);
        if (m < 60) return `${m} min`;
        const h = Math.floor(m / 60);
        const mr = m % 60;
        return mr ? `${h}h ${mr}min` : `${h}h`;
    }

    const ESTAT_MAP = {
        pendent: { txt: "Pendent", cls: "ctrl-badge-pendent" },
        en_curs: { txt: "En curs", cls: "ctrl-badge-en-curs" },
        acabada: { txt: "Acabada", cls: "ctrl-badge-acabada" },
        tancada: { txt: "Tancada", cls: "ctrl-badge-tancada" },
    };

    const ORIGEN_MAP = {
        desada:  { txt: "Desada",  cls: "ctrl-badge-origen-desada",  title: "Desada manualment per l'operari" },
        impresa: { txt: "Impresa", cls: "ctrl-badge-origen-impresa", title: "Auto-registrada en imprimir sense desar" },
    };

    function badgeOrigen(it) {
        const m = ORIGEN_MAP[it.origen];
        const plantilla = it.plantilla
            ? ` <span class="ctrl-badge ctrl-badge-origen-desada" title="Plantilla recurrent: l'app la suggereix en futures cerques">Plantilla</span>`
            : "";
        if (!m) return plantilla;
        return `<span class="ctrl-badge ${m.cls}" title="${escapeM(m.title)}">${escapeM(m.txt)}</span>${plantilla}`;
    }

    // Mateix llenguatge que la resta de pantalles: % pistolejat i productes fets.
    function textProgres(it) {
        const prod = `${it.n_preparats || 0}/${it.n_productes || 0} fets`;
        return it.pct_pistolejat == null ? prod : `${it.pct_pistolejat}% · ${prod}`;
    }

    function badgeEstat(it) {
        const m = ESTAT_MAP[it.estat] || { txt: it.estat, cls: "" };
        let title = "";
        if (it.estat === "tancada") {
            const qui = it.finalitzada_manual_per_nom || "—";
            const hora = fmtHoraCurta(it.finalitzada_manual_at);
            title = ` title="Tancada per ${escapeM(qui)} · ${escapeM(hora)}"`;
        }
        return `<span class="ctrl-badge ${m.cls}"${title}>${escapeM(m.txt)}</span>`;
    }

    function avuiISO() {
        const d = new Date();
        const y = d.getFullYear();
        const mo = String(d.getMonth() + 1).padStart(2, "0");
        const dy = String(d.getDate()).padStart(2, "0");
        return `${y}-${mo}-${dy}`;
    }

    function filtrar(items) {
        const origen = $("#ctrl-origen").value;
        const estat = $("#ctrl-estat").value;
        const nomesAvui = $("#ctrl-nomes-avui").checked;
        const today = avuiISO();
        return items.filter((it) => {
            if (origen === "plantilla" ? !it.plantilla : (origen && it.origen !== origen)) return false;
            if (estat && it.estat !== estat) return false;
            if (nomesAvui && !(it.ts || "").startsWith(today)) return false;
            return true;
        });
    }

    function accionsCell(it) {
        const idEsc = escapeM(it.id);
        let principal = "";
        if (it.estat === "tancada") {
            principal = `<button type="button" class="ctrl-btn ctrl-btn-reo" data-act="reobrir" data-id="${idEsc}">Reobrir</button>`;
        } else if (it.estat !== "acabada") {
            principal = `<button type="button" class="ctrl-btn ctrl-btn-fin" data-act="finalitzar" data-id="${idEsc}">Finalitza</button>`;
        }
        const btnImp = `<a class="ctrl-btn ctrl-btn-reo" href="/?agrupacio=${encodeURIComponent(it.id)}" title="Obre el resultat a la pàgina principal per tornar-lo a imprimir">Reimprimir</a>`;
        const btnDel = `<button type="button" class="ctrl-btn ctrl-btn-del" data-act="eliminar" data-id="${idEsc}">Elimina</button>`;
        return `<div class="ctrl-actions">${btnImp}${principal}${btnDel}</div>`;
    }

    function pinta() {
        const tbody = $("#ctrl-tbody");
        const buit = $("#ctrl-buit");
        const count = $("#ctrl-count");
        const items = filtrar(dades);
        count.textContent = `${items.length} / ${dades.length}`;
        if (!items.length) {
            tbody.innerHTML = "";
            buit.hidden = false;
            return;
        }
        buit.hidden = true;
        tbody.innerHTML = items.map((it) => {
            const progres = textProgres(it);
            return `<tr>
                <td>${badgeOrigen(it)}</td>
                <td><a href="/magatzem/${encodeURIComponent(it.id)}" class="ctrl-nom">${escapeM(it.nom)}</a></td>
                <td>${escapeM(fmtData(it.ts))}</td>
                <td>${escapeM(it.created_by_nom || "—")}</td>
                <td class="num">${escapeM(progres)}</td>
                <td>${badgeEstat(it)}</td>
                <td>${escapeM(fmtHoraCurta(it.prep_iniciat))}</td>
                <td>${escapeM(fmtHoraCurta(it.prep_finalitzat))}</td>
                <td>${escapeM(fmtDurada(it.durada_s))}</td>
                <td>${escapeM(it.prep_per_nom || (it.prep_iniciat ? "SGA" : "—"))}</td>
                <td>${accionsCell(it)}</td>
            </tr>`;
        }).join("");
    }

    async function finalitzar(id) {
        try {
            const r = await fetch(`/api/agrupacions/${encodeURIComponent(id)}/finalitzar`,
                { method: "POST", credentials: "same-origin", headers: csrfHeaders() });
            if (!r.ok) {
                console.warn("finalitzar HTTP", r.status);
                return;
            }
            await carregar();
        } catch (e) {
            console.warn("finalitzar error", e);
        }
    }

    async function reobrir(id) {
        try {
            const r = await fetch(`/api/agrupacions/${encodeURIComponent(id)}/reobrir`,
                { method: "POST", credentials: "same-origin", headers: csrfHeaders() });
            if (!r.ok) {
                console.warn("reobrir HTTP", r.status);
                return;
            }
            await carregar();
        } catch (e) {
            console.warn("reobrir error", e);
        }
    }

    async function eliminar(id) {
        const confirma = window.mostrarConfirmacio || (() => Promise.resolve(window.confirm("Eliminar definitivament?")));
        const ok = await confirma({
            titol: "Eliminar agrupació",
            missatge: "L'agrupació quedarà eliminada definitivament. Aquesta acció no es pot desfer.",
            btnOk: "Sí, elimina-la",
            btnCancel: "No",
            tipus: "danger",
        });
        if (!ok) return;
        try {
            const r = await fetch(`/api/agrupacions/${encodeURIComponent(id)}`,
                { method: "DELETE", credentials: "same-origin", headers: csrfHeaders() });
            if (!r.ok) {
                console.warn("eliminar HTTP", r.status);
                return;
            }
            await carregar();
        } catch (e) {
            console.warn("eliminar error", e);
        }
    }

    async function carregar() {
        try {
            const r = await fetch("/api/control/agrupacions", { credentials: "same-origin" });
            if (!r.ok) {
                console.warn("control: HTTP", r.status);
                return;
            }
            dades = await r.json();
            pinta();
        } catch (e) {
            console.warn("control: fetch error", e);
        }
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(carregar, POLL_MS);
    }

    document.addEventListener("DOMContentLoaded", () => {
        $("#ctrl-origen").addEventListener("change", pinta);
        $("#ctrl-estat").addEventListener("change", pinta);
        $("#ctrl-nomes-avui").addEventListener("change", pinta);
        $("#ctrl-tbody").addEventListener("click", (ev) => {
            const btn = ev.target.closest("button[data-act]");
            if (!btn) return;
            const id = btn.dataset.id;
            if (!id) return;
            if (btn.dataset.act === "finalitzar") finalitzar(id);
            else if (btn.dataset.act === "reobrir") reobrir(id);
            else if (btn.dataset.act === "eliminar") eliminar(id);
        });
        carregar();
        startPolling();
    });

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") carregar();
    });
})();
