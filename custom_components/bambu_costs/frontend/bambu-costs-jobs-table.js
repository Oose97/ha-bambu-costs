// Every column the table can show. `edit` marks what the user can change from
// the card; the cover button and the tray breakdown are structured, so they
// stay read-only. `unit` is shown under the header label rather than in every
// cell, so the cells hold plain editable values and the column can be as
// narrow as the numbers in it. Inputs are sized by measuring their actual
// rendered text (see .grow), clamped between `min` and `max` ch; `stretch`
// marks the one column that absorbs whatever width is left over.
const BCJT_COLS = [
  { k: "ts",          t: "Date",          type: "text", edit: true, nowrap: true, min: 13, max: 21 },
  { k: "job",         t: "Job",           type: "text", edit: true, min: 10, max: 48, stretch: true },
  { k: "time",        t: "Print time",    type: "text", edit: true, sortKey: "mins", nowrap: true, min: 5, max: 12 },
  { k: "layers",      t: "Layers",        type: "num",  edit: true },
  { k: "weight",      t: "Weight",        type: "num",  edit: true, unit: "g",   dp: 1 },
  { k: "length",      t: "Length",        type: "num",  edit: true, unit: "m",   dp: 2 },
  { k: "nozzle",      t: "Nozzle",        type: "text", edit: true, min: 2, max: 6, center: true },
  { k: "nozzle_type", t: "Nozzle type",   type: "text", edit: true, min: 6, max: 26 },
  { k: "kwh",         t: "Energy",        type: "num",  edit: true, unit: "kWh", dp: 3 },
  { k: "f_cost",      t: "Filament",      type: "num",  edit: true, unit: "$",   dp: 2 },
  { k: "p_cost",      t: "Power",         type: "num",  edit: true, unit: "$",   dp: 2 },
  { k: "cost",        t: "Total",         type: "num",  edit: true, unit: "$",   dp: 2, bold: true },
  { k: "types",       t: "Material",      type: "text", edit: true, min: 6, max: 30 },
  { k: "cover",       t: "Image",         type: "cover", sortable: false, min: 11 },
  { k: "trays",       t: "Filament used", type: "trays", sortable: false },
];
const BCJT_DEFAULT_ORDER = BCJT_COLS.map(c => c.k);
const BCJT_PAGE_SIZES = [10, 20, 50, 100];
// Table height as vh; 0 = grow with the page. Bounding the height is what
// makes the sticky header stick and keeps the horizontal scrollbar on
// screen — an unbounded table's scrollbar sits below the last row.
const BCJT_HEIGHTS = [0, 50, 60, 70, 80];
// What the printer can actually report, offered by a combo cell: focusing it
// opens a popup listing EVERY option (a datalist would filter them against
// the current text, hiding the alternatives exactly when a value is set),
// while the field itself stays free text. The stored value keeps the
// printer's own spelling; only the shown label is prettified.
const BCJT_NOZZLE_SIZES = ["0.2", "0.4", "0.6", "0.8"];
const BCJT_NOZZLE_TYPES = [
  "stainless_steel",
  "hardened_steel",
  "high_flow_hardened_steel",
  "tungsten_carbide",
  "high_flow_tungsten_carbide",
];

// Known filament type names, for display only: a stored value containing one
// (whatever brand precedes it — "SUNLU PETG", "Filalab ABS", "Bambu PLA
// Matte") shows just the type; no match shows the full stored text. Matched
// longest-first so "PLA Matte" wins over "PLA". The integration publishes a
// configurable list on the sensor; this built-in one is the fallback.
const bcjtTypeMatchers = names => names.slice()
  .sort((a, b) => b.length - a.length)
  .map(sku => ({
    sku,
    // Word-boundary-ish: the char before and after must not be alphanumeric
    // or "+", so "PLA Tough" does not claim "PLA Tough+" (its own entry wins).
    rx: new RegExp("(^|[^a-z0-9+])"
      + sku.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&")
      + "($|[^a-z0-9+])", "i"),
  }));

const BCJT_FILAMENT_TYPES = bcjtTypeMatchers([
  "Support for PLA/PETG", "Support for ABS", "Support for PA/PET",
  "PLA Aero", "PLA Basic", "PLA Dynamic", "PLA Galaxy", "PLA Glow", "PLA Lite",
  "PLA Marble", "PLA Matte", "PLA Metal", "PLA Pure", "PLA Silk+", "PLA Silk",
  "PLA Sparkle", "PLA Tough+", "PLA Tough", "PLA Translucent", "PLA Wood", "PLA-CF",
  "PETG Basic", "PETG HF", "PETG Translucent", "PETG-CF",
  "ABS-GF", "ABS", "ASA Aero", "ASA-CF", "ASA", "PC FR", "PC",
  "PAHT-CF", "PA6-CF", "PA6-GF", "PA-CF", "PET-CF", "PPA-CF", "PPS-CF",
  "TPU for AMS", "TPU 95A HF", "TPU 95A", "TPU 90A", "TPU 85A", "TPU",
  "PVA", "PETG", "PLA",
]);

class BambuCostsJobsTable extends HTMLElement {
  setConfig(cfg) {
    if (!cfg.entity) throw new Error("Define an entity (sensor.bambu_costs_job_log)");
    this._cfg = Object.assign({
      title: "Print jobs",
      page_size: 20,
      save_service: "bambu_costs.write_jobs",
      // Only used when a row predates cover_url; the integration serves covers itself.
      image_base: "/bambu-costs-covers/",
      currency: null,  // null → take it from the integration
    }, cfg);
    this._sort = { key: "ts", dir: -1 };   // newest first
    this._pageSize = this._cfg.page_size;
    this._maxH = 70;
    this._hideFailed = true;
    this._page = 0;
    this._filter = "";
    this._rows = [];
    this._baseSig = null;
    this._dirty = false;
    this._justSaved = false;
    this._busy = false;
    this._edited = new Set();
    this._nextKey = 1;
    // Display only. What a save writes is decided by the backend's canonical
    // column set and the file's own row order, never by the view.
    this._order = BCJT_DEFAULT_ORDER.slice();
    this._hidden = new Set();
    this._restoreSettings();
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._cfg.entity];
    if (!this._cfg.currency) {
      this._cfg.currency = (st && st.attributes && st.attributes.currency) || "€";
    }
    // The configurable known-types list rides on the sensor; rebuild the
    // matchers only when it actually changes.
    const names = (st && st.attributes && st.attributes.type_names) || null;
    const nsig = Array.isArray(names) ? names.join("|") : "";
    if (nsig !== this._typeSig) {
      this._typeSig = nsig;
      this._typeMatch = Array.isArray(names) && names.length ? bcjtTypeMatchers(names) : null;
    }
    if (!this._built) { this._load(); this._render(); return; }
    if (this._busy) return;
    const sig = JSON.stringify(this._sensorData());
    if (sig === this._baseSig) return;

    if (this._justSaved) {
      // Our own write coming back from the sensor — adopt it as the new
      // baseline. The table already shows exactly this data.
      this._justSaved = false;
      this._baseSig = sig;
      if (!this._dirty) { this._load(); this._paint(); }
      return;
    }

    if (this._dirty) return;
    this._load();
    this._paint();
  }

  getCardSize() { return 12; }

  // ── data ─────────────────────────────────────────────────
  _sensorData() {
    const st = this._hass && this._hass.states[this._cfg.entity];
    return (st && st.attributes && st.attributes.data) || [];
  }

  _load() {
    const d = this._sensorData();
    this._baseSig = JSON.stringify(d);
    // orig_ts is the row's identity for saving: it stays what the file had
    // even after the visible timestamp is edited.
    this._rows = d.map(r => Object.assign({ _k: this._nextKey++, orig_ts: String(r.ts || "") }, r));
    this._edited = new Set();
    this._dirty = false;
  }

  _row(k) { return this._rows.find(r => r._k === Number(k)); }

  _cols() {
    return this._order
      .map(k => BCJT_COLS.find(c => c.k === k))
      .filter(c => c && !this._hidden.has(c.k));
  }

  // ── persisted view settings ──────────────────────────────
  _settingsKey() { return `bambu-costs-jobs-cols:${this._cfg.entity}`; }

  _restoreSettings() {
    try {
      const raw = localStorage.getItem(this._settingsKey());
      if (!raw) return;
      const s = JSON.parse(raw);
      if (Array.isArray(s.order)) {
        // Keep only keys that still exist, then append any newly added column
        // so an upgrade never silently drops one.
        const known = new Set(BCJT_DEFAULT_ORDER);
        const order = s.order.filter(k => known.has(k));
        for (const k of BCJT_DEFAULT_ORDER) if (!order.includes(k)) order.push(k);
        this._order = order;
      }
      if (Array.isArray(s.hidden)) this._hidden = new Set(s.hidden);
      if (s.sortKey) this._sort = { key: s.sortKey, dir: s.sortDir === 1 ? 1 : -1 };
      if (Number(s.pageSize) > 0) this._pageSize = Number(s.pageSize);
      if (s.maxh !== undefined) this._maxH = Number(s.maxh) || 0;
      if (typeof s.hideFailed === "boolean") this._hideFailed = s.hideFailed;
    } catch (e) { /* corrupt or unavailable — fall back to defaults */ }
  }

  _saveSettings() {
    try {
      localStorage.setItem(this._settingsKey(), JSON.stringify({
        order: this._order, hidden: [...this._hidden],
        sortKey: this._sort.key, sortDir: this._sort.dir, pageSize: this._pageSize,
        maxh: this._maxH, hideFailed: this._hideFailed,
      }));
    } catch (e) { /* private mode — layout just will not persist */ }
  }

  // Bounded: the table scrolls inside its own box, the header sticks, and
  // the horizontal scrollbar stays on screen. Unbounded: the wrapper must
  // not be a vertical scroller at all — overflow-x:auto alone computes
  // overflow-y to auto, and a fractional-zoom pixel of phantom range is
  // enough for the browser to latch wheel gestures onto it.
  _applyScrollMode() {
    const el = this.querySelector(".bcjt-scroll");
    if (!el) return;
    if (this._maxH > 0) {
      el.style.maxHeight = this._maxH + "vh";
      el.style.overflowY = "auto";
    } else {
      el.style.maxHeight = "";
      el.style.overflowY = "hidden";
    }
  }

  // ── helpers ──────────────────────────────────────────────
  // Every bambu_costs service call names the entity's own config entry, so
  // a second loaded entry — another printer, a test setup — never makes the
  // call ambiguous, for this card or for that one. An older backend without
  // the attribute just resolves its single entry, as before.
  _withEntry(data) {
    const st = this._hass && this._hass.states[this._cfg.entity];
    const id = st && st.attributes && st.attributes.entry_id;
    return id ? Object.assign({ entry_id: id }, data) : data;
  }

  _esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  _parseColor(s) {
    if (!s) return null;
    s = String(s).trim();
    let m = s.match(/^#?([0-9a-f]{6})/i);
    if (m) return [parseInt(m[1].slice(0,2),16), parseInt(m[1].slice(2,4),16), parseInt(m[1].slice(4,6),16)];
    m = s.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/i);
    if (m) return [+m[1], +m[2], +m[3]];
    return null;
  }

  _css(rgb) {
    return "#" + rgb.map(v => Math.max(0, Math.min(255, v)).toString(16)
      .padStart(2, "0")).join("").toUpperCase();
  }

  // The configured currency, as its symbol where one is well known — cells
  // read "0.09 €" rather than "0.09 EUR" three times per row.
  _cur() {
    const cur = this._cfg.currency;
    return { EUR: "€", USD: "$", GBP: "£" }[cur] || cur;
  }

  _unit(col) {
    return col.unit === "$" ? this._cur() : col.unit;
  }

  // "SUNLU PETG" → "PETG"; "Bambu PLA Matte" → "PLA Matte"; unmatched text
  // shows in full. Display only — the stored value is never touched.
  _shortType(part) {
    const t = String(part || "").trim();
    if (!t) return "";
    const hit = (this._typeMatch || BCJT_FILAMENT_TYPES).find(m => m.rx.test(t));
    return hit ? hit.sku : t;
  }

  _typesDisp(v) {
    return String(v || "").split(",").map(p => this._shortType(p)).filter(Boolean).join(", ");
  }

  // "high_flow_hardened_steel" → "HF Hardened Steel". Generic on purpose: an
  // unlisted value still reads well instead of needing a hand-kept map.
  _typeDisp(v) {
    return String(v || "")
      .split("_")
      .map(w => w ? w[0].toUpperCase() + w.slice(1) : w)
      .join(" ")
      .replace(/^High Flow\b/, "HF");
  }

  // ── view pipeline ────────────────────────────────────────
  _filtered() {
    let rows = this._rows;
    // The hidden count is what the footer reports, so the successes-only
    // default never silently loses a logged failure.
    this._hiddenFailed = 0;
    if (this._hideFailed) {
      rows = rows.filter(r => r.status !== "failed");
      this._hiddenFailed = this._rows.length - rows.length;
    }
    const q = this._filter;
    if (!q) return rows;
    return rows.filter(r => {
      const trays = (r.trays || []).map(t => `${t.label} ${t.type || ""} ${t.name}`).join(" ");
      return `${r.ts} ${r.job} ${r.nozzle} ${r.nozzle_type} ${this._typeDisp(r.nozzle_type)} ${r.types} ${trays} ${r.status || ""}`
        .toLowerCase().includes(q);
    });
  }

  _sorted() {
    const { key, dir } = this._sort;
    const col = BCJT_COLS.find(c => (c.sortKey || c.k) === key);
    const num = key === "mins" || (col && col.type === "num");
    return this._filtered().slice().sort((a, b) => {
      if (num) return ((parseFloat(a[key]) || 0) - (parseFloat(b[key]) || 0)) * dir;
      const x = String(a[key] ?? "").toLowerCase(), y = String(b[key] ?? "").toLowerCase();
      return x < y ? -dir : x > y ? dir : 0;
    });
  }

  // Trays arrive as structured objects from the integration, so there is no
  // delimited string left to unpick. The cell is a compact summary — one dot
  // per slot, the slot count and the summed weight — and the detail lives in
  // a modal, so a multi-material job does not stretch every row it is in.
  _traysCell(r) {
    const trays = r.trays;
    if (!Array.isArray(trays) || !trays.length) return `<span class="muted">—</span>`;
    const dots = trays.map(t => {
      const rgb = this._parseColor(t.color || "");
      return rgb ? `<i class="dot" style="background:${this._css(rgb)}"></i>` : "";
    }).join("");
    const total = trays.reduce((s, t) => s + (parseFloat(t.weight) || 0), 0);
    // Full names here, brand included — the Material column is the one that
    // shortens; the per-slot detail tells the whole story.
    const tip = this._esc(trays.map(t =>
      `${t.label || "?"}${t.type ? " " + t.type : ""} ${(parseFloat(t.weight) || 0).toFixed(1)} g`
    ).join("\n"));
    return `<button class="trbtn" data-k="${r._k}" title="${tip}">${dots}` +
      `${trays.length} slot${trays.length === 1 ? "" : "s"} · ${total.toFixed(1)} g</button>`;
  }

  _openTrays(r) {
    const trays = Array.isArray(r.trays) ? r.trays : [];
    const cur = this._esc(this._cur());

    // The modal edits the row's tray objects in place — raw values, no
    // display shortening, so what is edited is exactly what is stored.
    const rowHtml = (t, i) => `
      <div class="bcjt-target trrow">
        <input type="color" class="tsw" data-i="${i}" data-tf="color"
          value="${this._esc(/^#[0-9a-f]{6}/i.test(t.color || "") ? t.color.slice(0, 7) : "#808080")}"
          title="Colour">
        <span class="bcjt-target-label">
          <span class="trline">
            <input class="cell tin" data-i="${i}" data-tf="label" title="Slot"
              value="${this._esc(t.label || "")}" style="width:6ch">
            <input class="cell tin" data-i="${i}" data-tf="type" placeholder="material"
              value="${this._esc(t.type || "")}" style="width:15ch">
          </span>
          <span class="trline">
            <input class="cell tin" data-i="${i}" data-tf="name" placeholder="colour name"
              value="${this._esc(t.name || "")}" style="width:23ch">
          </span>
        </span>
        <span class="trnum">
          <span class="trline"><input class="cell tin num" type="number" step="any" data-i="${i}"
            data-tf="weight" value="${isNaN(parseFloat(t.weight)) ? "" : parseFloat(t.weight)}"
            style="width:8ch"><span class="cu">g</span></span>
          <span class="trline"><input class="cell tin num" type="number" step="any" data-i="${i}"
            data-tf="price" value="${isNaN(parseFloat(t.price)) ? "" : parseFloat(t.price)}"
            style="width:8ch"><span class="cu">${cur}/kg</span></span>
          <span class="trline"><input class="cell tin num" type="number" step="any" data-i="${i}"
            data-tf="cost" value="${isNaN(parseFloat(t.cost)) ? "" : parseFloat(t.cost)}"
            style="width:8ch"><span class="cu">${cur}</span></span>
        </span>
      </div>`;

    const ov = document.createElement("div");
    ov.className = "bcjt-modal";
    ov.innerHTML = `
      <div class="bcjt-sheet" style="width:min(94vw,520px)" role="dialog" aria-modal="true">
        <div class="bcjt-sheet-head">
          <div class="bcjt-sheet-title">Filament used</div>
          <div class="bcjt-target-cur">${this._esc(r.job || "")}${r.ts ? ` · ${this._esc(r.ts)}` : ""}</div>
        </div>
        <div class="bcjt-sheet-body">${trays.map(rowHtml).join("")
          || `<div class="bcjt-target"><span class="muted">No per-slot data</span></div>`}</div>
        <div class="bcjt-sheet-foot">
          <span class="trtotal" style="align-self:center"></span>
          <button class="tbtn close">Done</button>
        </div>
      </div>`;

    const totals = () => {
      const w = trays.reduce((s, t) => s + (parseFloat(t.weight) || 0), 0);
      const c2 = trays.reduce((s, t) => s + (parseFloat(t.cost) || 0), 0);
      ov.querySelector(".trtotal").textContent = `${w.toFixed(1)} g · ${c2.toFixed(2)} ${this._cur()}`;
    };
    totals();

    ov.addEventListener("change", e => {
      const el = e.target.closest("[data-tf]");
      if (!el) return;
      const t = trays[Number(el.dataset.i)];
      if (!t) return;
      const f = el.dataset.tf;
      if (f === "weight" || f === "price" || f === "cost") {
        t[f] = parseFloat(String(el.value).replace(",", ".")) || 0;
        // Weight or price moved: the line's cost follows, the same way the
        // logger computed it. A direct cost edit stands on its own.
        if (f !== "cost") {
          t.cost = Math.round((parseFloat(t.weight) || 0) / 1000 * (parseFloat(t.price) || 0) * 1e4) / 1e4;
          const ci = ov.querySelector(`[data-i="${el.dataset.i}"][data-tf="cost"]`);
          if (ci) ci.value = t.cost;
        }
      } else {
        t[f] = el.value;
      }
      this._edited.add(r._k);
      this._dirty = true;
      totals();
      this._updateFoot();
    });

    // Repaint on close so the summary button reflects the edits.
    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); this._paint(); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    ov.querySelector("button.close").addEventListener("click", close);
    document.addEventListener("keydown", esc);
    this.appendChild(ov);
  }

  // The + Print button expands to the two manual forms. Same popup dress as
  // the combo cells, but its own lifecycle: closed by picking an option,
  // clicking anywhere else, Escape, or pressing the button again.
  _toggleAddMenu(btn) {
    if (this._addMenu) { this._closeAddMenu(); return; }
    const dd = document.createElement("div");
    dd.className = "bcjt-dd";
    dd.innerHTML = `
      <div class="opt" data-add="finished">Add finished print</div>
      <div class="opt" data-add="failed">Add failed print</div>`;
    // mousedown, like the combo popups: activation must not lose a race
    // against anything that closes the menu on the same gesture.
    dd.addEventListener("mousedown", e => {
      const opt = e.target.closest(".opt");
      if (!opt) return;
      e.preventDefault();
      const failed = opt.dataset.add === "failed";
      this._closeAddMenu();
      this._openAdd(failed);
    });
    this.appendChild(dd);
    const r = btn.getBoundingClientRect();
    dd.style.left = r.left + "px";
    dd.style.top = (r.bottom + 2) + "px";
    dd.style.minWidth = Math.max(r.width, 160) + "px";
    this._addMenu = dd;
    // The dashboard renders cards inside shadow roots, and a document-level
    // listener sees events RETARGETED to the shadow host — e.target is never
    // the menu, and testing it would close the menu on the very mousedown
    // that was picking an option. composedPath crosses the boundary.
    this._addMenuOff = e => {
      const path = e.composedPath ? e.composedPath() : [e.target];
      if (!path.includes(dd) && !path.includes(btn)) this._closeAddMenu();
    };
    this._addMenuEsc = e => { if (e.key === "Escape") this._closeAddMenu(); };
    document.addEventListener("mousedown", this._addMenuOff);
    document.addEventListener("keydown", this._addMenuEsc);
  }

  _closeAddMenu() {
    if (!this._addMenu) return;
    this._addMenu.remove();
    this._addMenu = null;
    document.removeEventListener("mousedown", this._addMenuOff);
    document.removeEventListener("keydown", this._addMenuEsc);
  }

  // ── the manual print forms ───────────────────────────────
  // One form, two doors: a print that failed part-way, and a finished one
  // the integration missed. Pre-filled by the integration from the print on
  // the printer (or the last one, once it is idle): the plan's filament
  // figures — scaled by how many layers actually finished when logging a
  // failure — and the stint's measured time, energy and electricity as they
  // are. Everything is editable; Save appends the row.
  async _openAdd(failed) {
    let draft;
    try {
      draft = (await this._hass.callWS({
        type: "call_service", domain: "bambu_costs", service: "draft_job",
        service_data: this._withEntry({}), return_response: true,
      })).response;
    } catch (err) {
      this._msg("Could not pre-fill the job: " + err.message, "err");
      return;
    }

    const row = draft.row || {};
    row.status = failed ? "failed" : "success";
    if (!failed) row.layers_done = 0;
    // A failure announces itself in the log's Job column. Prefilled, not
    // enforced — the field is right there to edit the tag away.
    if (failed && !/\[FAILED\]/i.test(row.job || "")) {
      row.job = ("[FAILED] " + (row.job || "")).trim();
    }
    // The untouched plan, kept aside so the layer ratio always scales from
    // the full job rather than compounding on its own output.
    const plan = JSON.parse(JSON.stringify(row));
    const cur = this._esc(this._cur());
    const hmin = m => `${Math.floor(m / 60)}h ${Math.round(m % 60)}min`;

    const num = (k, unit, w = 8) => `<span class="trline"><input class="cell tin num"
      type="number" step="any" data-ff="${k}" value="${isNaN(parseFloat(row[k])) ? "" : parseFloat(row[k])}"
      style="width:${w}ch"><span class="cu">${unit}</span></span>`;
    const field = (label, inner, sub = "") => `
      <div class="bcjt-target">
        <span class="bcjt-target-label"><span class="bcjt-target-name">${label}</span>${
          sub ? `<span class="bcjt-target-cur">${sub}</span>` : ""}</span>
        ${inner}
      </div>`;
    const text = (k, w) => `<input class="cell tin" data-ff="${k}"
      value="${this._esc(row[k] || "")}" style="width:${w}ch">`;

    const trayHtml = (t, i) => `
      <div class="bcjt-target trrow">
        <input type="color" class="tsw" data-i="${i}" data-tf="color"
          value="${this._esc(/^#[0-9a-f]{6}/i.test(t.color || "") ? t.color.slice(0, 7) : "#808080")}">
        <span class="bcjt-target-label">
          <span class="trline">
            <input class="cell tin" data-i="${i}" data-tf="label" title="Slot"
              value="${this._esc(t.label || "")}" style="width:6ch">
            <input class="cell tin" data-i="${i}" data-tf="type" placeholder="material"
              value="${this._esc(t.type || "")}" style="width:15ch">
          </span>
          <span class="trline">
            <input class="cell tin" data-i="${i}" data-tf="name" placeholder="colour name"
              value="${this._esc(t.name || "")}" style="width:23ch">
          </span>
        </span>
        <span class="trnum">
          <span class="trline"><input class="cell tin num" type="number" step="any" data-i="${i}"
            data-tf="weight" value="${isNaN(parseFloat(t.weight)) ? "" : parseFloat(t.weight)}"
            style="width:8ch"><span class="cu">g</span></span>
          <span class="trline"><input class="cell tin num" type="number" step="any" data-i="${i}"
            data-tf="price" value="${isNaN(parseFloat(t.price)) ? "" : parseFloat(t.price)}"
            style="width:8ch"><span class="cu">${cur}/kg</span></span>
          <span class="trline"><input class="cell tin num" type="number" step="any" data-i="${i}"
            data-tf="cost" value="${isNaN(parseFloat(t.cost)) ? "" : parseFloat(t.cost)}"
            style="width:8ch"><span class="cu">${cur}</span></span>
        </span>
      </div>`;

    const ov = document.createElement("div");
    ov.className = "bcjt-modal";
    ov.innerHTML = `
      <div class="bcjt-sheet" style="width:min(94vw,560px)" role="dialog" aria-modal="true">
        <div class="bcjt-sheet-head">
          <div class="bcjt-sheet-title">${failed ? "Log failed print" : "Log finished print"}</div>
          <div class="bcjt-target-cur">${draft.running
            ? "Pre-filled from the print running now."
            : "Pre-filled from the last print."} Everything is editable.</div>
        </div>
        <div class="bcjt-sheet-body">
          ${field("Date", text("ts", 21))}
          ${field("Job", text("job", 26))}
          ${failed ? field("Layers completed",
            `<span class="lsplit"><input class="cell tin num" type="number" step="any"
              data-ff="layers_done" value="${isNaN(parseFloat(row.layers_done)) ? "" : parseFloat(row.layers_done)}"
              style="width:6ch"><span class="sep"> / </span><input class="cell tin num" type="number" step="any"
              data-ff="layers" value="${isNaN(parseFloat(row.layers)) ? "" : parseFloat(row.layers)}"
              style="width:6ch"></span>`,
            "Editing these rescales the filament figures from the plan")
          : field("Layers", num("layers", "", 6))}
          ${field("Print time", text("time", 12), draft.mins_planned > 0
            ? `Ran so far, of the planned ${hmin(draft.mins_planned)}`
            : "How long it actually ran")}
          ${field("Weight", num("weight", "g"))}
          ${field("Length", num("length", "m"))}
          ${field("Nozzle", `<span class="trline">${text("nozzle", 5)}${text("nozzle_type", 20)}</span>`)}
          ${field("Energy", num("kwh", "kWh"))}
          ${field("Filament cost", num("f_cost", cur))}
          ${field("Power cost", num("p_cost", cur), "Measured for the stint — not scaled")}
          ${field("Total", num("cost", cur))}
          ${field("Material", text("types", 24))}
          <div class="bcjt-target"><span class="bcjt-target-label">
            <span class="bcjt-target-name" style="font-weight:600">Filament used</span>
          </span><span class="trtotal"></span></div>
          <div class="ftrays">${(row.trays || []).map(trayHtml).join("")
            || `<div class="bcjt-target"><span class="muted">No per-slot data</span></div>`}</div>
          <div class="bcjt-target fcover">
            <img style="display:none" alt="">
            <span class="bcjt-target-label">
              <span class="bcjt-target-name">Picture</span>
              <span class="bcjt-target-cur fcap">${draft.has_camera
                ? "Capture a photo of the plate, or Save uses the slicer's render."
                : "Save stores the slicer's render."}</span>
            </span>
            ${draft.has_camera ? `<button class="tbtn snap">📷 Capture photo</button>` : ""}
          </div>
          <div class="bcjt-target">
            <label style="display:flex;align-items:center;gap:8px;font-size:13px">
              <input type="checkbox" class="ftot" checked>
              Add the filament to the lifetime totals
            </label>
          </div>
        </div>
        <div class="bcjt-sheet-foot">
          <button class="tbtn cancel">Cancel</button>
          <button class="save fsave">Save</button>
        </div>
      </div>`;

    const q = s => ov.querySelector(s);
    const setVal = (sel, v) => { const el = q(sel); if (el) el.value = v; };

    const totals = () => {
      const trays = row.trays || [];
      const w = trays.reduce((s, t) => s + (parseFloat(t.weight) || 0), 0);
      const c2 = trays.reduce((s, t) => s + (parseFloat(t.cost) || 0), 0);
      q(".trtotal").textContent = trays.length
        ? `${w.toFixed(1)} g · ${c2.toFixed(2)} ${this._cur()}` : "";
    };

    const rescale = () => {
      const total = parseFloat(row.layers) || 0;
      const done = parseFloat(row.layers_done) || 0;
      // No completed-layer figure yet means "show the plan", not "times zero".
      const ratio = total > 0 && done > 0 ? Math.min(1, done / total) : 1;
      row.weight = Math.round(plan.weight * ratio * 1e3) / 1e3;
      row.length = Math.round(plan.length * ratio * 100) / 100;
      (row.trays || []).forEach((t, i) => {
        const p = (plan.trays || [])[i] || {};
        t.weight = Math.round((parseFloat(p.weight) || 0) * ratio * 1e3) / 1e3;
        t.cost = Math.round(t.weight / 1000 * (parseFloat(t.price) || 0) * 1e4) / 1e4;
        setVal(`[data-i="${i}"][data-tf="weight"]`, t.weight);
        setVal(`[data-i="${i}"][data-tf="cost"]`, t.cost);
      });
      row.f_cost = (row.trays || []).length
        ? Math.round(row.trays.reduce((s, t) => s + (parseFloat(t.cost) || 0), 0) * 1e4) / 1e4
        : Math.round(plan.f_cost * ratio * 1e4) / 1e4;
      row.cost = Math.round((row.f_cost + (parseFloat(row.p_cost) || 0)) * 1e4) / 1e4;
      setVal('[data-ff="weight"]', row.weight);
      setVal('[data-ff="length"]', row.length);
      setVal('[data-ff="f_cost"]', row.f_cost);
      setVal('[data-ff="cost"]', row.cost);
      totals();
    };

    ov.addEventListener("change", e => {
      const ff = e.target.closest("[data-ff]");
      if (ff) {
        const k = ff.dataset.ff;
        if (ff.classList.contains("num")) {
          row[k] = parseFloat(String(ff.value).replace(",", ".")) || 0;
        } else {
          row[k] = ff.value;
          if (k === "time") {
            const h = /(\d+)\s*h/i.exec(ff.value);
            const m = /(\d+)\s*min/i.exec(ff.value);
            if (h || m) row.mins = (h ? +h[1] * 60 : 0) + (m ? +m[1] : 0);
          }
        }
        if (failed && (k === "layers" || k === "layers_done")) rescale();
        else if (k === "f_cost" || k === "p_cost") {
          row.cost = Math.round(((parseFloat(row.f_cost) || 0)
            + (parseFloat(row.p_cost) || 0)) * 1e4) / 1e4;
          setVal('[data-ff="cost"]', row.cost);
        }
        return;
      }
      const tf = e.target.closest("[data-tf]");
      if (!tf) return;
      const t = (row.trays || [])[Number(tf.dataset.i)];
      if (!t) return;
      const f = tf.dataset.tf;
      if (f === "weight" || f === "price" || f === "cost") {
        t[f] = parseFloat(String(tf.value).replace(",", ".")) || 0;
        if (f !== "cost") {
          t.cost = Math.round((parseFloat(t.weight) || 0) / 1000 * (parseFloat(t.price) || 0) * 1e4) / 1e4;
          setVal(`[data-i="${tf.dataset.i}"][data-tf="cost"]`, t.cost);
        }
        // The row's filament figures follow the slots, like the logger's did.
        row.weight = Math.round(row.trays.reduce((s, x) => s + (parseFloat(x.weight) || 0), 0) * 1e3) / 1e3;
        row.f_cost = Math.round(row.trays.reduce((s, x) => s + (parseFloat(x.cost) || 0), 0) * 1e4) / 1e4;
        row.cost = Math.round((row.f_cost + (parseFloat(row.p_cost) || 0)) * 1e4) / 1e4;
        setVal('[data-ff="weight"]', row.weight);
        setVal('[data-ff="f_cost"]', row.f_cost);
        setVal('[data-ff="cost"]', row.cost);
        totals();
      } else {
        t[f] = tf.value;
      }
    });

    const snap = q("button.snap");
    if (snap) snap.addEventListener("click", async () => {
      snap.disabled = true;
      snap.textContent = "Capturing…";
      try {
        const resp = (await this._hass.callWS({
          type: "call_service", domain: "bambu_costs", service: "capture_cover",
          service_data: this._withEntry({ timestamp: String(row.ts || "") }),
          return_response: true,
        })).response;
        row.cover = resp.cover;
        const img = q(".fcover img");
        img.src = resp.url + "?t=" + Date.now();
        img.style.display = "";
        q(".fcap").textContent = "Captured — Save keeps this photo.";
        snap.textContent = "↻ Retake";
      } catch (err) {
        q(".fcap").textContent = "Capture failed: " + err.message;
        snap.textContent = "📷 Capture photo";
      }
      snap.disabled = false;
    });

    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    q("button.cancel").addEventListener("click", close);
    document.addEventListener("keydown", esc);

    q("button.fsave").addEventListener("click", async () => {
      const btn = q("button.fsave");
      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        await this._hass.callService("bambu_costs", "add_job", this._withEntry({
          row: {
            ts: String(row.ts || ""), job: String(row.job || ""),
            time: String(row.time || ""), mins: Number(row.mins) || 0,
            layers: Number(row.layers) || 0, layers_done: Number(row.layers_done) || 0,
            weight: Number(row.weight) || 0, length: Number(row.length) || 0,
            nozzle: String(row.nozzle || ""), nozzle_type: String(row.nozzle_type || ""),
            kwh: Number(row.kwh) || 0, f_cost: Number(row.f_cost) || 0,
            p_cost: Number(row.p_cost) || 0, cost: Number(row.cost) || 0,
            cover: String(row.cover || ""), types: String(row.types || ""),
            trays: Array.isArray(row.trays) ? row.trays : [],
            status: row.status,
          },
          capture_cover: true,
          update_totals: q(".ftot").checked,
        }));
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Save";
        q(".fcap").textContent = "Save failed: " + err.message;
        return;
      }
      close();
      this._msg(failed
        ? "Failed print logged."
          + (this._hideFailed ? " It is hidden by default — see ⚙ → Hide failed prints." : "")
        : "Job logged.");
      if (!this._dirty) {
        try {
          await this._hass.callService("homeassistant", "update_entity",
            { entity_id: this._cfg.entity });
          await this._sleep(1500);
          this._load();
          this._paint();
        } catch (err) { /* the next sensor refresh will bring it in */ }
      }
    });

    this.appendChild(ov);
    // A failure opens pre-scaled to the layers that finished; a finished
    // print is the plan as reported, so only the totals line needs drawing.
    if (failed) rescale(); else totals();
  }

  // ── image modal ──────────────────────────────────────────
  _openImage(src, caption) {
    const ov = document.createElement("div");
    ov.style.cssText = `position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.72);
      display:flex;align-items:center;justify-content:center;padding:24px;`;
    ov.innerHTML = `
      <div style="max-width:min(90vw,720px);background:var(--card-background-color,#fff);
        border-radius:14px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.5);">
        <img src="${src}" style="display:block;width:100%;height:auto;background:#8883;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;
          padding:12px 16px;font-size:13px;color:var(--primary-text-color,#000);">
          <span>${this._esc(caption)}</span>
          <a href="${src}" target="_blank" rel="noopener"
             style="color:var(--primary-color,#03a9f4);text-decoration:none;">Open ↗</a>
        </div>
      </div>`;
    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    ov.querySelector("img").addEventListener("error", () => { close(); window.open(src, "_blank"); });
    document.addEventListener("keydown", esc);
    document.body.appendChild(ov);
  }

  // ── shell ────────────────────────────────────────────────
  _render() {
    this.innerHTML = `
      <ha-card header="${this._esc(this._cfg.title)}">
        <style>
          .bcjt-wrap { padding:0 16px 16px; }
          .bcjt-tools { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
          .bcjt-tools input.f { flex:1; padding:7px 10px; border-radius:8px;
            border:1px solid var(--divider-color); background:var(--card-background-color);
            color:var(--primary-text-color); font-size:13px; }
          .tbtn { background:none; border:1px solid var(--divider-color);
            color:var(--primary-text-color); border-radius:8px; padding:6px 10px;
            font-size:12px; cursor:pointer; white-space:nowrap; }
          .tbtn:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .bcjt-msg { margin:8px 0; padding:8px 10px; border-radius:8px; font-size:12.5px;
            background:rgba(var(--rgb-primary-color),.12); display:none; }
          .bcjt-msg.warn { background:rgba(255,152,0,.18); }
          .bcjt-msg.err { background:rgba(244,67,54,.18); }
          .bcjt-scroll { overflow-x:auto; }
          table.bcjt { width:100%; border-collapse:collapse; font-size:12.5px; }
          table.bcjt th { text-align:left; font-weight:500; color:var(--secondary-text-color);
            font-size:11px; text-transform:uppercase; letter-spacing:.4px; white-space:nowrap;
            padding:6px 4px; border-bottom:1px solid var(--divider-color); user-select:none;
            /* Sticks when the wrapper is height-bounded. The shadow redraws
               the divider: collapsed borders do not travel with sticky cells.
               Opaque background, or rows show through while scrolled. */
            position:sticky; top:0; z-index:2;
            background:var(--ha-card-background, var(--card-background-color));
            box-shadow:0 1px 0 var(--divider-color); }
          table.bcjt th.stretch { width:99%; }
          table.bcjt th.s { cursor:pointer; }
          table.bcjt th.s:hover { color:var(--primary-text-color); }
          table.bcjt th.active { color:var(--primary-color); }
          table.bcjt td { padding:4px 3px; border-bottom:1px solid var(--divider-color);
            vertical-align:middle; }
          table.bcjt td.nw, table.bcjt th.nw { white-space:nowrap; }
          table.bcjt td.num { text-align:right; white-space:nowrap; }
          table.bcjt td.ctr { text-align:center; }
          table.bcjt td.ctr input.cell { text-align:center; }
          table.bcjt td.b input.cell { font-weight:600; }
          .muted { opacity:.5; }
          /* An input cannot size itself to its text, so a hidden twin does it:
             the wrapper is a one-cell grid holding the input and a ::after
             carrying the same text in the same font, and the wider of the two
             — always the text — sets the width. Pixel-accurate where the
             size attribute's character estimate kept clipping. */
          .grow { display:inline-grid; align-items:center; vertical-align:middle; }
          /* Twin and input must share the same font metrics or their widths
             drift and long values clip. font and letter-spacing are pinned on
             both, and the twin carries two trailing spaces plus wider right
             padding as slack for the drift a themed frontend still causes. */
          .grow::after { content:attr(data-v) " "; visibility:hidden; white-space:pre;
            grid-area:1/1; font:inherit; font-size:12.5px; letter-spacing:inherit;
            padding:4px 9px 4px 6px; border:1px solid transparent; }
          .grow input { grid-area:1/1; width:100%; box-sizing:border-box; min-width:0; }
          input.cell { padding:4px 6px; border-radius:7px;
            border:1px solid transparent; background:transparent;
            color:var(--primary-text-color); font:inherit; font-size:12.5px;
            letter-spacing:inherit; }
          .cu { font-size:11px; color:var(--secondary-text-color); margin-left:1px;
            white-space:nowrap; }
          table.bcjt td.cvr { text-align:center; padding:4px 8px; }
          .bcjt-dd { position:fixed; z-index:100000; background:var(--card-background-color);
            border:1px solid var(--divider-color); border-radius:8px; padding:4px 0;
            box-shadow:0 6px 20px rgba(0,0,0,.28); font-size:12.5px;
            max-height:40vh; overflow-y:auto; }
          .bcjt-dd .opt { padding:5px 12px; cursor:pointer; white-space:nowrap;
            color:var(--primary-text-color); }
          .bcjt-dd .opt:hover { background:rgba(var(--rgb-primary-color),.12); }
          .bcjt-dd .opt.on { color:var(--primary-color); font-weight:600; }
          input.cell:hover { border-color:var(--divider-color); }
          input.cell:focus { border-color:var(--primary-color);
            background:var(--card-background-color); outline:none; }
          input.cell.num { text-align:right; appearance:textfield; -moz-appearance:textfield; }
          input.cell.num::-webkit-outer-spin-button,
          input.cell.num::-webkit-inner-spin-button { -webkit-appearance:none; margin:0; }
          .tcost { opacity:.65; }
          .dot { display:inline-block; width:9px; height:9px; border-radius:2px;
            margin-right:4px; box-shadow:0 0 0 1px var(--secondary-text-color); }
          .trrow .trline { display:flex; gap:4px; align-items:center; margin:1px 0; }
          .trrow input.tin { padding:3px 6px; }
          .trrow .tsw { width:26px; height:26px; padding:0; border:none; background:none;
            border-radius:5px; cursor:pointer; flex:none;
            box-shadow:0 0 0 1px var(--divider-color); }
          .trnum { display:flex; flex-direction:column; align-items:flex-end; }
          button.trbtn { display:inline-flex; align-items:center; background:none;
            border:1px solid var(--divider-color); color:var(--primary-text-color);
            border-radius:7px; padding:4px 8px; font-size:11.5px; cursor:pointer;
            white-space:nowrap; }
          button.trbtn:hover { border-color:var(--primary-color); }
          button.cbtn { background:none; border:1px solid var(--divider-color);
            color:var(--primary-color); border-radius:7px; padding:4px 8px;
            font-size:11.5px; cursor:pointer; white-space:nowrap; }
          button.cbtn:hover { border-color:var(--primary-color); }
          .bcjt-foot { display:flex; justify-content:space-between; align-items:center;
            margin-top:12px; font-size:12px; color:var(--secondary-text-color); gap:12px;
            flex-wrap:wrap; }
          .bcjt-pager { display:flex; align-items:center; gap:6px; }
          .bcjt-pager button { background:none; border:1px solid var(--divider-color);
            color:var(--primary-text-color); border-radius:7px; padding:4px 10px;
            font-size:12px; cursor:pointer; }
          .bcjt-pager button[disabled] { opacity:.35; cursor:default; }
          button.save { background:var(--primary-color); color:var(--text-primary-color);
            border:none; border-radius:9px; padding:9px 18px; font-size:13px;
            font-weight:500; cursor:pointer; }
          button.save[disabled] { opacity:.4; cursor:default; }
          .bcjt-modal { position:fixed; inset:0; z-index:99999; background:rgba(0,0,0,.6);
            display:flex; align-items:center; justify-content:center; padding:20px; }
          .bcjt-sheet { width:min(94vw,400px); max-height:80vh; display:flex; flex-direction:column;
            background:var(--card-background-color); color:var(--primary-text-color);
            border:1px solid var(--divider-color); border-radius:14px; overflow:hidden;
            box-shadow:0 12px 48px rgba(0,0,0,.5); }
          .bcjt-sheet-head { padding:14px 16px 10px; border-bottom:1px solid var(--divider-color); }
          .bcjt-sheet-title { font-size:15px; font-weight:600; }
          .bcjt-sheet-body { overflow-y:auto; padding:6px 0; }
          .bcjt-target { display:flex; align-items:center; gap:10px; padding:8px 16px; }
          .bcjt-target + .bcjt-target { border-top:1px solid var(--divider-color); }
          .bcjt-target-label { flex:1; min-width:0; display:flex; flex-direction:column; }
          .bcjt-target-name { font-size:13px; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; }
          .bcjt-target-cur { font-size:11px; color:var(--secondary-text-color); }
          .bcjt-sheet-foot { padding:10px 16px; border-top:1px solid var(--divider-color);
            display:flex; justify-content:space-between; }
          .bcjt-sheet select { padding:5px 8px; border-radius:7px; font-size:12.5px;
            border:1px solid var(--divider-color); background:var(--card-background-color);
            color:var(--primary-text-color); }
          .tog { background:none; border:1px solid var(--divider-color); border-radius:6px;
            color:var(--secondary-text-color); font-size:9px; font-weight:600;
            letter-spacing:.3px; padding:4px 0; width:36px; cursor:pointer; }
          .tog:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .tog.isoff { border-color:var(--warning-color,#ff9800);
            color:var(--warning-color,#ff9800); }
          .arrows { display:flex; gap:2px; }
          .arrows button { background:none; border:1px solid var(--divider-color);
            color:var(--secondary-text-color); border-radius:6px; width:24px; height:24px;
            font-size:12px; line-height:1; padding:0; cursor:pointer; }
          .arrows button:hover { border-color:var(--primary-color); color:var(--primary-color); }
          /* A failed print reads as one at a glance: the faintest red wash. */
          table.bcjt tr.failed td { background:rgba(244,67,54,.05); }
          /* A staged deletion — struck through until Save actually removes it. */
          table.bcjt tr.deld td { opacity:.45; }
          table.bcjt tr.deld input.cell, table.bcjt tr.deld button.trbtn,
          table.bcjt tr.deld button.cbtn { text-decoration:line-through; pointer-events:none; }
          .del { background:none; border:none; color:var(--secondary-text-color);
            cursor:pointer; font-size:14px; padding:2px 4px; border-radius:6px; }
          .del:hover { color:var(--error-color,#f44336); }
          tr.deld .del { pointer-events:auto; text-decoration:none; opacity:1; }
          .lsplit { white-space:nowrap; }
          .lsplit input.cell { width:5ch; text-align:center; }
          .lsplit .sep { opacity:.6; }
          .fcover { display:flex; align-items:center; gap:10px; }
          .fcover img { width:64px; height:64px; object-fit:cover; border-radius:8px;
            box-shadow:0 0 0 1px var(--divider-color); }
        </style>
        <div class="bcjt-wrap">
          <div class="bcjt-tools">
            <input class="f" type="text" placeholder="Filter jobs…">
            <button class="tbtn addprint" title="Log a print by hand">+ Print</button>
            <button class="tbtn settings" title="Table settings">⚙</button>
            <button class="tbtn reload" title="Reload from file">↻</button>
          </div>
          <div class="bcjt-msg"></div>
          <div class="bcjt-scroll">
            <table class="bcjt">
              <thead><tr></tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div class="bcjt-foot">
            <span class="bcjt-count"></span>
            <div class="bcjt-pager">
              <button class="prev">‹ Prev</button>
              <span class="pg"></span>
              <button class="next">Next ›</button>
            </div>
            <span class="bcjt-actions">
              <button class="tbtn discard" style="display:none">Discard</button>
              <button class="save" disabled>Save</button>
            </span>
          </div>
        </div>
      </ha-card>`;

    this._built = true;

    this.querySelector("input.f").addEventListener("input", e => {
      this._filter = e.target.value.toLowerCase();
      this._page = 0;
      this._paint();
    });

    this.querySelector(".addprint").addEventListener("click", e =>
      this._toggleAddMenu(e.currentTarget));
    this.querySelector(".settings").addEventListener("click", () => this._openSettings());
    this.querySelector(".reload").addEventListener("click", () => this._reload());
    this.querySelector("button.save").addEventListener("click", () => this._save());
    this.querySelector("button.discard").addEventListener("click", () => {
      const n = this._edited.size;
      if (!confirm(`Discard ${n} unsaved edit${n === 1 ? "" : "s"}?`)) return;
      this._load();
      this._paint();
      this._msg("Changes discarded.");
    });

    this.querySelector("thead").addEventListener("click", e => {
      // A click that landed on a header sorts; nothing else lives up there.
      const th = e.target.closest("th.s");
      if (!th) return;
      const k = th.dataset.k;
      const col = BCJT_COLS.find(c => (c.sortKey || c.k) === k);
      // Numbers and dates read newest/biggest first; text alphabetically.
      const defDir = (k === "ts" || k === "mins" || (col && col.type === "num")) ? -1 : 1;
      if (this._sort.key === k) this._sort.dir *= -1;
      else this._sort = { key: k, dir: defDir };
      this._page = 0;
      this._paint();
    });

    this.querySelector(".prev").addEventListener("click", () => {
      if (this._page > 0) { this._page--; this._paint(); }
    });
    this.querySelector(".next").addEventListener("click", () => {
      const max = Math.max(0, Math.ceil(this._filtered().length / this._pageSize) - 1);
      if (this._page < max) { this._page++; this._paint(); }
    });

    this.querySelector("tbody").addEventListener("click", e => {
      const cover = e.target.closest("button.cbtn");
      if (cover) { this._openImage(cover.dataset.src, cover.dataset.cap); return; }
      const del = e.target.closest("button.del");
      if (del) {
        // Staged, not immediate: the row is struck through and the file only
        // changes on Save, so a mis-click is one more click to take back.
        const row = this._row(del.dataset.k);
        if (row) {
          row._del = !row._del;
          this._edited.add(row._k);
          this._dirty = true;
          this._paint();
        }
        return;
      }
      const trays = e.target.closest("button.trbtn");
      if (trays) {
        const row = this._row(trays.dataset.k);
        if (row) this._openTrays(row);
      }
    });

    // One delegated listener instead of one per input: the body repaints on
    // every sort, page and filter change.
    this.querySelector("tbody").addEventListener("change", e => {
      const inp = e.target.closest("input[data-f], select[data-f]");
      if (inp) this._edit(inp);
    });

    // Inputs grow and shrink with what is being typed, within the column's
    // bounds: the hidden twin (.grow::after) tracks the value live.
    this.querySelector("tbody").addEventListener("input", e => {
      const inp = e.target.closest(".grow input");
      if (!inp) return;
      const col = BCJT_COLS.find(c => c.k === inp.dataset.f);
      inp.parentElement.dataset.v = String(inp.value).slice(0, (col && col.max) || 40);
    });

    // The option popup for the nozzle combo cells: opens on focus, closes on
    // blur, Escape, or the table scrolling under it.
    const tbody = this.querySelector("tbody");
    tbody.addEventListener("focusin", e => {
      const inp = e.target.closest("input.combo");
      if (inp) this._openCombo(inp);
    });
    tbody.addEventListener("focusout", () => this._closeCombo());
    tbody.addEventListener("keydown", e => {
      if (e.key === "Escape") this._closeCombo();
    });
    this.querySelector(".bcjt-scroll").addEventListener("scroll", () => this._closeCombo());

    this._applyScrollMode();
    this._paint();
  }

  _openCombo(inp) {
    this._closeCombo();
    const f = inp.dataset.f;
    const opts = f === "nozzle" ? BCJT_NOZZLE_SIZES : BCJT_NOZZLE_TYPES;
    const label = v => f === "nozzle" ? v.replace(/^0(?=\.)/, "") : this._typeDisp(v);

    const dd = document.createElement("div");
    dd.className = "bcjt-dd";
    dd.innerHTML = opts.map(o => {
      const l = label(o);
      return `<div class="opt${l === inp.value ? " on" : ""}" data-v="${this._esc(l)}">${this._esc(l)}</div>`;
    }).join("");

    // mousedown, not click: click would blur the input first, and the
    // focusout close would eat the selection.
    dd.addEventListener("mousedown", e => {
      e.preventDefault();
      const opt = e.target.closest(".opt");
      if (!opt) return;
      inp.value = opt.dataset.v;
      this._closeCombo();
      inp.dispatchEvent(new Event("input", { bubbles: true }));
      inp.dispatchEvent(new Event("change", { bubbles: true }));
    });

    this.appendChild(dd);
    const r = inp.getBoundingClientRect();
    dd.style.left = r.left + "px";
    dd.style.minWidth = Math.max(r.width, 90) + "px";
    // Below the cell, unless that would run off the screen.
    const h = dd.offsetHeight;
    dd.style.top = (r.bottom + h + 4 > window.innerHeight ? r.top - h - 2 : r.bottom + 2) + "px";
    this._dd = dd;
  }

  _closeCombo() {
    if (this._dd) { this._dd.remove(); this._dd = null; }
  }

  _headHtml() {
    return this._cols().map(c => {
      const sk = c.sortKey || c.k;
      const on = c.sortable === false ? "" : "s";
      const active = on && this._sort.key === sk;
      const arrow = active ? (this._sort.dir === 1 ? " ▲" : " ▼") : "";
      // Units live in the cells, next to their values; the header is just
      // the label, on one line.
      const align = c.type === "num" ? "right" : c.center ? "center" : "";
      return `<th class="${on} ${active ? "active" : ""} ${c.stretch ? "stretch" : ""}"
        data-k="${sk}" ${align ? `style="text-align:${align}"` : ""}>${
        this._esc(c.t)}${arrow}</th>`;
    }).join("");
  }

  _cell(col, r) {
    if (col.type === "cover") {
      // min-width on every cell, the empty ones too, so the column does not
      // resize between pages; centred with its own padding so the slack sits
      // on BOTH sides of the button instead of all after it.
      const w = `style="min-width:${col.min || 11}ch"`;
      const f = r.cover;
      if (!f || f === "—") return `<td class="nw cvr" ${w}><span class="muted">—</span></td>`;
      const src = r.cover_url || (this._cfg.image_base + f);
      return `<td class="nw cvr" ${w}><button class="cbtn" data-src="${this._esc(src)}"
        data-cap="${this._esc(r.job || f)}" title="${this._esc(f)}">🖼 View</button></td>`;
    }
    if (col.type === "trays") return `<td class="nw">${this._traysCell(r)}</td>`;

    // A failed print's Layers cell carries both figures — how far it got over
    // how far it was going — each editable in place.
    if (col.k === "layers" && r.status === "failed") {
      const done = parseFloat(r.layers_done);
      const total = parseFloat(r.layers);
      return `<td class="num nw" title="Layers completed / total"><span class="lsplit"><input
        class="cell num" type="number" step="any" data-k="${r._k}" data-f="layers_done"
        value="${isNaN(done) ? "" : done}"><span class="sep">/</span><input
        class="cell num" type="number" step="any" data-k="${r._k}" data-f="layers"
        value="${isNaN(total) ? "" : total}"></span></td>`;
    }

    const cls = [col.type === "num" ? "num" : "", col.center ? "ctr" : "",
      col.nowrap ? "nw" : "", col.bold ? "b" : ""].filter(Boolean).join(" ");
    if (!col.edit) return `<td class="${cls}">${this._esc(r[col.k] ?? "—")}</td>`;

    if (col.k === "nozzle" || col.k === "nozzle_type") {
      const raw = String(r[col.k] ?? "").trim();
      const v = col.k === "nozzle" ? raw.replace(/^0(?=[.,])/, "") : this._typeDisp(raw);
      return `<td class="${cls}"><span class="grow" data-v="${this._twin(col, v)}"
        style="min-width:${col.min || 4}ch"><input class="cell combo" type="text"
        autocomplete="off" data-k="${r._k}" data-f="${col.k}" value="${this._esc(v)}"></span></td>`;
    }

    if (col.type === "num") {
      const n = parseFloat(r[col.k]);
      const v = isNaN(n) ? "" : n.toFixed(col.dp === undefined ? 0 : col.dp);
      const u = this._unit(col);
      return `<td class="${cls}"><span class="grow" data-v="${this._twin(col, v)}"
        style="min-width:${col.min || 4}ch"><input class="cell num"
        type="number" step="any" data-k="${r._k}" data-f="${col.k}" value="${v}"></span>${
        u ? `<span class="cu">${this._esc(u)}</span>` : ""}</td>`;
    }
    let v = String(r[col.k] ?? "");
    let title = "";
    // Bambu's nozzles are all sub-millimetre (0.2–0.8), so the leading zero
    // says nothing — ".4" reads cleaner. A 1.0+ value shows as-is, and the
    // stored data keeps the zero either way (the edit path restores it).
    if (col.k === "nozzle") v = v.replace(/^0(?=[.,])/, "");
    if (col.k === "types") {
      const short = this._typesDisp(v);
      if (short !== v) title = v;  // the tooltip keeps the full stored value
      v = short;
    }
    return `<td class="${cls}"><span class="grow" data-v="${this._twin(col, v)}"
      style="min-width:${col.min || 4}ch"><input class="cell"
      type="text" data-k="${r._k}" data-f="${col.k}" value="${this._esc(v)}"${
      title ? ` title="${this._esc(title)}"` : ""}></span></td>`;
  }

  // What the hidden twin measures. Capped at the column's maximum characters
  // rather than with max-width: the twin's text is incompressible by design
  // (that is what stops the table crushing the column), so a CSS clamp on the
  // box would not hold — a shorter measurement is the only cap that does.
  // A value past the cap scrolls inside its input instead of widening it.
  _twin(col, value) {
    return this._esc(String(value).slice(0, col.max || 40));
  }

  _edit(el) {
    const row = this._row(el.dataset.k);
    if (!row) return;
    const f = el.dataset.f;

    if (f === "layers_done" || BCJT_COLS.find(c => c.k === f && c.type === "num")) {
      row[f] = parseFloat(String(el.value).replace(",", ".")) || 0;
    } else if (f === "nozzle") {
      // The display drops the leading zero; the data never does.
      const t = el.value.trim().replace(",", ".");
      row[f] = t.startsWith(".") ? "0" + t : t;
    } else if (f === "nozzle_type") {
      // The combo shows pretty labels; a label (or the raw spelling, any
      // case) maps back to the printer's own value. Anything else is the
      // user's free text and is stored as typed.
      const t = el.value.trim();
      const hit = BCJT_NOZZLE_TYPES.find(o =>
        o.toLowerCase() === t.toLowerCase()
        || this._typeDisp(o).toLowerCase() === t.toLowerCase());
      row[f] = hit || t;
    } else {
      row[f] = el.value;
      // The minutes behind the print-time text are what sorting and the file
      // use, so an edited "2h 5min" must not leave the old duration behind.
      if (f === "time") {
        const h = /(\d+)\s*h/i.exec(el.value);
        const m = /(\d+)\s*min/i.exec(el.value);
        if (h || m) row.mins = (h ? +h[1] * 60 : 0) + (m ? +m[1] : 0);
      }
    }
    this._edited.add(row._k);
    this._dirty = true;
    this._updateFoot();
  }

  // ── body ─────────────────────────────────────────────────
  _paint() {
    const all = this._sorted();
    const pages = Math.max(1, Math.ceil(all.length / this._pageSize));
    if (this._page > pages - 1) this._page = pages - 1;
    const slice = all.slice(this._page * this._pageSize, (this._page + 1) * this._pageSize);
    const cols = this._cols();

    // The delete cell is structural, like the tags editor's: always last,
    // not a configurable column.
    this.querySelector("thead tr").innerHTML = this._headHtml() + "<th></th>";
    this.querySelector("tbody").innerHTML = slice.map(r => {
      const cls = [r.status === "failed" ? "failed" : "", r._del ? "deld" : ""]
        .filter(Boolean).join(" ");
      return `<tr data-k="${r._k}"${cls ? ` class="${cls}"` : ""}>${
        cols.map(c => this._cell(c, r)).join("")
      }<td class="nw"><button class="del" data-k="${r._k}" title="${
        r._del ? "Kept after all — click to undo the deletion" : "Delete this row (applied on Save)"
      }">${r._del ? "↩" : "🗑"}</button></td></tr>`;
    }).join("") || `<tr><td colspan="${cols.length + 1}"
      style="text-align:center;padding:24px" class="muted">No jobs logged yet</td></tr>`;

    this.querySelector(".pg").textContent = `${this._page + 1} / ${pages}`;
    this.querySelector(".prev").disabled = this._page === 0;
    this.querySelector(".next").disabled = this._page >= pages - 1;
    this._updateFoot(all.length);
  }

  _updateFoot(count) {
    const n = count === undefined ? this._filtered().length : count;
    const dels = this._rows.filter(r => r._del).length;
    const edits = this._edited.size - dels;
    this.querySelector(".bcjt-count").textContent =
      `${n} job${n === 1 ? "" : "s"}${this._filter ? " (filtered)" : ""}`
      + (this._hiddenFailed ? ` · ${this._hiddenFailed} failed hidden` : "")
      + (edits > 0 ? ` · ${edits} unsaved edit${edits === 1 ? "" : "s"}` : "")
      + (dels ? ` · ${dels} deletion${dels === 1 ? "" : "s"} pending` : "");
    const b = this.querySelector("button.save");
    if (b && !this._busy) { b.disabled = !this._dirty; b.textContent = "Save"; }
    const d = this.querySelector("button.discard");
    if (d) d.style.display = this._dirty && !this._busy ? "" : "none";
  }

  _msg(text, kind) {
    const m = this.querySelector(".bcjt-msg");
    if (!m) return;
    m.className = "bcjt-msg" + (kind ? " " + kind : "");
    m.textContent = text;
    m.style.display = text ? "block" : "none";
  }

  // ── settings ─────────────────────────────────────────────
  _openSettings() {
    const sortables = BCJT_COLS.filter(c => c.sortable !== false);

    const draw = () => `
      <div class="bcjt-target">
        <span class="bcjt-target-label">
          <span class="bcjt-target-name">Default sort</span>
          <span class="bcjt-target-cur">Applied now and on every load</span>
        </span>
        <select data-sortsel>${sortables.map(c => {
          const sk = c.sortKey || c.k;
          return `<option value="${sk}"${this._sort.key === sk ? " selected" : ""}>${this._esc(c.t)}</option>`;
        }).join("")}</select>
        <button class="tbtn" data-sortdir>${this._sort.dir === 1 ? "▲ asc" : "▼ desc"}</button>
      </div>
      <div class="bcjt-target">
        <span class="bcjt-target-label">
          <span class="bcjt-target-name">Rows per page</span>
        </span>
        <select data-pagesel>${
          (BCJT_PAGE_SIZES.includes(this._pageSize) ? BCJT_PAGE_SIZES
            : BCJT_PAGE_SIZES.concat(this._pageSize).sort((a, b) => a - b))
          .map(n => `<option value="${n}"${this._pageSize === n ? " selected" : ""}>${n}</option>`).join("")
        }</select>
      </div>
      <div class="bcjt-target">
        <span class="bcjt-target-label">
          <span class="bcjt-target-name">Table height</span>
          <span class="bcjt-target-cur">Bounded keeps the header and the bottom scrollbar on screen</span>
        </span>
        <select data-maxh>${BCJT_HEIGHTS.map(n =>
          `<option value="${n}"${this._maxH === n ? " selected" : ""}>${
            n ? n + "% of screen" : "Unlimited"}</option>`).join("")
        }</select>
      </div>
      <div class="bcjt-target">
        <span class="bcjt-target-label">
          <span class="bcjt-target-name">Hide failed prints</span>
          <span class="bcjt-target-cur">The footer still counts what is hidden</span>
        </span>
        <button class="tog${this._hideFailed ? "" : " isoff"}" data-hidefail>${
          this._hideFailed ? "ON" : "OFF"}</button>
      </div>
      <div class="bcjt-target"><span class="bcjt-target-label">
        <span class="bcjt-target-name" style="font-weight:600">Columns</span>
        <span class="bcjt-target-cur">Display only — a save always writes every field.</span>
      </span></div>
      ${this._order.map(key => {
        const col = BCJT_COLS.find(c => c.k === key);
        const on = !this._hidden.has(key);
        return `<div class="bcjt-target">
          <button class="tog${on ? "" : " isoff"}" data-toggle="${key}"
                  title="${on ? "Shown — click to hide" : "Hidden — click to show"}"
                  >${on ? "ON" : "OFF"}</button>
          <span class="bcjt-target-label"><span class="bcjt-target-name">${this._esc(col.t)}</span></span>
          <span class="arrows">
            <button class="cup" data-move="${key}">▲</button>
            <button class="cdown" data-move="${key}">▼</button>
          </span>
        </div>`;
      }).join("")}`;

    const ov = document.createElement("div");
    ov.className = "bcjt-modal";
    ov.innerHTML = `
      <div class="bcjt-sheet" role="dialog" aria-modal="true">
        <div class="bcjt-sheet-head">
          <div class="bcjt-sheet-title">Table settings</div>
        </div>
        <div class="bcjt-sheet-body"></div>
        <div class="bcjt-sheet-foot">
          <button class="tbtn reset">Reset</button>
          <button class="tbtn close">Done</button>
        </div>
      </div>`;

    const body = ov.querySelector(".bcjt-sheet-body");
    const render = () => {
      body.innerHTML = draw();
      body.querySelector("[data-sortsel]").addEventListener("change", e => {
        const k = e.target.value;
        const col = BCJT_COLS.find(c => (c.sortKey || c.k) === k);
        this._sort = { key: k, dir: (k === "ts" || k === "mins" || (col && col.type === "num")) ? -1 : 1 };
        this._page = 0;
        this._saveSettings(); render(); this._paint();
      });
      body.querySelector("[data-sortdir]").addEventListener("click", () => {
        this._sort.dir *= -1;
        this._saveSettings(); render(); this._paint();
      });
      body.querySelector("[data-pagesel]").addEventListener("change", e => {
        this._pageSize = Number(e.target.value) || this._cfg.page_size;
        this._page = 0;
        this._saveSettings(); this._paint();
      });
      body.querySelector("[data-maxh]").addEventListener("change", e => {
        this._maxH = Number(e.target.value) || 0;
        this._saveSettings(); this._applyScrollMode();
      });
      body.querySelector("[data-hidefail]").addEventListener("click", () => {
        this._hideFailed = !this._hideFailed;
        this._page = 0;
        this._saveSettings(); render(); this._paint();
      });
      body.querySelectorAll("[data-toggle]").forEach(b => {
        b.addEventListener("click", e => {
          const key = e.currentTarget.dataset.toggle;
          if (this._hidden.has(key)) this._hidden.delete(key); else this._hidden.add(key);
          this._saveSettings(); render(); this._paint();
        });
      });
      body.querySelectorAll("[data-move]").forEach(b => {
        b.addEventListener("click", e => {
          const key = e.currentTarget.dataset.move;
          const dir = e.currentTarget.classList.contains("cup") ? -1 : 1;
          const i = this._order.indexOf(key);
          const j = i + dir;
          if (i < 0 || j < 0 || j >= this._order.length) return;
          this._order.splice(j, 0, this._order.splice(i, 1)[0]);
          this._saveSettings(); render(); this._paint();
        });
      });
    };
    render();

    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    ov.querySelector("button.close").addEventListener("click", close);
    ov.querySelector("button.reset").addEventListener("click", () => {
      this._order = BCJT_DEFAULT_ORDER.slice();
      this._hidden = new Set();
      this._sort = { key: "ts", dir: -1 };
      this._pageSize = this._cfg.page_size;
      this._maxH = 70;
      this._hideFailed = true;
      this._page = 0;
      this._saveSettings(); render(); this._paint(); this._applyScrollMode();
    });
    document.addEventListener("keydown", esc);
    this.appendChild(ov);
  }

  // ── persistence ──────────────────────────────────────────
  _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  async _reload() {
    if (this._dirty && !confirm("Discard unsaved edits and reload from the file?")) return;
    this._busy = true;
    this._msg("Refreshing from file…");
    try {
      await this._hass.callService("homeassistant", "update_entity",
        { entity_id: this._cfg.entity });
      await this._sleep(1500);
    } catch (err) {
      this._msg("Could not refresh: " + err, "err");
    }
    this._busy = false;
    this._load();
    this._paint();
    this._msg("Reloaded.");
  }

  _payload() {
    // Only the rows actually touched: the service matches them into the file
    // by orig_ts, so everything else — including rows past the sensor's
    // window and a job logged while editing — stays exactly as it was.
    return this._rows.filter(r => this._edited.has(r._k)).map(r => r._del ? {
      orig_ts: r.orig_ts, delete: true,
    } : ({
      orig_ts: r.orig_ts,
      ts: String(r.ts || ""),
      job: String(r.job || ""),
      time: String(r.time || ""),
      mins: Number(r.mins) || 0,
      layers: Number(r.layers) || 0,
      weight: Number(r.weight) || 0,
      length: Number(r.length) || 0,
      nozzle: String(r.nozzle || ""),
      nozzle_type: String(r.nozzle_type || ""),
      kwh: Number(r.kwh) || 0,
      f_cost: Number(r.f_cost) || 0,
      p_cost: Number(r.p_cost) || 0,
      cost: Number(r.cost) || 0,
      cover: String(r.cover || ""),
      types: String(r.types || ""),
      trays: Array.isArray(r.trays) ? r.trays : [],
      layers_done: Number(r.layers_done) || 0,
      status: String(r.status || "success"),
    }));
  }

  async _save() {
    if (!this._dirty || this._busy) return;
    const btn = this.querySelector("button.save");
    this._busy = true;
    btn.disabled = true;
    btn.textContent = "Checking…";
    this._msg("Checking the file hasn't changed…");

    try {
      await this._hass.callService("homeassistant", "update_entity",
        { entity_id: this._cfg.entity });
      await this._sleep(1500);

      if (JSON.stringify(this._sensorData()) !== this._baseSig) {
        this._msg("The log changed on disk (a job was probably just logged). "
          + "Press ↻ to reload and redo your edits — nothing was written.", "warn");
        this._busy = false;
        btn.textContent = "Save";
        btn.disabled = false;
        return;
      }

      btn.textContent = "Saving…";
      this._msg("Writing the job log…");
      const [domain, service] = this._cfg.save_service.split(".");
      await this._hass.callService(domain, service, this._withEntry({ rows: this._payload() }));
    } catch (err) {
      this._msg("Save failed: " + err, "err");
      this._busy = false;
      btn.textContent = "Save";
      btn.disabled = false;
      return;
    }

    // What is on screen IS what was just written. The saved timestamps are
    // the rows' identity from here on, so adopt them before the sensor's
    // refresh lands (_justSaved makes that refresh the new baseline); the
    // deleted rows are gone from the file, so they leave the table too.
    const dels = this._rows.filter(r => r._del).length;
    const saved = this._edited.size - dels;
    this._rows = this._rows.filter(r => !r._del);
    for (const r of this._rows) if (this._edited.has(r._k)) r.orig_ts = String(r.ts || "");
    this._busy = false;
    this._dirty = false;
    this._justSaved = true;
    this._edited = new Set();
    this._paint();
    this._msg(`Saved ${saved} row${saved === 1 ? "" : "s"}`
      + (dels ? `, deleted ${dels}` : "")
      + ". Previous version kept as jobs.csv.bak.");
  }
}

// Defensive: a card loaded twice (stale resource plus new one) would
// otherwise throw on the second define and register nothing at all.
if (!customElements.get("bambu-costs-jobs-table")) customElements.define("bambu-costs-jobs-table", BambuCostsJobsTable);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "bambu-costs-jobs-table")) window.customCards.push({
  type: "bambu-costs-jobs-table",
  name: "Bambu Costs: Jobs Table",
  description: "Editable print job history with configurable columns",
});
