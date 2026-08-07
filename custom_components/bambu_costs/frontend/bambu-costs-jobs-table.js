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
  { k: "nozzle",      t: "Nozzle",        type: "text", edit: true, min: 2, max: 6 },
  { k: "nozzle_type", t: "Nozzle type",   type: "text", edit: true, min: 6, max: 26 },
  { k: "kwh",         t: "Energy",        type: "num",  edit: true, unit: "kWh", dp: 3 },
  { k: "f_cost",      t: "Filament",      type: "num",  edit: true, unit: "$",   dp: 2 },
  { k: "p_cost",      t: "Power",         type: "num",  edit: true, unit: "$",   dp: 2 },
  { k: "cost",        t: "Total",         type: "num",  edit: true, unit: "$",   dp: 2, bold: true },
  { k: "types",       t: "Material",      type: "text", edit: true, min: 6, max: 30 },
  { k: "cover",       t: "Image",         type: "cover", sortable: false },
  { k: "trays",       t: "Filament used", type: "trays", sortable: false },
];
const BCJT_DEFAULT_ORDER = BCJT_COLS.map(c => c.k);
const BCJT_PAGE_SIZES = [10, 20, 50, 100];

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
    if (!this._cfg.currency) {
      const st = hass.states[this._cfg.entity];
      this._cfg.currency = (st && st.attributes && st.attributes.currency) || "€";
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
    } catch (e) { /* corrupt or unavailable — fall back to defaults */ }
  }

  _saveSettings() {
    try {
      localStorage.setItem(this._settingsKey(), JSON.stringify({
        order: this._order, hidden: [...this._hidden],
        sortKey: this._sort.key, sortDir: this._sort.dir, pageSize: this._pageSize,
      }));
    } catch (e) { /* private mode — layout just will not persist */ }
  }

  // ── helpers ──────────────────────────────────────────────
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

  _unit(col) {
    return col.unit === "$" ? this._cfg.currency : col.unit;
  }

  // ── view pipeline ────────────────────────────────────────
  _filtered() {
    const q = this._filter;
    if (!q) return this._rows;
    return this._rows.filter(r => {
      const trays = (r.trays || []).map(t => `${t.label} ${t.type || ""} ${t.name}`).join(" ");
      return `${r.ts} ${r.job} ${r.nozzle} ${r.nozzle_type} ${r.types} ${trays}`
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
    const tip = this._esc(trays.map(t =>
      `${t.label || "?"}${t.type ? " " + t.type : ""} ${(parseFloat(t.weight) || 0).toFixed(1)} g`
    ).join("\n"));
    return `<button class="trbtn" data-k="${r._k}" title="${tip}">${dots}` +
      `${trays.length} slot${trays.length === 1 ? "" : "s"} · ${total.toFixed(1)} g</button>`;
  }

  _openTrays(r) {
    const trays = Array.isArray(r.trays) ? r.trays : [];
    const totalW = trays.reduce((s, t) => s + (parseFloat(t.weight) || 0), 0);
    const totalC = trays.reduce((s, t) => s + (parseFloat(t.cost) || 0), 0);
    const cur = this._esc(this._cfg.currency);

    const rows = trays.map(t => {
      const rgb = this._parseColor(t.color || "");
      const dot = rgb ? `<i class="dot dotb" style="background:${this._css(rgb)}"></i>` : "";
      const price = isNaN(parseFloat(t.price)) ? "" : `@ ${parseFloat(t.price).toFixed(2)} ${cur}/kg`;
      const cost = isNaN(parseFloat(t.cost)) ? "" : `${parseFloat(t.cost).toFixed(2)} ${cur}`;
      const weight = isNaN(parseFloat(t.weight)) ? "" : `${parseFloat(t.weight).toFixed(2)} g`;
      return `<div class="bcjt-target">
        ${dot}
        <span class="bcjt-target-label">
          <span class="bcjt-target-name">${this._esc(t.label || "?")}${
            t.type ? ` — ${this._esc(t.type)}` : ""}</span>
          <span class="bcjt-target-cur">${this._esc(t.name || "")}${
            t.name && price ? " " : ""}${this._esc(price)}</span>
        </span>
        <span class="trnum">${weight}<br><span class="tcost">${cost}</span></span>
      </div>`;
    }).join("") || `<div class="bcjt-target"><span class="muted">No per-slot data</span></div>`;

    const ov = document.createElement("div");
    ov.className = "bcjt-modal";
    ov.innerHTML = `
      <div class="bcjt-sheet" role="dialog" aria-modal="true">
        <div class="bcjt-sheet-head">
          <div class="bcjt-sheet-title">Filament used</div>
          <div class="bcjt-target-cur">${this._esc(r.job || "")}${r.ts ? ` · ${this._esc(r.ts)}` : ""}</div>
        </div>
        <div class="bcjt-sheet-body">${rows}</div>
        <div class="bcjt-sheet-foot">
          <span style="align-self:center">${totalW.toFixed(1)} g · ${totalC.toFixed(2)} ${cur}</span>
          <button class="tbtn close">Done</button>
        </div>
      </div>`;

    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    ov.querySelector("button.close").addEventListener("click", close);
    document.addEventListener("keydown", esc);
    this.appendChild(ov);
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
            font-size:11px; text-transform:uppercase; letter-spacing:.4px; white-space:normal;
            vertical-align:bottom; padding:6px 4px; border-bottom:1px solid var(--divider-color);
            user-select:none; }
          table.bcjt th .u { display:block; font-size:9px; letter-spacing:0;
            text-transform:none; opacity:.75; }
          table.bcjt th.stretch { width:99%; }
          table.bcjt th.s { cursor:pointer; }
          table.bcjt th.s:hover { color:var(--primary-text-color); }
          table.bcjt th.active { color:var(--primary-color); }
          table.bcjt td { padding:4px 3px; border-bottom:1px solid var(--divider-color);
            vertical-align:middle; }
          table.bcjt td.nw, table.bcjt th.nw { white-space:nowrap; }
          table.bcjt td.num { text-align:right; white-space:nowrap; }
          table.bcjt td.b input.cell { font-weight:600; }
          .muted { opacity:.5; }
          /* An input cannot size itself to its text, so a hidden twin does it:
             the wrapper is a one-cell grid holding the input and a ::after
             carrying the same text in the same font, and the wider of the two
             — always the text — sets the width. Pixel-accurate where the
             size attribute's character estimate kept clipping. */
          .grow { display:inline-grid; align-items:center; }
          /* Twin and input must share the exact same font, or their widths
             drift a few pixels apart and long values clip by a hair. */
          .grow::after { content:attr(data-v) " "; visibility:hidden; white-space:pre;
            grid-area:1/1; font:inherit; font-size:12.5px; padding:4px 6px;
            border:1px solid transparent; }
          .grow input { grid-area:1/1; width:100%; box-sizing:border-box; min-width:0; }
          input.cell { padding:4px 6px; border-radius:7px;
            border:1px solid transparent; background:transparent;
            color:var(--primary-text-color); font:inherit; font-size:12.5px; }
          input.cell:hover { border-color:var(--divider-color); }
          input.cell:focus { border-color:var(--primary-color);
            background:var(--card-background-color); outline:none; }
          input.cell.num { text-align:right; appearance:textfield; -moz-appearance:textfield; }
          input.cell.num::-webkit-outer-spin-button,
          input.cell.num::-webkit-inner-spin-button { -webkit-appearance:none; margin:0; }
          .tcost { opacity:.65; }
          .dot { display:inline-block; width:9px; height:9px; border-radius:2px;
            margin-right:4px; box-shadow:0 0 0 1px var(--secondary-text-color); }
          .dot.dotb { width:14px; height:14px; border-radius:4px; margin:0; flex:none; }
          button.trbtn { display:inline-flex; align-items:center; background:none;
            border:1px solid var(--divider-color); color:var(--primary-text-color);
            border-radius:7px; padding:4px 8px; font-size:11.5px; cursor:pointer;
            white-space:nowrap; }
          button.trbtn:hover { border-color:var(--primary-color); }
          .trnum { text-align:right; font-size:12px; white-space:nowrap; }
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
        </style>
        <div class="bcjt-wrap">
          <div class="bcjt-tools">
            <input class="f" type="text" placeholder="Filter jobs…">
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
            <button class="save" disabled>Save</button>
          </div>
        </div>
      </ha-card>`;

    this._built = true;

    this.querySelector("input.f").addEventListener("input", e => {
      this._filter = e.target.value.toLowerCase();
      this._page = 0;
      this._paint();
    });

    this.querySelector(".settings").addEventListener("click", () => this._openSettings());
    this.querySelector(".reload").addEventListener("click", () => this._reload());
    this.querySelector("button.save").addEventListener("click", () => this._save());

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
      const trays = e.target.closest("button.trbtn");
      if (trays) {
        const row = this._row(trays.dataset.k);
        if (row) this._openTrays(row);
      }
    });

    // One delegated listener instead of one per input: the body repaints on
    // every sort, page and filter change.
    this.querySelector("tbody").addEventListener("change", e => {
      const inp = e.target.closest("input[data-f]");
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

    this._paint();
  }

  _headHtml() {
    return this._cols().map(c => {
      const sk = c.sortKey || c.k;
      const on = c.sortable === false ? "" : "s";
      const active = on && this._sort.key === sk;
      const arrow = active ? (this._sort.dir === 1 ? " ▲" : " ▼") : "";
      const u = this._unit(c);
      // The unit sits under the label instead of beside it, so a column of
      // short numbers is not held open by a long one-line header.
      return `<th class="${on} ${active ? "active" : ""} ${c.stretch ? "stretch" : ""}"
        data-k="${sk}" ${c.type === "num" ? 'style="text-align:right"' : ""}>${
        this._esc(c.t)}${arrow}${u ? `<span class="u">(${this._esc(u)})</span>` : ""}</th>`;
    }).join("");
  }

  _cell(col, r) {
    if (col.type === "cover") {
      const f = r.cover;
      if (!f || f === "—") return `<td><span class="muted">—</span></td>`;
      const src = r.cover_url || (this._cfg.image_base + f);
      return `<td class="nw"><button class="cbtn" data-src="${this._esc(src)}"
        data-cap="${this._esc(r.job || f)}" title="${this._esc(f)}">🖼 View</button></td>`;
    }
    if (col.type === "trays") return `<td class="nw">${this._traysCell(r)}</td>`;

    const cls = [col.type === "num" ? "num" : "", col.nowrap ? "nw" : "", col.bold ? "b" : ""]
      .filter(Boolean).join(" ");
    if (!col.edit) return `<td class="${cls}">${this._esc(r[col.k] ?? "—")}</td>`;

    if (col.type === "num") {
      const n = parseFloat(r[col.k]);
      const v = isNaN(n) ? "" : n.toFixed(col.dp === undefined ? 0 : col.dp);
      return `<td class="${cls}"><span class="grow" data-v="${this._twin(col, v)}"
        style="min-width:${col.min || 4}ch"><input class="cell num"
        type="number" step="any" data-k="${r._k}" data-f="${col.k}" value="${v}"></span></td>`;
    }
    const v = String(r[col.k] ?? "");
    return `<td class="${cls}"><span class="grow" data-v="${this._twin(col, v)}"
      style="min-width:${col.min || 4}ch"><input class="cell"
      type="text" data-k="${r._k}" data-f="${col.k}" value="${this._esc(v)}"></span></td>`;
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
    if (BCJT_COLS.find(c => c.k === f && c.type === "num")) {
      row[f] = parseFloat(String(el.value).replace(",", ".")) || 0;
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

    this.querySelector("thead tr").innerHTML = this._headHtml();
    this.querySelector("tbody").innerHTML = slice.map(r =>
      `<tr data-k="${r._k}">${cols.map(c => this._cell(c, r)).join("")}</tr>`
    ).join("") || `<tr><td colspan="${cols.length}"
      style="text-align:center;padding:24px" class="muted">No jobs logged yet</td></tr>`;

    this.querySelector(".pg").textContent = `${this._page + 1} / ${pages}`;
    this.querySelector(".prev").disabled = this._page === 0;
    this.querySelector(".next").disabled = this._page >= pages - 1;
    this._updateFoot(all.length);
  }

  _updateFoot(count) {
    const n = count === undefined ? this._filtered().length : count;
    this.querySelector(".bcjt-count").textContent =
      `${n} job${n === 1 ? "" : "s"}${this._filter ? " (filtered)" : ""}`
      + (this._dirty ? ` · ${this._edited.size} unsaved edit${this._edited.size === 1 ? "" : "s"}` : "");
    const b = this.querySelector("button.save");
    if (b && !this._busy) { b.disabled = !this._dirty; b.textContent = "Save"; }
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
      this._page = 0;
      this._saveSettings(); render(); this._paint();
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
    return this._rows.filter(r => this._edited.has(r._k)).map(r => ({
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
      await this._hass.callService(domain, service, { rows: this._payload() });
    } catch (err) {
      this._msg("Save failed: " + err, "err");
      this._busy = false;
      btn.textContent = "Save";
      btn.disabled = false;
      return;
    }

    // What is on screen IS what was just written. The saved timestamps are
    // the rows' identity from here on, so adopt them before the sensor's
    // refresh lands (_justSaved makes that refresh the new baseline).
    const saved = this._edited.size;
    for (const r of this._rows) if (this._edited.has(r._k)) r.orig_ts = String(r.ts || "");
    this._busy = false;
    this._dirty = false;
    this._justSaved = true;
    this._edited = new Set();
    this._updateFoot();
    this._msg(`Saved ${saved} row${saved === 1 ? "" : "s"}. Previous version kept as jobs.csv.bak.`);
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
