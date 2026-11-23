// CRUD d'usuaris (admin only)
(() => {
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const fmtDate = new Intl.DateTimeFormat("ca-ES", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function getCsrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
}

async function fetchJ(url, opts = {}) {
    const method = (opts.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
        const tok = getCsrf();
        if (tok) {
            const h = new Headers(opts.headers || {});
            if (!h.has("X-CSRF-Token")) h.set("X-CSRF-Token", tok);
            opts = { ...opts, headers: h };
        }
    }
    const r = await fetch(url, opts);
    if (!r.ok) {
        let err = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j.error) err = j.error; } catch {}
        const e = new Error(err);
        e.status = r.status;
        throw e;
    }
    return r.json();
}

function toast(type, msg) {
    const wrap = $("#toasts");
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.innerHTML = `<span class="toast-body">${escapeHtml(msg)}</span><button class="toast-close" aria-label="Tanca">×</button>`;
    wrap.appendChild(t);
    const dismiss = () => { t.classList.add("is-leaving"); setTimeout(() => t.remove(), 220); };
    t.querySelector(".toast-close").addEventListener("click", dismiss);
    setTimeout(dismiss, type === "error" ? 8000 : 4000);
}

// ---------------------------------------------------------------------
// Estat i render de la taula
// ---------------------------------------------------------------------
const state = { usuaris: [], editId: null };

function fmtTs(iso) {
    if (!iso) return "—";
    try { return fmtDate.format(new Date(iso)); } catch { return iso; }
}

function rolBadge(rol) {
    const colors = { admin: "#dc2626", oficina: "#2c5282", magatzem: "#d97706", granel: "#6b46c1" };
    const c = colors[rol] || "#718096";
    return `<span class="rol-badge" style="background:${c}">${escapeHtml(rol)}</span>`;
}

function actiuBadge(actiu) {
    return actiu
        ? `<span class="estat-badge estat-actiu">Actiu</span>`
        : `<span class="estat-badge estat-inactiu">Desactivat</span>`;
}

function rowHTML(u) {
    return `
        <tr data-id="${u.id}" class="${u.actiu ? '' : 'is-inactiu'}">
            <td><code>${escapeHtml(u.username)}</code></td>
            <td>${escapeHtml(u.nom)}</td>
            <td>${rolBadge(u.rol)}</td>
            <td>${actiuBadge(u.actiu)}</td>
            <td class="muted-small">${fmtTs(u.created_at)}</td>
            <td class="muted-small">${fmtTs(u.last_login_at)}</td>
            <td class="col-acc">
                <button class="btn-mini" data-act="edit" title="Editar">✏️</button>
                <button class="btn-mini" data-act="password" title="Canviar contrasenya">🔑</button>
                <button class="btn-mini" data-act="toggle-actiu" title="${u.actiu ? 'Desactivar' : 'Activar'}">${u.actiu ? '🚫' : '✓'}</button>
            </td>
        </tr>`;
}

async function carregar() {
    const tbody = $("#taula-usuaris tbody");
    const errEl = $("#usuaris-error");
    errEl.hidden = true;
    tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:1.5rem;">Carregant…</td></tr>`;
    try {
        state.usuaris = await fetchJ("/api/admin/usuaris");
        $("#usuaris-count").textContent = state.usuaris.length;
        if (state.usuaris.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:1.5rem;">Cap usuari.</td></tr>`;
        } else {
            tbody.innerHTML = state.usuaris.map(rowHTML).join("");
        }
    } catch (e) {
        tbody.innerHTML = "";
        errEl.textContent = `Error carregant usuaris: ${e.message}`;
        errEl.hidden = false;
    }
}

// ---------------------------------------------------------------------
// Modal: nou / editar
// ---------------------------------------------------------------------
function obreModalNou() {
    state.editId = null;
    $("#dlg-usuari-titol").textContent = "Nou usuari";
    $("#btn-submit-usuari").textContent = "Crear";
    $("#form-usuari").reset();
    $("#f-username").disabled = false;
    $("#f-password").required = true;
    $("#pwd-hint-create").hidden = false;
    $("#field-actiu-row").hidden = true;
    $("#form-error").hidden = true;
    $("#dlg-usuari").showModal();
    setTimeout(() => $("#f-username").focus(), 50);
}

function obreModalEditar(u) {
    state.editId = u.id;
    $("#dlg-usuari-titol").textContent = `Editar — ${u.username}`;
    $("#btn-submit-usuari").textContent = "Desa";
    $("#f-username").value = u.username;
    $("#f-username").disabled = true;
    $("#f-nom").value = u.nom;
    $("#f-rol").value = u.rol;
    $("#f-actiu").checked = !!u.actiu;
    $("#f-password").value = "";
    $("#f-password").required = false;
    $("#pwd-hint-create").hidden = true;
    $("#field-password-row").hidden = true;  // password només per crear; reset via modal específic
    $("#field-actiu-row").hidden = false;
    $("#form-error").hidden = true;
    $("#dlg-usuari").showModal();
    setTimeout(() => $("#f-nom").focus(), 50);
}

async function submitUsuari(ev) {
    ev.preventDefault();
    const errEl = $("#form-error");
    errEl.hidden = true;
    const data = {
        username: $("#f-username").value.trim().toLowerCase(),
        nom: $("#f-nom").value.trim(),
        rol: $("#f-rol").value,
    };
    try {
        if (state.editId == null) {
            // Crear
            data.password = $("#f-password").value;
            await fetchJ("/api/admin/usuaris", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            toast("success", `Usuari "${data.username}" creat.`);
        } else {
            // Editar (només nom, rol, actiu — sense username ni password)
            await fetchJ(`/api/admin/usuaris/${state.editId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ nom: data.nom, rol: data.rol, actiu: $("#f-actiu").checked }),
            });
            toast("success", "Usuari actualitzat.");
        }
        $("#dlg-usuari").close();
        await carregar();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.hidden = false;
    }
}

// ---------------------------------------------------------------------
// Modal: canvi de contrasenya
// ---------------------------------------------------------------------
function obreModalPassword(u) {
    state.editId = u.id;
    $("#dlg-password-user").textContent = u.username;
    $("#form-password").reset();
    $("#password-error").hidden = true;
    $("#dlg-password").showModal();
    setTimeout(() => $("#f-new-password").focus(), 50);
}

async function submitPassword(ev) {
    ev.preventDefault();
    const errEl = $("#password-error");
    errEl.hidden = true;
    try {
        await fetchJ(`/api/admin/usuaris/${state.editId}/password`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: $("#f-new-password").value }),
        });
        toast("success", "Contrasenya actualitzada.");
        $("#dlg-password").close();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.hidden = false;
    }
}

// ---------------------------------------------------------------------
// Toggle actiu (sense modal)
// ---------------------------------------------------------------------
async function toggleActiu(u) {
    const desactivar = u.actiu;
    if (desactivar && !confirm(`Desactivar ${u.username}? No podrà entrar fins que el reactivis.`)) return;
    try {
        await fetchJ(`/api/admin/usuaris/${u.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ actiu: !u.actiu }),
        });
        toast("success", desactivar ? "Usuari desactivat." : "Usuari activat.");
        await carregar();
    } catch (e) {
        toast("error", e.message);
    }
}

// ---------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    carregar();

    $("#btn-nou-usuari").addEventListener("click", obreModalNou);
    $("#form-usuari").addEventListener("submit", submitUsuari);
    $("#form-password").addEventListener("submit", submitPassword);

    // Tancar modals amb el botó X / Cancel·la
    $$(".app-dialog").forEach(dlg => {
        dlg.addEventListener("click", (e) => {
            if (e.target.matches("[data-close]")) dlg.close();
            else if (e.target === dlg) dlg.close();  // click backdrop
        });
    });

    // Accions per fila (delegation)
    $("#taula-usuaris tbody").addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-act]");
        if (!btn) return;
        const tr = btn.closest("tr[data-id]");
        if (!tr) return;
        const id = +tr.dataset.id;
        const u = state.usuaris.find(x => x.id === id);
        if (!u) return;
        const act = btn.dataset.act;
        if (act === "edit") obreModalEditar(u);
        else if (act === "password") obreModalPassword(u);
        else if (act === "toggle-actiu") toggleActiu(u);
    });
});

})();
