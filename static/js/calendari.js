// =====================================================================
// Calendari mensual de càrregues
// Grid de Dilluns a Divendres (les càrregues de DS/DG, si n'hi ha, surten
// a una secció separada sota el grid).
// Click sobre una càrrega → obre dialog modal amb el detall.
// =====================================================================
(function () {
    "use strict";

    const $ = (sel, root) => (root || document).querySelector(sel);

    const fmtKg0 = new Intl.NumberFormat("ca-ES", { maximumFractionDigits: 0 });
    const fmtKg2 = new Intl.NumberFormat("ca-ES", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    const fmtNum = new Intl.NumberFormat("ca-ES");
    const fmtMes = new Intl.DateTimeFormat("ca-ES", { month: "long", year: "numeric" });
    const fmtDiaLlarg = new Intl.DateTimeFormat("ca-ES", { weekday: "long", day: "numeric", month: "long" });

    // Càrregues amb menys d'aquest pes (kg) es renderitzen agrupades sota un
    // <details> desplegable per reduir scroll vertical al calendari.
    const LLINDAR_PETITES_KG = 1000;

    function capitalitzar(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
    function debounce(fn, delay) {
        let t = null;
        return function (...args) {
            clearTimeout(t);
            t = setTimeout(() => fn.apply(this, args), delay);
        };
    }
    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[ch]));
    }
    function pad(n) { return String(n).padStart(2, "0"); }
    function isoLocal(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
    function ferDataLocal(any, mes, dia) { return new Date(any, mes - 1, dia, 0, 0, 0, 0); }
    function diaSetmana(d) {
        // 0 = dilluns, 6 = diumenge
        return (d.getDay() + 6) % 7;
    }
    function dilluns(d) {
        const x = new Date(d);
        x.setDate(x.getDate() - diaSetmana(x));
        x.setHours(0, 0, 0, 0);
        return x;
    }

    function rangMesVisible(any, mes) {
        // Sempre 6 setmanes (42 dies). El grid només renderitza Dl-Dv,
        // però fetch-egem dades de la setmana sencera per detectar càrregues
        // a DS/DG i mostrar-les a la secció de cap de setmana.
        const primer = ferDataLocal(any, mes, 1);
        const inici = new Date(primer);
        inici.setDate(primer.getDate() - diaSetmana(primer));
        const fi = new Date(inici);
        fi.setDate(inici.getDate() + 41);
        return { inici, fi };
    }

    // Rang d'ordenació per a la separació en blocs dins d'un mateix dia.
    // Prioritat estricta — la primera regla que es compleix determina el bloc.
    //   0 = GRA (granel)
    //   1 = AGRI
    //   2 = Mª Soledad López
    //   3 = alerta capacitat (1 sola comanda i > 17.000 kg)
    //   4 = transport 201 / 194
    //   5 = transport 199
    //   6 = resta
    function rangSort(c) {
        if (c.is_granel) return 0;
        const tra = (c.transportista || "").trim().toUpperCase();
        if (tra.startsWith("AGRI")) return 1;
        const traNorm = tra.normalize("NFD").replace(/[̀-ͯª]/g, "");
        if (traNorm.startsWith("M SOLEDAD LOPEZ")) return 2;
        const traCodi = (c.tra_codi || "").trim();
        // 199 té preferència sobre la regla d'"alerta capacitat" (>17 t en una
        // sola comanda): aquest transportista ja gestiona aquest cas com a
        // habitual i no s'ha de mostrar com a alerta.
        if (traCodi === "199") return 5;
        if ((Number(c.num_comandes) || 0) === 1 && kgDeCarrega(c) > 17000) return 3;
        if (traCodi === "201" || traCodi === "194") return 4;
        return 6;
    }

    // Excepció: per a càrregues "Agri" / "Mª Soledad López", la data que
    // determina el dia al calendari és la d'arribada (car_fecllegada), no
    // la de sortida. La resta segueix amb car_fecsalida.
    function usaDataArribada(c) {
        const tra = (c.transportista || "").trim().toUpperCase();
        if (tra.startsWith("AGRI")) return true;
        const traNorm = tra.normalize("NFD").replace(/[̀-ͯª]/g, "");
        return traNorm.startsWith("M SOLEDAD LOPEZ");
    }

    function dataCalendari(c) {
        if (usaDataArribada(c) && c.car_fecllegada) return c.car_fecllegada;
        return c.car_fecsalida;
    }

    function kgDeCarrega(c) {
        const k = Number(c.kg_total) || 0;
        if (k > 0) return k;
        const t = Number(c.car_pesoteorico) || 0;
        if (t > 0) return t;
        return Number(c.car_pesonetocarga) || 0;
    }

    // ---------------------------------------------------------------
    // Estat
    // ---------------------------------------------------------------
    const DIES_CURT = ["Dl", "Dt", "Dc", "Dj", "Dv", "Ds", "Dg"];

    // Paleta de colors per transportista (10 colors distints + gris "altres").
    // Triats per ser distingibles entre ells i no xocar amb el blau primari
    // (carregues saca) ni el teal (granel).
    const TRA_PALETTE = [
        "#6366f1", // indigo
        "#a855f7", // purple
        "#ec4899", // pink
        "#f59e0b", // amber
        "#10b981", // emerald
        "#06b6d4", // cyan
        "#65a30d", // lime
        "#f97316", // orange
        "#dc2626", // red
        "#0ea5e9", // sky
    ];
    const TRA_COLOR_ALTRES = "#94a3b8"; // slate-400

    const state = {
        any_: 0,
        mes: 0,
        diaInici: null,        // primer dilluns visible
        diaFi: null,           // últim diumenge visible
        carreguesPerDiaTotes: new Map(),  // isoDate -> Carrega[]   (totes, sense filtre)
        carreguesPerDia: new Map(),       // isoDate -> Carrega[]   (filtrades per `cercaText`)
        capSetmanaTotes: [],   // (totes les DS/DG, sense filtre)
        capSetmana: [],        // càrregues DS/DG dins el mes actual (filtrades)
        totalsCount: 0,
        totalsKg: 0,
        totalsSetmana: 0,      // càrregues a la setmana actual (dins del mes vist)
        totalsGranel: 0,       // càrregues amb is_granel (dins del mes vist)
        cercaText: "",
        filtreTra: "",         // tra_codi actiu o "" si cap filtre
        traMap: new Map(),     // tra_codi -> { color, nom, n }
        traOrdre: [],          // tra_codi en l'ordre del top usats
        abortCtrl: null,
        modalAbort: null,
        scrollPendent: true,   // primer render: scrolla a la setmana actual
    };

    // ---------------------------------------------------------------
    // Fetch llista de càrregues
    // ---------------------------------------------------------------
    async function carregaMes() {
        if (state.abortCtrl) state.abortCtrl.abort();
        const ctrl = new AbortController();
        state.abortCtrl = ctrl;

        $("#cal-loading").hidden = false;
        $("#cal-error").hidden = true;

        const desde = isoLocal(state.diaInici);
        const fins  = isoLocal(state.diaFi);
        const url = `/api/carregues?desde=${desde}&fins=${fins}&limit=1000&estat=1`;

        try {
            const resp = await fetch(url, { signal: ctrl.signal, credentials: "same-origin" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            agruparPerDia(data.items || []);
            renderLegenda();
            renderGrid();
            renderCapSetmana();
            renderStats();
        } catch (e) {
            if (e.name === "AbortError") return;
            console.error(e);
            const err = $("#cal-error");
            err.textContent = `No s'ha pogut carregar el calendari: ${e.message}`;
            err.hidden = false;
            state.carreguesPerDia.clear();
            state.capSetmana = [];
            renderGrid();
            renderCapSetmana();
        } finally {
            if (state.abortCtrl === ctrl) state.abortCtrl = null;
            $("#cal-loading").hidden = true;
        }
    }

    function agruparPerDia(items) {
        const perDia = new Map();
        const capSetmana = [];
        for (const c of items) {
            const d = dataCalendari(c);
            if (!d) continue;
            const key = String(d).slice(0, 10);
            const [yy, mm, dd] = key.split("-").map(Number);
            const data = new Date(yy, mm - 1, dd);
            const ws = diaSetmana(data);
            const enMesActual = (yy === state.any_ && mm === state.mes);
            if (ws >= 5) {
                if (enMesActual) capSetmana.push({ data: key, ws, c });
            } else {
                if (!perDia.has(key)) perDia.set(key, []);
                perDia.get(key).push(c);
            }
        }
        // Ordenació dins d'un mateix dia: 4 blocs (rangSort definit a nivell
        // de mòdul) i, dins de cada bloc, ordre per kg total descendent.
        function compararDins(a, b) {
            const ra = rangSort(a);
            const rb = rangSort(b);
            if (ra !== rb) return ra - rb;
            // Dins el bloc: kg de més gran a més petit
            const ka = kgDeCarrega(a);
            const kb = kgDeCarrega(b);
            if (ka !== kb) return kb - ka;
            // Empat: descripció alfabètica
            return (a.car_descripcion || "").localeCompare(b.car_descripcion || "", "ca");
        }
        for (const arr of perDia.values()) {
            arr.sort(compararDins);
        }
        capSetmana.sort((a, b) => {
            if (a.data !== b.data) return a.data.localeCompare(b.data);
            return compararDins(a.c, b.c);
        });
        state.carreguesPerDiaTotes = perDia;
        state.capSetmanaTotes = capSetmana;
        construirMapaTransportistes(items);
        aplicarFiltreText();
    }

    function construirMapaTransportistes(items) {
        // Comptem freqüència per tra_codi. El top 10 reben colors de la paleta;
        // la resta agafen el color "altres" gris.
        const cont = new Map();
        for (const c of items) {
            const codi = (c.tra_codi || "").trim();
            if (!codi) continue;
            const e = cont.get(codi) || { codi, nom: (c.transportista || "").trim() || codi, n: 0 };
            e.n++;
            if (!e.nom) e.nom = (c.transportista || "").trim() || codi;
            cont.set(codi, e);
        }
        // Ordena per freqüència descendent, després alfabèticament
        const ordenats = Array.from(cont.values()).sort((a, b) =>
            b.n - a.n || a.codi.localeCompare(b.codi)
        );
        const traMap = new Map();
        const traOrdre = [];
        for (let i = 0; i < ordenats.length; i++) {
            const e = ordenats[i];
            const color = i < TRA_PALETTE.length ? TRA_PALETTE[i] : TRA_COLOR_ALTRES;
            traMap.set(e.codi, { color, nom: e.nom, n: e.n });
            traOrdre.push(e.codi);
        }
        state.traMap = traMap;
        state.traOrdre = traOrdre;
    }

    function colorPerTra(traCodi) {
        const e = state.traMap.get((traCodi || "").trim());
        return e ? e.color : "";
    }

    function carregaCoincideix(c, q) {
        if (!q) return true;
        const ql = q.toLowerCase();
        const camps = [
            c.carrega_id, c.car_descripcion, c.transportista, c.tra_codi,
            c.car_matricula, c.car_nomconductor, c.car_observaciones,
        ];
        return camps.some(v => (v || "").toString().toLowerCase().includes(ql));
    }

    function aplicarFiltreText() {
        const q = state.cercaText.trim();
        const traF = state.filtreTra || "";
        const matchTra = (c) => !traF || (c.tra_codi || "") === traF;
        // Setmana actual (dilluns ISO) per al KPI "aquesta setmana"
        const dillunsAvuiIso = isoLocal(dilluns(new Date()));
        // Filtra Dl-Dv
        const perDia = new Map();
        let nMes = 0, kgMes = 0, nSetmana = 0, nGranel = 0;
        for (const [key, arr] of state.carreguesPerDiaTotes) {
            const filtrats = arr.filter(c => matchTra(c) && (!q || carregaCoincideix(c, q)));
            if (filtrats.length > 0) perDia.set(key, filtrats);
            // Stats: només dies del mes actual
            const [yy, mm, dd] = key.split("-").map(Number);
            if (yy === state.any_ && mm === state.mes) {
                const dillunsKey = isoLocal(dilluns(new Date(yy, mm - 1, dd)));
                for (const c of filtrats) {
                    nMes++;
                    kgMes += kgDeCarrega(c);
                    if (c.is_granel) nGranel++;
                    if (dillunsKey === dillunsAvuiIso) nSetmana++;
                }
            }
        }
        // Filtra DS/DG (capSetmana — events del mes actual)
        const capSetmana = state.capSetmanaTotes.filter(x =>
            matchTra(x.c) && (!q || carregaCoincideix(x.c, q))
        );
        for (const x of capSetmana) {
            nMes++;
            kgMes += kgDeCarrega(x.c);
            if (x.c.is_granel) nGranel++;
            const [yy, mm, dd] = x.data.split("-").map(Number);
            const dillunsKey = isoLocal(dilluns(new Date(yy, mm - 1, dd)));
            if (dillunsKey === dillunsAvuiIso) nSetmana++;
        }
        state.carreguesPerDia = perDia;
        state.capSetmana = capSetmana;
        state.totalsCount = nMes;
        state.totalsKg = kgMes;
        state.totalsSetmana = nSetmana;
        state.totalsGranel = nGranel;
    }

    // ---------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------
    function actualitzaTitol() {
        const d = ferDataLocal(state.any_, state.mes, 1);
        $("#cal-titol").textContent = capitalitzar(fmtMes.format(d));
    }

    function formatKgCompact(kg) {
        if (kg >= 1000) {
            const t = kg / 1000;
            return `${t.toLocaleString("ca-ES", { maximumFractionDigits: t < 10 ? 1 : 0 })} t`;
        }
        return `${fmtKg0.format(kg)} kg`;
    }

    function renderLegenda() {
        const el = $("#cal-legend");
        if (!el) return;
        if (state.traOrdre.length === 0) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        el.hidden = false;
        const chips = state.traOrdre.map(codi => {
            const e = state.traMap.get(codi);
            const isActive = state.filtreTra === codi;
            const isDimmed = state.filtreTra && !isActive;
            const nom = e.nom || codi;
            return `<button type="button" class="cal-legend-chip${isActive ? " is-active" : ""}${isDimmed ? " is-dimmed" : ""}"
                style="--c:${e.color}"
                data-tra="${escapeHtml(codi)}"
                title="${escapeHtml(nom)} (${escapeHtml(codi)}) · ${e.n} càrregues">
                <span class="cal-legend-dot" aria-hidden="true"></span>
                <span class="cal-legend-nom">${escapeHtml(nom)}</span>
                <span class="cal-legend-n">${e.n}</span>
            </button>`;
        }).join("");
        const clear = state.filtreTra
            ? `<button type="button" class="cal-legend-clear" id="cal-legend-clear">✕ Treu filtre</button>`
            : "";
        el.innerHTML = `<span class="cal-legend-lbl">Transportistes</span>${chips}${clear}`;
    }

    function renderStats() {
        const stats = $("#cal-stats");
        if (state.totalsCount === 0) {
            stats.innerHTML = `<div class="cal-kpi-card is-empty" role="status">
                <span class="cal-kpi-val">—</span>
                <span class="cal-kpi-lbl">Cap càrrega aquest mes</span>
            </div>`;
        } else {
            const card = (val, lbl, title, icon, mod) =>
                `<div class="cal-kpi-card${mod ? " " + mod : ""}" title="${title}">
                    <span class="cal-kpi-ico" aria-hidden="true">${icon}</span>
                    <span class="cal-kpi-val">${val}</span>
                    <span class="cal-kpi-lbl">${lbl}</span>
                </div>`;
            stats.innerHTML =
                card(state.totalsCount, "càrregues", "Càrregues amb data de càrrega aquest mes", "📦", "") +
                card(formatKgCompact(state.totalsKg), "total", "Suma total de pes (kg/t) aquest mes", "⚖", "") +
                card(state.totalsSetmana, "aq. setm.", "Càrregues a la setmana actual (dins del mes vist)", "📅", "is-week") +
                card(state.totalsGranel, "granel", "Càrregues a granel aquest mes", "🌾", "is-granel");
        }

        // Botó "Avui" destacat quan no estem al mes actual
        const t = new Date();
        const auMesActual = (state.any_ === t.getFullYear() && state.mes === (t.getMonth() + 1));
        $("#cal-avui").classList.toggle("is-prominent", !auMesActual);
    }

    function renderGrid() {
        const grid = $("#cal-grid");
        const avuiIso = isoLocal(new Date());
        const avuiSetmanaIso = isoLocal(dilluns(new Date()));
        const frag = document.createDocumentFragment();
        let primeraCelaSetmanaActual = null;

        // 6 setmanes × 5 dies = 30 cel·les (només Dl-Dv).
        let d = new Date(state.diaInici);
        for (let i = 0; i < 42; i++) {
            const ws = diaSetmana(d);
            if (ws < 5) {  // dilluns(0) a divendres(4) — saltem DS/DG
                const iso = isoLocal(d);
                const mesActual = (d.getMonth() + 1 === state.mes && d.getFullYear() === state.any_);
                const isToday = iso === avuiIso;
                const isCurrentWeek = isoLocal(dilluns(d)) === avuiSetmanaIso;
                const llista = state.carreguesPerDia.get(iso) || [];

                const cell = document.createElement("div");
                cell.className = "cal-cell"
                    + (mesActual ? "" : " is-other-month")
                    + (isToday ? " is-today" : "")
                    + (isCurrentWeek ? " is-current-week" : "");
                cell.setAttribute("role", "gridcell");
                cell.dataset.date = iso;
                if (isCurrentWeek && !primeraCelaSetmanaActual) primeraCelaSetmanaActual = cell;

                const head = document.createElement("div");
                head.className = "cal-cell-head";
                const dayLbl = document.createElement("span");
                dayLbl.className = "cal-cell-day";
                dayLbl.textContent = DIES_CURT[ws];
                head.appendChild(dayLbl);
                const num = document.createElement("span");
                num.className = "cal-cell-num";
                num.textContent = String(d.getDate());
                head.appendChild(num);

                if (llista.length > 0) {
                    const badge = document.createElement("span");
                    badge.className = "cal-cell-badge";
                    badge.innerHTML = `<span class="cal-cell-ico" aria-hidden="true">📦</span>${llista.length}`;
                    badge.title = `${llista.length} càrregues`;
                    head.appendChild(badge);

                    // Kg totals a la capçalera (al costat del badge, amb icona ⚖)
                    const sumKg = llista.reduce((acc, c) => acc + kgDeCarrega(c), 0);
                    if (sumKg > 0) {
                        const kgSpan = document.createElement("span");
                        kgSpan.className = "cal-cell-kg";
                        kgSpan.innerHTML = `<span class="cal-cell-ico" aria-hidden="true">⚖</span>${escapeHtml(fmtKg0.format(sumKg))} kg`;
                        kgSpan.title = `Total: ${fmtKg2.format(sumKg)} kg`;
                        head.appendChild(kgSpan);
                    }
                }
                cell.appendChild(head);

                if (llista.length > 0) {
                    const ul = document.createElement("ul");
                    ul.className = "cal-cell-list";
                    // Separem grans i petites. Les petites (<LLINDAR_PETITES_KG)
                    // s'agrupen al final en un <details> desplegable per reduir
                    // scroll vertical al calendari.
                    const grans = [];
                    const petites = [];
                    for (const c of llista) {
                        (kgDeCarrega(c) < LLINDAR_PETITES_KG ? petites : grans).push(c);
                    }
                    let rangAnt = null;
                    for (const c of grans) {
                        const liEvt = renderEvent(c, iso);
                        const rang = rangSort(c);
                        if (rangAnt !== null && rang !== rangAnt) {
                            liEvt.classList.add("is-rang-break");
                        }
                        rangAnt = rang;
                        ul.appendChild(liEvt);
                    }
                    if (petites.length > 0) {
                        const kgPetites = petites.reduce((acc, c) => acc + kgDeCarrega(c), 0);
                        const li = document.createElement("li");
                        li.className = "cal-petites-group";
                        const det = document.createElement("details");
                        const sum = document.createElement("summary");
                        sum.innerHTML =
                            `<span class="cal-petites-ico" aria-hidden="true">📦</span>` +
                            `<span class="cal-petites-lbl">+${petites.length} càrregues petites</span>` +
                            `<span class="cal-petites-kg">${escapeHtml(fmtKg0.format(kgPetites))} kg</span>`;
                        sum.title = `${petites.length} càrregues de menys de ${fmtNum.format(LLINDAR_PETITES_KG)} kg — ${fmtKg2.format(kgPetites)} kg en total`;
                        det.appendChild(sum);
                        const innerUl = document.createElement("ul");
                        innerUl.className = "cal-petites-list";
                        let rangAntP = null;
                        for (const c of petites) {
                            const liEvt = renderEvent(c, iso);
                            const rang = rangSort(c);
                            if (rangAntP !== null && rang !== rangAntP) {
                                liEvt.classList.add("is-rang-break");
                            }
                            rangAntP = rang;
                            innerUl.appendChild(liEvt);
                        }
                        det.appendChild(innerUl);
                        li.appendChild(det);
                        ul.appendChild(li);
                    }
                    cell.appendChild(ul);
                }

                // Desglossament Kg al peu del dia (després de la llista). Sempre
                // renderitzem les 3 files (GRANEL, SACS, TOTAL) si el dia té
                // càrregues, encara que algun valor sigui 0 — l'usuari ho vol
                // així per a coherència visual entre dies.
                if (llista.length > 0) {
                    let kgGra = 0, kgSacs = 0;
                    for (const c of llista) {
                        const kg = kgDeCarrega(c);
                        if (c.is_granel) kgGra += kg;
                        else kgSacs += kg;
                    }
                    const kgTotal = kgGra + kgSacs;
                    const kgBox = document.createElement("div");
                    kgBox.className = "cal-cell-kgs";
                    const fila = (cls, ico, lbl, val, tip) =>
                        `<div class="cal-kg-line ${cls}" title="${escapeHtml(tip)}">` +
                            `<span class="cal-kg-ico" aria-hidden="true">${ico}</span>` +
                            `<span class="cal-kg-lbl">${lbl}</span>` +
                            `<span class="cal-kg-val">${escapeHtml(fmtKg0.format(val))} kg</span>` +
                        `</div>`;
                    kgBox.innerHTML = [
                        fila("is-gra",   "🌾", "GRANEL", kgGra,   `Granel: ${fmtKg2.format(kgGra)} kg`),
                        fila("is-sacs",  "📦", "SACS",   kgSacs,  `Sacs: ${fmtKg2.format(kgSacs)} kg`),
                        fila("is-total", "Σ",  "TOTAL",  kgTotal, `Total: ${fmtKg2.format(kgTotal)} kg`),
                    ].join("");
                    cell.appendChild(kgBox);
                }
                frag.appendChild(cell);
            }
            d.setDate(d.getDate() + 1);
        }
        grid.innerHTML = "";
        grid.appendChild(frag);

        // Fade-in al canvi de mes (treure i reaplicar la classe per re-disparar l'animació)
        const wrap = grid.closest(".cal-wrap");
        if (wrap) {
            wrap.classList.remove("is-loaded");
            // Force reflow per re-disparar l'animació
            // eslint-disable-next-line no-unused-expressions
            void wrap.offsetWidth;
            wrap.classList.add("is-loaded");
        }

        if (state.scrollPendent && primeraCelaSetmanaActual) {
            // Primer render o "Avui": porta la fila de la setmana actual a la vista.
            // `behavior: 'auto'` (instant) per no fer scroll animat molest al carregar.
            primeraCelaSetmanaActual.scrollIntoView({ behavior: "auto", block: "center" });
            state.scrollPendent = false;
        }
    }

    function renderEvent(c, isoData) {
        const li = document.createElement("li");
        li.className = "cal-evt";
        li.tabIndex = 0;
        li.dataset.id = c.carrega_id || "";
        li.dataset.data = isoData;
        li.dataset.tipus = c.is_granel ? "granel" : "saca";
        li.dataset.rang = String(rangSort(c));
        if (c.palletitzable === false) li.classList.add("is-no-palletitzable");
        const traColor = colorPerTra(c.tra_codi);
        if (traColor) li.style.setProperty("--tra-color", traColor);
        // Guardem dades per al tooltip propi
        li._cal = c;

        const nom = (c.car_descripcion || "").trim() || c.carrega_id || "—";
        const kg = kgDeCarrega(c);

        if (c.is_granel) {
            const tag = document.createElement("span");
            tag.className = "cal-evt-tag";
            tag.textContent = "GRANEL";
            tag.title = "Càrrega a granel";
            li.appendChild(tag);
        }

        const sNom = document.createElement("span");
        sNom.className = "cal-evt-nom";
        sNom.textContent = nom;
        li.appendChild(sNom);

        if (kg > 0) {
            const sKg = document.createElement("span");
            sKg.className = "cal-evt-kg";
            sKg.textContent = `${fmtKg0.format(kg)} kg`;
            li.appendChild(sKg);
        }
        return li;
    }

    // ---------------------------------------------------------------
    // Tooltip propi (substitueix l'atribut `title` natiu, més lent i lleig)
    // ---------------------------------------------------------------
    function tooltipHTML(c) {
        const nom = (c.car_descripcion || "").trim() || c.carrega_id || "—";
        const kg = kgDeCarrega(c);
        const transp = (c.transportista || c.tra_codi || "").trim();
        const matricula = (c.car_matricula || "").trim();
        const dataCarrega = fmtDataLlarga(c.car_fecsalida || c.car_fecha, c.car_fecsalida_hora);
        const dataEntrega = fmtDataLlarga(c.car_fecllegada, c.car_fecllegada_hora);
        const rows = [
            `<div class="cal-tt-titol">${escapeHtml(nom)}</div>`,
            `<div class="cal-tt-id muted"><code>${escapeHtml(c.carrega_id)}</code></div>`,
            dataCarrega ? `<div class="cal-tt-row"><span class="muted">Data càrrega:</span> ${escapeHtml(dataCarrega)}</div>` : "",
            dataEntrega ? `<div class="cal-tt-row"><span class="muted">Data entrega:</span> ${escapeHtml(dataEntrega)}</div>` : "",
            transp ? `<div class="cal-tt-row"><span class="muted">Transportista:</span> ${escapeHtml(transp)}</div>` : "",
            matricula ? `<div class="cal-tt-row"><span class="muted">Matrícula:</span> ${escapeHtml(matricula)}</div>` : "",
            kg > 0 ? `<div class="cal-tt-row"><span class="muted">Pes:</span> <strong>${escapeHtml(fmtKg2.format(kg))} kg</strong></div>` : "",
            `<div class="cal-tt-hint muted">Clica per veure el detall complet</div>`,
        ].filter(Boolean).join("");
        return rows;
    }

    let tooltipEl = null;
    function getTooltipEl() {
        if (tooltipEl) return tooltipEl;
        tooltipEl = document.createElement("div");
        tooltipEl.className = "cal-tooltip";
        tooltipEl.setAttribute("role", "tooltip");
        document.body.appendChild(tooltipEl);
        return tooltipEl;
    }
    function mostraTooltip(target, c) {
        const tt = getTooltipEl();
        tt.innerHTML = tooltipHTML(c);
        tt.classList.remove("is-flipped-x", "is-flipped-y");
        tt.classList.add("is-visible");
        const r = target.getBoundingClientRect();
        const margin = 10;
        const ttRect = tt.getBoundingClientRect();
        // Posiciona a la dreta de l'esdeveniment per defecte.
        let left = r.right + margin;
        let top  = r.top + (r.height / 2) - (ttRect.height / 2);
        let flippedX = false, flippedY = false;
        // Si no hi cap a la dreta, prova a l'esquerra
        if (left + ttRect.width > window.innerWidth - 8) {
            left = r.left - ttRect.width - margin;
            flippedX = true;
        }
        // Si tampoc cap a l'esquerra, fer flip vertical (a sota la cel·la)
        if (left < 8) {
            left = Math.max(8, r.left + (r.width / 2) - (ttRect.width / 2));
            top = r.bottom + margin;
            flippedX = false;
            flippedY = true;
        }
        // Clamps verticals per a no sortir de la pantalla
        if (top < 8) top = 8;
        if (top + ttRect.height > window.innerHeight - 8) top = window.innerHeight - ttRect.height - 8;
        tt.style.left = `${left}px`;
        tt.style.top  = `${top}px`;
        if (flippedX) tt.classList.add("is-flipped-x");
        if (flippedY) tt.classList.add("is-flipped-y");
    }
    function amagaTooltip() {
        if (tooltipEl) tooltipEl.classList.remove("is-visible");
    }

    function renderCapSetmana() {
        const sec = $("#cal-capsetmana");
        const ul  = $("#cal-capsetmana-llista");
        if (state.capSetmana.length === 0) {
            sec.hidden = true;
            ul.innerHTML = "";
            return;
        }
        sec.hidden = false;
        $("#cal-capsetmana-comptador").textContent = String(state.capSetmana.length);

        const html = state.capSetmana.map(({ data, ws, c }) => {
            const nom = (c.car_descripcion || "").trim() || c.carrega_id || "—";
            const kg = kgDeCarrega(c);
            const [yy, mm, dd] = data.split("-").map(Number);
            const dataObj = new Date(yy, mm - 1, dd);
            const dataTxt = capitalitzar(fmtDiaLlarg.format(dataObj));
            const transp = (c.transportista || c.tra_codi || "").trim();
            const kgHtml = kg > 0 ? `<span class="cal-cs-kg">${escapeHtml(fmtKg0.format(kg))} kg</span>` : "";
            const transpHtml = transp ? `<span class="cal-cs-tra muted">${escapeHtml(transp)}</span>` : "";
            const npClass = c.palletitzable === false ? " is-no-palletitzable" : "";
            return `<li class="cal-cs-item${npClass}" data-id="${escapeHtml(c.carrega_id)}" data-data="${escapeHtml(data)}" tabindex="0" title="Càrrega ${escapeHtml(c.carrega_id)}">
                <span class="cal-cs-data">${escapeHtml(dataTxt)}</span>
                <span class="cal-cs-nom">${escapeHtml(nom)}</span>
                ${transpHtml}
                ${kgHtml}
            </li>`;
        }).join("");
        ul.innerHTML = html;
    }

    // ---------------------------------------------------------------
    // Modal: detall d'una càrrega
    // ---------------------------------------------------------------
    async function obrirModal(carregaId) {
        if (!carregaId) return;
        const [eje, sca, car] = carregaId.split("/");
        if (!eje || !sca || !car) return;

        if (state.modalAbort) state.modalAbort.abort();
        const ctrl = new AbortController();
        state.modalAbort = ctrl;

        const dlg = $("#cal-modal");
        $("#cal-modal-titol").textContent = `Càrrega ${carregaId}`;
        $("#cal-modal-meta").innerHTML = "";
        $("#cal-modal-body").innerHTML = `<div class="muted cal-modal-loading"><span class="cal-spinner"></span> Carregant detall…</div>`;
        if (typeof dlg.showModal === "function") dlg.showModal();
        else dlg.setAttribute("open", "");

        // Capçalera: troba la càrrega al state per omplir meta sense esperar fetch
        const localItem = trobaCarreguaLocal(carregaId);
        if (localItem) renderModalMeta(localItem);

        try {
            const params = new URLSearchParams({ eje, sca, car });
            const resp = await fetch(`/api/carrega-detall?${params}`, { signal: ctrl.signal, credentials: "same-origin" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            $("#cal-modal-body").innerHTML = renderDetallCarrega(data);
        } catch (e) {
            if (e.name === "AbortError") return;
            $("#cal-modal-body").innerHTML = `<div class="cal-error">Error carregant detall: ${escapeHtml(e.message)}</div>`;
        } finally {
            if (state.modalAbort === ctrl) state.modalAbort = null;
        }
    }

    function trobaCarreguaLocal(carregaId) {
        for (const arr of state.carreguesPerDia.values()) {
            const found = arr.find(c => c.carrega_id === carregaId);
            if (found) return found;
        }
        const cs = state.capSetmana.find(x => x.c.carrega_id === carregaId);
        return cs ? cs.c : null;
    }

    function fmtDataLlarga(iso, hora) {
        if (!iso) return "";
        const [yy, mm, dd] = String(iso).split("-").map(Number);
        if (!(yy && mm && dd)) return "";
        const base = capitalitzar(fmtDiaLlarg.format(new Date(yy, mm - 1, dd)));
        return hora ? `${base}, ${hora}` : base;
    }

    function renderModalMeta(c) {
        const dataCarrega = fmtDataLlarga(c.car_fecsalida || c.car_fecha, c.car_fecsalida_hora);
        const dataEntrega = fmtDataLlarga(c.car_fecllegada, c.car_fecllegada_hora);
        const transp = (c.transportista || c.tra_codi || "").trim();
        const matricula = (c.car_matricula || "").trim();
        const conductor = (c.car_nomconductor || "").trim();
        const kg = kgDeCarrega(c);
        const descripcio = (c.car_descripcion || "").trim();
        const meta = [
            descripcio ? `<div class="cal-modal-meta-row"><strong>${escapeHtml(descripcio)}</strong></div>` : "",
            dataCarrega ? `<div class="cal-modal-meta-row"><span class="muted">Data càrrega:</span> ${escapeHtml(dataCarrega)}</div>` : "",
            dataEntrega ? `<div class="cal-modal-meta-row"><span class="muted">Data entrega:</span> ${escapeHtml(dataEntrega)}</div>` : "",
            transp ? `<div class="cal-modal-meta-row"><span class="muted">Transportista:</span> ${escapeHtml(transp)}</div>` : "",
            matricula ? `<div class="cal-modal-meta-row"><span class="muted">Matrícula:</span> ${escapeHtml(matricula)}</div>` : "",
            conductor ? `<div class="cal-modal-meta-row"><span class="muted">Conductor:</span> ${escapeHtml(conductor)}</div>` : "",
            kg > 0 ? `<div class="cal-modal-meta-row"><span class="muted">Pes total:</span> <strong>${escapeHtml(fmtKg2.format(kg))} kg</strong></div>` : "",
        ].filter(Boolean).join("");
        $("#cal-modal-meta").innerHTML = meta;
    }

    function renderDetallCarrega(data) {
        if (!data.comandes || data.comandes.length === 0) {
            return `<div class="muted">Aquesta càrrega no té comandes associades.</div>`;
        }
        const blocks = data.comandes.map(a => {
            const linies = a.linies.map(l => {
                const np = l.palletitzable === false;
                const cls = np ? ' class="not-palletitzable"' : '';
                const tip = np ? ' title="No palletitzable: el motor d&apos;embalatges ignora aquesta línia"' : '';
                return `<tr${cls}${tip}>
                    <td><code>${escapeHtml(l.art_codi)}</code></td>
                    <td>${escapeHtml(l.art_descrip)}</td>
                    <td>${escapeHtml(l.tunitat)}</td>
                    <td class="num">${fmtNum.format(l.sacs)}</td>
                    <td class="num">${fmtKg0.format(l.kg)}</td>
                </tr>`;
            }).join("");
            const tipoBadge = a.det_tipo === "P"
                ? `<span class="badge badge-warn" title="Comanda pendent">P</span>`
                : `<span class="badge badge-ok" title="Comanda">A</span>`;
            const poblaHtml = a.pobla
                ? `<span class="comanda-pobla" title="Població d'enviament"><span aria-hidden="true">📍</span> ${escapeHtml(a.pobla)}</span>`
                : "";
            return `
                <div class="comanda-block">
                    <h4>
                        <span><code>${escapeHtml(a.comanda)}</code> ${tipoBadge} · ${escapeHtml(a.cli_codi)} ${escapeHtml(a.cli_nom)}${poblaHtml ? " · " + poblaHtml : ""}</span>
                        <span class="muted">${fmtNum.format(a.total_sacs)} sacs · ${fmtKg0.format(a.total_kg)} kg</span>
                    </h4>
                    <table class="data-table data-table-mini">
                        <thead><tr><th>Article</th><th>Descripció</th><th>TUnitat</th><th class="num">Sacs</th><th class="num">Kg</th></tr></thead>
                        <tbody>${linies || `<tr><td colspan="5" class="muted">Sense línies</td></tr>`}</tbody>
                    </table>
                </div>`;
        }).join("");
        return `<div class="detall-resum muted">${data.comandes.length} comandes · <strong>${fmtNum.format(data.total_sacs)}</strong> sacs · <strong>${fmtKg0.format(data.total_kg)}</strong> kg</div>${blocks}`;
    }

    function tancarModal() {
        const dlg = $("#cal-modal");
        if (typeof dlg.close === "function") dlg.close();
        else dlg.removeAttribute("open");
        if (state.modalAbort) { state.modalAbort.abort(); state.modalAbort = null; }
    }

    // ---------------------------------------------------------------
    // Navegació
    // ---------------------------------------------------------------
    function anarA(any, mes) {
        state.any_ = any;
        state.mes = mes;
        const { inici, fi } = rangMesVisible(any, mes);
        state.diaInici = inici;
        state.diaFi = fi;
        actualitzaTitol();
        carregaMes();
    }
    function anarMes(delta) {
        let m = state.mes + delta, y = state.any_;
        while (m < 1) { m += 12; y--; }
        while (m > 12) { m -= 12; y++; }
        anarA(y, m);
    }
    function anarAvui() {
        state.scrollPendent = true;
        const t = new Date();
        anarA(t.getFullYear(), t.getMonth() + 1);
    }

    // ---------------------------------------------------------------
    // Picker mes/any (dropdown ancorat al títol)
    // ---------------------------------------------------------------
    const MESOS_PICKER = ["Gen", "Feb", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Des"];
    const picker = {
        any_: 0,
        obert: false,
    };

    function pickerObre() {
        if (picker.obert) return;
        picker.obert = true;
        picker.any_ = state.any_;
        const el = $("#cal-picker");
        el.hidden = false;
        $("#cal-titol").classList.add("is-open");
        pickerRender();
        document.addEventListener("click", pickerClickFora, true);
        document.addEventListener("keydown", pickerKeydown, true);
    }
    function pickerTanca() {
        if (!picker.obert) return;
        picker.obert = false;
        $("#cal-picker").hidden = true;
        $("#cal-titol").classList.remove("is-open");
        document.removeEventListener("click", pickerClickFora, true);
        document.removeEventListener("keydown", pickerKeydown, true);
    }
    function pickerToggle() {
        if (picker.obert) pickerTanca(); else pickerObre();
    }
    function pickerClickFora(e) {
        const wrap = e.target.closest(".cal-titol-wrap");
        if (!wrap) pickerTanca();
    }
    function pickerKeydown(e) {
        if (e.key === "Escape") {
            e.preventDefault();
            pickerTanca();
            $("#cal-titol").focus();
        }
    }
    function pickerRender() {
        $("#cal-picker-year-lbl").textContent = String(picker.any_);
        const grid = $("#cal-picker-grid");
        const t = new Date();
        const avuiAny = t.getFullYear();
        const avuiMes = t.getMonth() + 1;
        const frag = document.createDocumentFragment();
        for (let m = 1; m <= 12; m++) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "cal-picker-mes"
                + (picker.any_ === state.any_ && m === state.mes ? " is-current" : "")
                + (picker.any_ === avuiAny && m === avuiMes ? " is-today-month" : "");
            btn.textContent = MESOS_PICKER[m - 1];
            btn.dataset.mes = String(m);
            btn.addEventListener("click", () => {
                pickerTanca();
                state.scrollPendent = false;
                anarA(picker.any_, m);
            });
            frag.appendChild(btn);
        }
        grid.innerHTML = "";
        grid.appendChild(frag);
    }

    // ---------------------------------------------------------------
    // Bootstrap
    // ---------------------------------------------------------------
    function init() {
        const t = new Date();
        anarA(t.getFullYear(), t.getMonth() + 1);

        $("#cal-prev").addEventListener("click", () => anarMes(-1));
        $("#cal-next").addEventListener("click", () => anarMes(1));
        $("#cal-avui").addEventListener("click", anarAvui);

        // Llegenda: click a chip filtra per transportista
        $("#cal-legend").addEventListener("click", (e) => {
            const clearBtn = e.target.closest("#cal-legend-clear");
            if (clearBtn) {
                state.filtreTra = "";
                aplicarFiltreText();
                renderLegenda(); renderGrid(); renderCapSetmana(); renderStats();
                return;
            }
            const chip = e.target.closest(".cal-legend-chip");
            if (!chip) return;
            const codi = chip.dataset.tra || "";
            state.filtreTra = (state.filtreTra === codi) ? "" : codi;
            aplicarFiltreText();
            renderLegenda(); renderGrid(); renderCapSetmana(); renderStats();
        });

        // Picker mes/any: click al títol obre el dropdown
        $("#cal-titol").addEventListener("click", pickerToggle);
        $("#cal-titol").addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickerToggle(); }
        });
        $("#cal-picker-year-prev").addEventListener("click", (e) => {
            e.stopPropagation();
            picker.any_ -= 1;
            pickerRender();
        });
        $("#cal-picker-year-next").addEventListener("click", (e) => {
            e.stopPropagation();
            picker.any_ += 1;
            pickerRender();
        });

        document.addEventListener("keydown", (e) => {
            if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
            const dlg = $("#cal-modal");
            if (dlg && dlg.hasAttribute("open")) return;  // tecles dins el modal: deixa que <dialog> gestioni Esc
            if (e.key === "ArrowLeft") { e.preventDefault(); anarMes(-1); }
            else if (e.key === "ArrowRight") { e.preventDefault(); anarMes(1); }
            else if (e.key === "Home") { e.preventDefault(); anarAvui(); }
        });

        const grid = $("#cal-grid");
        const onClickEvt = (e) => {
            const evt = e.target.closest(".cal-evt, .cal-cs-item");
            if (!evt) return;
            obrirModal(evt.dataset.id);
        };
        grid.addEventListener("click", onClickEvt);
        $("#cal-capsetmana-llista").addEventListener("click", onClickEvt);

        // Tooltip propi (substitueix l'atribut title natiu). Mouseover/mouseout
        // bubbleejen i els filtrem per `closest(".cal-evt, .cal-cs-item")`.
        let lastHover = null;
        const onMouseOver = (e) => {
            const evt = e.target.closest(".cal-evt, .cal-cs-item");
            if (!evt || evt === lastHover) return;
            lastHover = evt;
            const c = evt._cal || (evt.dataset.id && trobaCarreguaLocal(evt.dataset.id));
            if (c) mostraTooltip(evt, c);
        };
        const onMouseOut = (e) => {
            const evt = e.target.closest(".cal-evt, .cal-cs-item");
            if (!evt) return;
            if (e.relatedTarget && evt.contains(e.relatedTarget)) return;
            lastHover = null;
            amagaTooltip();
        };
        grid.addEventListener("mouseover", onMouseOver);
        grid.addEventListener("mouseout",  onMouseOut);
        $("#cal-capsetmana-llista").addEventListener("mouseover", onMouseOver);
        $("#cal-capsetmana-llista").addEventListener("mouseout",  onMouseOut);
        window.addEventListener("scroll", amagaTooltip, true);
        window.addEventListener("resize", amagaTooltip);

        // Cerca per text
        const cercaInput = $("#cal-cerca");
        if (cercaInput) {
            const aplicarCerca = debounce(() => {
                state.cercaText = cercaInput.value;
                aplicarFiltreText();
                renderGrid();
                renderCapSetmana();
                renderStats();
            }, 150);
            cercaInput.addEventListener("input", aplicarCerca);
            // Esc dins la caixa neteja
            cercaInput.addEventListener("keydown", (e) => {
                if (e.key === "Escape" && cercaInput.value) {
                    cercaInput.value = "";
                    state.cercaText = "";
                    aplicarFiltreText(); renderGrid(); renderCapSetmana(); renderStats();
                    e.preventDefault();
                    e.stopPropagation();
                }
            });
        }

        const onKeyEvt = (e) => {
            if (e.key !== "Enter" && e.key !== " ") return;
            const evt = e.target.closest(".cal-evt, .cal-cs-item");
            if (!evt) return;
            e.preventDefault();
            obrirModal(evt.dataset.id);
        };
        grid.addEventListener("keydown", onKeyEvt);
        $("#cal-capsetmana-llista").addEventListener("keydown", onKeyEvt);

        // Modal: tanca amb X o clic fora
        const dlg = $("#cal-modal");
        $("#cal-modal-close").addEventListener("click", tancarModal);
        dlg.addEventListener("click", (e) => {
            // Click sobre el backdrop (fora del <article>) tanca
            if (e.target === dlg) tancarModal();
        });
        dlg.addEventListener("close", () => {
            if (state.modalAbort) { state.modalAbort.abort(); state.modalAbort = null; }
        });

        // Auto-refresh cada 10 minuts. No refresca si la pestanya és al fons
        // ni si hi ha el modal de detall obert (per no interrompre la lectura).
        const REFRESH_MS = 10 * 60 * 1000;
        setInterval(() => {
            if (document.hidden) return;
            if (dlg.hasAttribute("open")) return;
            carregaMes();
        }, REFRESH_MS);
        // En tornar a la pestanya després d'estar a un altre tab, refresca un
        // cop perquè els kg/càrregues del dia reflecteixin canvis recents.
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden && !dlg.hasAttribute("open")) carregaMes();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
