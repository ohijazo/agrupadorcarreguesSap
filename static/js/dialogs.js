// Utilitats de diàlegs custom — substitueixen window.confirm / window.prompt
// per controls integrats amb l'estil de l'app i que funcionen bé a tablet.
//
// API:
//   await mostrarConfirmacio({titol, missatge, btnOk, btnCancel, tipus})
//       -> Promise<boolean>  (true si Ok, false si Cancel·la o Esc)
//   await mostrarInput({titol, etiqueta, defecte, placeholder, btnOk, btnCancel})
//       -> Promise<string|null>  (string si Ok amb valor, null si Cancel·la)
//
// Es despleguen amb HTMLDialogElement nadiu. La cancel·lació amb Esc i el
// clic fora es tracten com a "cancel·la".

(() => {
"use strict";

function _escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function _crearDialeg(id) {
    let dlg = document.getElementById(id);
    if (dlg) return dlg;
    dlg = document.createElement("dialog");
    dlg.id = id;
    dlg.className = "app-dialog";
    document.body.appendChild(dlg);
    return dlg;
}

function _tancar(dlg) {
    if (typeof dlg.close === "function" && dlg.open) {
        try { dlg.close(); } catch {}
    } else {
        dlg.removeAttribute("open");
    }
}

window.mostrarConfirmacio = function mostrarConfirmacio(opts = {}) {
    const titol = opts.titol || "Confirma";
    const missatge = opts.missatge || "";
    const btnOk = opts.btnOk || "D'acord";
    const btnCancel = opts.btnCancel || "Cancel·la";
    const tipus = opts.tipus || "primary";  // "primary" | "danger"

    return new Promise(resolve => {
        const dlg = _crearDialeg("app-dialog-confirm");
        const classeOk = tipus === "danger" ? "btn btn-danger" : "btn btn-primary";
        dlg.innerHTML = `
            <header class="app-dialog-header">
                <h3>${_escape(titol)}</h3>
                <button type="button" class="dialog-close" data-act="cancel" aria-label="Tanca">×</button>
            </header>
            <div class="app-dialog-body">
                <p class="app-dialog-message">${_escape(missatge)}</p>
            </div>
            <footer class="app-dialog-footer">
                <button type="button" class="btn btn-ghost" data-act="cancel">${_escape(btnCancel)}</button>
                <button type="button" class="${classeOk}" data-act="ok" autofocus>${_escape(btnOk)}</button>
            </footer>
        `;
        let resolt = false;
        const fi = (valor) => {
            if (resolt) return;
            resolt = true;
            _tancar(dlg);
            resolve(valor);
        };
        dlg.querySelectorAll('[data-act="ok"]').forEach(b =>
            b.addEventListener("click", () => fi(true), { once: true })
        );
        dlg.querySelectorAll('[data-act="cancel"]').forEach(b =>
            b.addEventListener("click", () => fi(false), { once: true })
        );
        dlg.addEventListener("cancel", (e) => { e.preventDefault(); fi(false); }, { once: true });
        dlg.addEventListener("close", () => fi(false), { once: true });
        if (typeof dlg.showModal === "function") dlg.showModal();
        else dlg.setAttribute("open", "");
    });
};

window.mostrarInput = function mostrarInput(opts = {}) {
    const titol = opts.titol || "Introdueix un valor";
    const etiqueta = opts.etiqueta || "";
    const defecte = opts.defecte ?? "";
    const placeholder = opts.placeholder || "";
    const btnOk = opts.btnOk || "D'acord";
    const btnCancel = opts.btnCancel || "Cancel·la";
    const maxlength = opts.maxlength || 200;
    // Camp opcional: checkbox amb {label, checked, tooltip}. Si està definit,
    // la promesa resol amb {valor, marcat} en comptes de només string.
    const checkbox = opts.checkbox || null;
    // Camp secret opcional ({label, placeholder}), abans del de text, que no es
    // veu en pantalla (p. ex. el codi d'operari). Si està definit, la promesa
    // resol amb {valor, secret}.
    const secret = opts.secret || null;

    return new Promise(resolve => {
        const dlg = _crearDialeg("app-dialog-input");
        const checkHtml = checkbox ? `
            <label class="app-dialog-check" title="${_escape(checkbox.tooltip || "")}">
                <input type="checkbox" id="app-dialog-input-check" ${checkbox.checked ? "checked" : ""}>
                <span>${_escape(checkbox.label || "")}</span>
            </label>` : "";
        dlg.innerHTML = `
            <header class="app-dialog-header">
                <h3>${_escape(titol)}</h3>
                <button type="button" class="dialog-close" data-act="cancel" aria-label="Tanca">×</button>
            </header>
            <form class="app-dialog-body" method="dialog">
                ${secret ? `
                <label for="app-dialog-input-secret">${_escape(secret.label || "")}</label>
                <input type="password" id="app-dialog-input-secret" class="app-dialog-input"
                       inputmode="numeric" autocomplete="off" maxlength="10"
                       placeholder="${_escape(secret.placeholder || "")}">` : ""}
                ${etiqueta ? `<label for="app-dialog-input-field">${_escape(etiqueta)}</label>` : ""}
                <input type="text" id="app-dialog-input-field" class="app-dialog-input"
                       value="${_escape(defecte)}" placeholder="${_escape(placeholder)}" maxlength="${maxlength}" autocomplete="off">
                ${checkHtml}
            </form>
            <footer class="app-dialog-footer">
                <button type="button" class="btn btn-ghost" data-act="cancel">${_escape(btnCancel)}</button>
                <button type="button" class="btn btn-primary" data-act="ok">${_escape(btnOk)}</button>
            </footer>
        `;
        const input = dlg.querySelector("#app-dialog-input-field");
        const check = dlg.querySelector("#app-dialog-input-check");
        const secretIn = dlg.querySelector("#app-dialog-input-secret");
        const form = dlg.querySelector("form");
        let resolt = false;
        const valorOK = () => secret
            ? { valor: input.value, secret: secretIn.value }
            : checkbox
                ? { valor: input.value, marcat: !!check?.checked }
                : input.value;
        const fi = (valor) => {
            if (resolt) return;
            resolt = true;
            _tancar(dlg);
            resolve(valor);
        };
        dlg.querySelector('[data-act="ok"]').addEventListener("click", () => {
            fi(valorOK());
        }, { once: true });
        dlg.querySelectorAll('[data-act="cancel"]').forEach(b =>
            b.addEventListener("click", () => fi(null), { once: true })
        );
        form.addEventListener("submit", (e) => { e.preventDefault(); fi(valorOK()); }, { once: true });
        dlg.addEventListener("cancel", (e) => { e.preventDefault(); fi(null); }, { once: true });
        dlg.addEventListener("close", () => fi(null), { once: true });
        if (typeof dlg.showModal === "function") dlg.showModal();
        else dlg.setAttribute("open", "");
        // Selecciona el text per defecte perquè es pugui sobreescriure ràpidament
        setTimeout(() => {
            if (secretIn) { secretIn.focus(); return; }
            input.focus(); input.select();
        }, 50);
    });
};

})();
