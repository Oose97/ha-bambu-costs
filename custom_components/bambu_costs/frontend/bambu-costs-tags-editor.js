// Every configurable column. The grip, the ON/OFF toggle and the delete button
// are structural and always present, so they are not listed here.
const BTE_COLS = [
  { key: "swatch",     label: "",         width: "34px",  tight: true },
  { key: "filament",   label: "Filament" },
  { key: "hex",        label: "Hex",      width: "100px" },
  { key: "color_name", label: "Color" },
  { key: "serial",     label: "Serial",   width: "150px" },
  { key: "serial_2",   label: "Serial 2", width: "150px" },
  { key: "price",      label: "PRICE",    width: "120px", tight: true },
];
const BTE_DEFAULT_ORDER = BTE_COLS.map(c => c.key);

class BambuCostsTagsEditor extends HTMLElement {
  setConfig(cfg) {
    if (!cfg.entity) throw new Error("Define an entity (sensor.bambu_costs_tag_library)");
    this._cfg = Object.assign({
      title: "Filament tags",
      save_service: "bambu_costs.write_tags",
      default_price_entity: "number.bambu_costs_default_filament_price",
      unit: null,      // null → take the currency from the integration
    }, cfg);
    this._rows = [];
    this._baseSig = null;
    this._dirty = false;
    this._justSaved = false;
    this._filter = "";
    this._showDisabled = false;
    // A pair renders as one spool row with its second tag as a child row.
    // The default state is a persisted setting; per-spool toggles are kept as
    // deviations from it, so a newly formed pair follows the default.
    this._expandDefault = false;
    this._expandOverrides = new Set();
    this._nextKey = 1;
    // Display only. The payload sent on save always carries every field in
    // its canonical order, so hiding or reordering a column here can never
    // change what is written.
    this._order = BTE_DEFAULT_ORDER.slice();
    this._hidden = new Set();
    this._restoreCols();
    this._built = false;
    this._busy = false;
    this._mode = (window.matchMedia && window.matchMedia("(pointer: coarse)").matches)
      ? "arrows" : "drag";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._cfg.unit) {
      const st = hass.states[this._cfg.entity];
      const cur = st && st.attributes && st.attributes.currency;
      this._cfg.unit = cur ? `${cur}/kg` : "EUR/kg";
    }
    if (!this._built) { this._load(); this._render(); return; }
    if (this._busy) return;
    const sig = JSON.stringify(this._sensorData());
    if (sig === this._baseSig) return;

    if (this._justSaved) {
      // Our own write coming back from the sensor, not an external change:
      // adopt it as the new baseline. The table already shows exactly this
      // data, so there is nothing to revert to or flash through.
      this._justSaved = false;
      this._baseSig = sig;
      if (!this._dirty) { this._load(); this._paint(); }
      return;
    }

    if (this._dirty) return;
    this._load();
    // Repaint rather than rebuild: a full render would wipe the filter box
    // and any status banner just because a tag was scanned in the background.
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
    this._rows = d.map(r => ({
      _k: this._nextKey++,
      filament: r.filament || "",
      color_code: this._norm(r.color_code),
      color_name: r.color_name || "",
      serial: r.serial || "",
      serial_2: r.serial_2 || "",
      cost_per_kg: Number(r.cost_per_kg) || 0,
      disabled: this._isDisabled(r.disabled),
    }));
    this._rows = this._grouped();
    this._dirty = false;
  }

  // ── spool pairs ──────────────────────────────────────────────────────────
  // A spool carries a tag on each side. When one row names the other's serial
  // they are two halves of the same spool, and are kept adjacent and moved
  // together so they cannot drift apart in the list.
  _groups() {
    const bySerial = new Map();
    for (const r of this._rows) {
      const s = String(r.serial || "").trim().toLowerCase();
      if (s) bySerial.set(s, r);
    }
    const seen = new Set();
    const groups = [];
    for (const r of this._rows) {
      if (seen.has(r._k)) continue;
      seen.add(r._k);
      const group = [r];
      const other = String(r.serial_2 || "").trim().toLowerCase();
      const partner = other ? bySerial.get(other) : null;
      if (partner && partner !== r && !seen.has(partner._k)) {
        seen.add(partner._k);
        group.push(partner);
      }
      groups.push(group);
    }
    return groups;
  }

  _grouped() { return this._groups().flat(); }

  _groupOf(k) {
    return this._groups().find(g => g.some(r => r._k === Number(k))) || [];
  }

  _payload() {
    return this._rows.map(r => ({
      filament: this._clean(r.filament),
      color_code: this._clean(r.color_code),
      color_name: this._clean(r.color_name),
      serial: this._clean(r.serial),
      serial_2: this._clean(r.serial_2),
      cost_per_kg: Number(r.cost_per_kg) || 0,
      disabled: !!r.disabled,
    }));
  }

  // ── column configuration ─────────────────────────────────────────────────
  _colsKey() { return `bambu-costs-tags-cols:${this._cfg.entity}`; }

  _restoreCols() {
    try {
      const raw = localStorage.getItem(this._colsKey());
      if (!raw) return;
      const s = JSON.parse(raw);
      if (Array.isArray(s.order)) {
        // Keep only keys that still exist, then append any newly added column
        // so an upgrade never silently drops one.
        const known = new Set(BTE_DEFAULT_ORDER);
        const order = s.order.filter(k => known.has(k));
        for (const k of BTE_DEFAULT_ORDER) if (!order.includes(k)) order.push(k);
        this._order = order;
      }
      if (Array.isArray(s.hidden)) this._hidden = new Set(s.hidden);
      if (typeof s.expandDefault === "boolean") this._expandDefault = s.expandDefault;
    } catch (e) { /* corrupt or unavailable — fall back to defaults */ }
  }

  _saveCols() {
    try {
      localStorage.setItem(this._colsKey(),
        JSON.stringify({ order: this._order, hidden: [...this._hidden],
                         expandDefault: this._expandDefault }));
    } catch (e) { /* private mode — layout just will not persist */ }
  }

  // ── pair expansion ───────────────────────────────────────────────────────
  _groupSig(group) {
    return String(group[0].serial || group[0]._k).trim().toLowerCase();
  }

  _isExpanded(sig) {
    return this._expandOverrides.has(sig) ? !this._expandDefault : this._expandDefault;
  }

  _toggleExpand(sig) {
    if (this._expandOverrides.has(sig)) this._expandOverrides.delete(sig);
    else this._expandOverrides.add(sig);
    this._paint();
  }

  _cols() {
    return this._order
      .map(k => BTE_COLS.find(c => c.key === k))
      .filter(c => c && !this._hidden.has(c.key));
  }

  _row(k) { return this._rows.find(r => r._k === Number(k)); }

  // 6th CSV column is optional — anything missing/blank/unrecognised means enabled.
  _isDisabled(v) {
    if (typeof v === "boolean") return v;
    const s = String(v == null ? "" : v).trim().toLowerCase();
    return s === "disabled" || s === "1" || s === "true" || s === "yes";
  }

  _disabledCount() { return this._rows.filter(r => r.disabled).length; }

  // The integration writes the CSV with a real writer, so commas and quotes no
  // longer have to be stripped here — only newlines, which have no place in a cell.
  _clean(v) { return String(v == null ? "" : v).replace(/[\r\n]/g, " ").trim(); }

  _norm(v) {
    const m = String(v || "").match(/([0-9a-f]{6})/i);
    return m ? "#" + m[1].toUpperCase() : "#808080";
  }

  // ── colors ───────────────────────────────────────────────
  _parseColor(s) {
    if (!s) return null;
    s = String(s).trim();
    let m = s.match(/^#?([0-9a-f]{6})/i);
    if (m) return [parseInt(m[1].slice(0,2),16), parseInt(m[1].slice(2,4),16), parseInt(m[1].slice(4,6),16)];
    m = s.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/i);
    if (m) return [+m[1], +m[2], +m[3]];
    return null;
  }

  _lum(r, g, b) {
    const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  }

  _contrast(a, b) { return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); }

  _css(rgb) {
    return "#" + rgb.map(v => Math.max(0, Math.min(255, v)).toString(16)
      .padStart(2, "0")).join("").toUpperCase();
  }

  _bg() {
    const cs = getComputedStyle(this);
    let c = this._parseColor(cs.getPropertyValue("--ha-card-background"))
         || this._parseColor(cs.getPropertyValue("--card-background-color"))
         || this._parseColor(cs.getPropertyValue("--primary-background-color"));
    if (c) return c;

    const card = this.querySelector("ha-card");
    if (card) {
      const cc = getComputedStyle(card).backgroundColor;
      if (cc && cc !== "transparent" && cc.indexOf("rgba(0, 0, 0, 0)") !== 0) {
        c = this._parseColor(cc);
        if (c) return c;
      }
    }

    const t = this._parseColor(cs.getPropertyValue("--primary-text-color"));
    if (t) return this._lum(...t) > 0.5 ? [0, 0, 0] : [255, 255, 255];

    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
      return [0, 0, 0];
    return [255, 255, 255];
  }

  connectedCallback() {
    requestAnimationFrame(() => this._recolor());
    setTimeout(() => this._recolor(), 400);
  }

  _recolor() {
    if (!this._built) return;
    const bg = this._bg();
    this.style.setProperty("--bte-ring", this._css(this._readable(bg, bg, 2.5)));
    this.querySelectorAll("input.hx").forEach(inp => {
      const row = this._row(inp.dataset.k);
      inp.style.color = this._textFor(row ? row.color_code : inp.value, bg);
    });
  }

  _readable(rgb, bg, min) {
    const bl = this._lum(...bg);
    const tgt = bl > 0.45 ? [0, 0, 0] : [255, 255, 255];
    let out = rgb.slice();
    for (let t = 0; t <= 1.0001; t += 0.04) {
      out = rgb.map((v, i) => Math.round(v + (tgt[i] - v) * t));
      if (this._contrast(this._lum(...out), bl) >= min) break;
    }
    return out;
  }

  _textFor(code, bg) {
    const rgb = this._parseColor(code);
    return rgb ? this._css(this._readable(rgb, bg, 4)) : "var(--primary-text-color)";
  }

  _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ── render ───────────────────────────────────────────────
  _render() {
    const bg = this._bg();
    const ring = this._css(this._readable(bg, bg, 2.5));

    this.innerHTML = `
      <ha-card header="${this._esc(this._cfg.title)}">
        <style>
          .bte-wrap { padding: 0 16px 16px; }
          .bte-tools { display:flex; gap:6px; align-items:center; margin-bottom:10px; flex-wrap:wrap; }
          .bte-tools input.f { flex:1; min-width:140px; padding:7px 10px; border-radius:8px;
            border:1px solid var(--divider-color); background:var(--card-background-color);
            color:var(--primary-text-color); font-size:13px; }
          .tbtn { background:none; border:1px solid var(--divider-color);
            color:var(--primary-text-color); border-radius:8px; padding:6px 10px;
            font-size:12px; cursor:pointer; white-space:nowrap; }
          .tbtn:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .tbtn.on { border-color:var(--primary-color); color:var(--primary-color);
            background:rgba(var(--rgb-primary-color),.12); }
          .bte-msg { margin:8px 0; padding:8px 10px; border-radius:8px; font-size:12.5px;
            background:rgba(var(--rgb-primary-color),.12); display:none; }
          .bte-msg.warn { background:rgba(255,152,0,.18); }
          .bte-msg.err { background:rgba(244,67,54,.18); }
          .bte-scroll { overflow-x:auto; }
          table.bte { width:100%; border-collapse:collapse; font-size:13px; }
          table.bte th { text-align:left; font-weight:500; color:var(--secondary-text-color);
            font-size:11px; text-transform:uppercase; letter-spacing:.4px; white-space:nowrap;
            padding:4px 13px; border-bottom:1px solid var(--divider-color); }
          table.bte th.tight { padding:4px 6px; }
          .phead { display:inline-block; width:74px; text-align:right; padding-right:7px; }
          table.bte td { padding:4px 6px; border-bottom:1px solid var(--divider-color); }
          table.bte tr.dragging { opacity:.55; background:rgba(var(--rgb-primary-color),.12); }
          .modeBtn { background:none; border:1px solid var(--divider-color); border-radius:7px;
            color:var(--secondary-text-color); font-size:13px; line-height:1;
            padding:4px 6px; cursor:pointer; }
          .modeBtn:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .grip { display:inline-block; cursor:grab; touch-action:none; user-select:none;
            font-size:16px; color:var(--secondary-text-color); padding:2px 4px; line-height:1; }
          .grip:active { cursor:grabbing; }
          .arrows { display:flex; gap:2px; }
          .arrows button { background:none; border:1px solid var(--divider-color);
            color:var(--secondary-text-color); border-radius:6px; width:24px; height:24px;
            font-size:12px; line-height:1; padding:0; cursor:pointer; }
          .arrows button:hover:not([disabled]) { border-color:var(--primary-color);
            color:var(--primary-color); }
          .arrows button[disabled] { opacity:.25; cursor:default; }
          .grip.off, .arrows.off { opacity:.25; pointer-events:none; }
          input.sw { width:26px; height:26px; padding:0; border:none; background:none;
            border-radius:5px; cursor:pointer; box-shadow:0 0 0 1px ${ring}; }
          input.cell { width:100%; min-width:90px; padding:5px 7px; border-radius:7px;
            border:1px solid transparent; background:transparent;
            color:var(--primary-text-color); font-size:13px; }
          input.cell:hover { border-color:var(--divider-color); }
          input.cell:focus { border-color:var(--primary-color); background:var(--card-background-color);
            outline:none; }
          input.hx { font-family:monospace; font-size:12px; font-weight:600; min-width:86px; width:86px; }
          input.ser { font-family:monospace; font-size:11px; min-width:140px; }
          input.p { width:74px; min-width:74px; text-align:right; }
          .pricecell { display:flex; align-items:center; gap:4px; justify-content:flex-start; }
          .setdef { background:none; border:1px solid var(--divider-color); border-radius:6px;
            color:var(--secondary-text-color); font-size:9px; font-weight:600;
            letter-spacing:.3px; padding:4px 5px; cursor:pointer; }
          .setdef:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .bte-modal { position:fixed; inset:0; z-index:99999; background:rgba(0,0,0,.6);
            display:flex; align-items:center; justify-content:center; padding:20px; }
          .bte-sheet { width:min(94vw,380px); max-height:80vh; display:flex; flex-direction:column;
            background:var(--card-background-color); color:var(--primary-text-color);
            border:1px solid var(--divider-color); border-radius:14px; overflow:hidden;
            box-shadow:0 12px 48px rgba(0,0,0,.5); }
          .bte-sheet-head { padding:14px 16px 10px; border-bottom:1px solid var(--divider-color); }
          .bte-sheet-title { font-size:15px; font-weight:600; }
          .bte-sheet-sub { font-size:12px; color:var(--secondary-text-color); margin-top:2px; }
          .bte-sheet-body { overflow-y:auto; padding:6px 0; }
          .bte-target { display:flex; align-items:center; gap:10px; padding:8px 16px; }
          .bte-target + .bte-target { border-top:1px solid var(--divider-color); }
          .bte-target-label { flex:1; min-width:0; display:flex; flex-direction:column; }
          .bte-target-name { font-size:13px; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; }
          .bte-target-cur { font-size:11px; color:var(--secondary-text-color); }
          .bte-sheet-foot { padding:10px 16px; border-top:1px solid var(--divider-color);
            display:flex; justify-content:flex-end; }
          /* A spool's two rows read as one block. */
          table.bte tr.paired td { border-bottom-color:transparent; }
          /* …unless the pair is collapsed — then the first row is the block. */
          table.bte tr.pairtop.collapsed td { border-bottom-color:var(--divider-color); }
          .exp { background:none; border:1px solid var(--divider-color); border-radius:6px;
            color:var(--secondary-text-color); font-size:10px; line-height:1;
            width:20px; height:20px; padding:0; cursor:pointer; margin-left:2px;
            vertical-align:middle; }
          .exp:hover { border-color:var(--primary-color); color:var(--primary-color); }
          table.bte tr.paired:not(.pairtop) td:first-child { border-left:2px solid var(--primary-color); }
          table.bte tr.pairtop td:first-child { border-left:2px solid var(--primary-color); }
          .del { background:none; border:none; color:var(--secondary-text-color);
            cursor:pointer; font-size:14px; padding:2px 4px; border-radius:6px; }
          .del:hover { color:var(--error-color,#f44336); }
          .tog { background:none; border:1px solid var(--divider-color); border-radius:6px;
            color:var(--secondary-text-color); font-size:9px; font-weight:600;
            letter-spacing:.3px; padding:4px 0; width:36px; cursor:pointer; }
          .tog:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .tog.isoff { border-color:var(--warning-color,#ff9800);
            color:var(--warning-color,#ff9800); }
          /* washed-out treatment for disabled rows — opacity only, so it reads
             the same way on the light PC theme and the pure-black phone theme */
          table.bte tr.dis td { opacity:.42; filter:saturate(.3); }
          table.bte tr.dis td.togcell { opacity:1; filter:none; }
          .bte-foot { display:flex; justify-content:space-between; align-items:center;
            margin-top:12px; font-size:12px; color:var(--secondary-text-color); gap:12px; }
          button.save { background:var(--primary-color); color:var(--text-primary-color);
            border:none; border-radius:9px; padding:9px 18px; font-size:13px;
            font-weight:500; cursor:pointer; }
          button.save[disabled] { opacity:.4; cursor:default; }
          input.sw { width:26px; height:26px; padding:0; border:none; background:none;
            border-radius:5px; cursor:pointer;
            box-shadow:0 0 0 1px var(--bte-ring, var(--divider-color)); }
        </style>
        <div class="bte-wrap">
          <div class="bte-tools">
            <input class="f" type="text" placeholder="Filter…">
            <button class="tbtn add">+ Row</button>
            <button class="tbtn settings" title="Table settings">⚙</button>
            <button class="tbtn reload">↻ Reload</button>
          </div>
          <div class="bte-msg"></div>
          <div class="bte-scroll">
            <table class="bte">
              <thead><tr>${this._headHtml()}</tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div class="bte-foot">
            <span class="bte-count"></span>
            <button class="save" disabled>Save</button>
          </div>
        </div>
      </ha-card>`;

    this._built = true;

    const q = s => this.querySelector(s);

    q("input.f").addEventListener("input", e => {
      this._filter = e.target.value.toLowerCase();
      this._applyFilter();
    });

    q(".modeBtn").addEventListener("click", () => {
      this._mode = this._mode === "drag" ? "arrows" : "drag";
      this._paint();
      this._msg(this._mode === "drag"
        ? "Reorder mode: drag the ⠿ handle."
        : "Reorder mode: ↑ / ↓ buttons.");
    });

    q(".add").addEventListener("click", () => {
      this._rows.unshift({ _k: this._nextKey++, filament: "", color_code: "#808080",
        color_name: "", serial: "", serial_2: "", cost_per_kg: 0, disabled: false });
      this._dirty = true;
      this._paint();
      const first = this.querySelector("tbody tr input.cell");
      if (first) first.focus();
    });

    q(".settings").addEventListener("click", () => this._openSettings());

    q(".reload").addEventListener("click", () => this._reload());
    q("button.save").addEventListener("click", () => this._save());

    this._paint();
  }

  _paint() {
    const bg = this._bg();
    const tbody = this.querySelector("tbody");
    const modeBtn = this.querySelector(".modeBtn");
    if (modeBtn) {
      modeBtn.textContent = this._mode === "drag" ? "⠿" : "↕";
      modeBtn.title = this._mode === "drag"
        ? "Drag mode — click for ↑/↓ buttons (better on touch)"
        : "Button mode — click for drag handles";
    }

    const total = this._rows.length;

    const groups = this._groups();
    const cols = this._cols();

    tbody.innerHTML = groups.map((group, gi) => group.map((r, ri) => {
      const key = `${r.filament} ${r.color_name} ${r.color_code} ${r.serial} ${r.serial_2}`
        .toLowerCase().replace(/"/g, "");
      const sig = this._groupSig(group);
      const expanded = group.length > 1 && this._isExpanded(sig);

      // One handle per spool, spanning its visible rows: a pair moves as a
      // unit either way — a collapsed child row still travels with its spool.
      const handle = ri > 0 ? "" : `<td rowspan="${expanded ? group.length : 1}">${
        this._mode === "drag"
          ? `<span class="grip" data-k="${r._k}" title="Drag to reorder">⠿</span>`
          : `<span class="arrows">
               <button class="up" data-k="${r._k}" title="Move up" ${gi === 0 ? "disabled" : ""}>▲</button>
               <button class="down" data-k="${r._k}" title="Move down" ${
                 gi === groups.length - 1 ? "disabled" : ""}>▼</button>
             </span>`}${
        group.length > 1
          ? `<button class="exp" data-gs="${this._esc(sig)}" title="${
              expanded ? "Hide the spool's second tag" : "Show the spool's second tag"}">${
              expanded ? "▾" : "▸"}</button>`
          : ""}</td>`;

      const cells = cols.map(c => this._cell(c, r, bg)).join("");
      const cls = [r.disabled ? "dis" : "", group.length > 1 ? "paired" : "",
                   group.length > 1 && ri === 0 ? "pairtop" : "",
                   group.length > 1 && ri === 0 && !expanded ? "collapsed" : ""]
        .filter(Boolean).join(" ");
      return `<tr data-k="${r._k}" data-g="${gi}" data-gs="${this._esc(sig)}" data-s="${this._esc(key)}"${
        r.disabled ? ' data-dis="1"' : ""}${ri > 0 ? ' data-p2="1"' : ""}${
        cls ? ` class="${cls}"` : ""}>
        ${handle}${cells}
        <td class="togcell"><button class="tog${r.disabled ? " isoff" : ""}" data-k="${r._k}"
              title="${r.disabled ? "Disabled — click to enable" : "Enabled — click to disable"}"
              >${r.disabled ? "OFF" : "ON"}</button></td>
        <td><button class="del" data-k="${r._k}" title="Delete row">✕</button></td>
      </tr>`;
    }).join("")).join("") || `<tr><td colspan="${cols.length + 3}"
      style="text-align:center;padding:24px;opacity:.5">
      No tags — press “+ Row” to add one</td></tr>`;

    tbody.querySelectorAll("input[data-f]").forEach(inp => {
      inp.addEventListener("change", e => this._edit(e.target));
      if (inp.type === "color") inp.addEventListener("input", e => this._edit(e.target));
    });

    tbody.querySelectorAll("button.del").forEach(b => {
      b.addEventListener("click", e => {
        const k = Number(e.currentTarget.dataset.k);
        this._rows = this._rows.filter(r => r._k !== k);
        this._dirty = true;
        this._paint();
      });
    });

    tbody.querySelectorAll("button.setdef").forEach(b => {
      b.addEventListener("click", e => this._openPricePicker(e.currentTarget.dataset.k));
    });

    tbody.querySelectorAll("button.tog").forEach(b => {
      b.addEventListener("click", e => this._toggleDisabled(e.currentTarget.dataset.k));
    });

    tbody.querySelectorAll("button.up").forEach(b => {
      b.addEventListener("click", e => this._move(e.currentTarget.dataset.k, -1));
    });
    tbody.querySelectorAll("button.down").forEach(b => {
      b.addEventListener("click", e => this._move(e.currentTarget.dataset.k, 1));
    });

    tbody.querySelectorAll(".grip").forEach(g => {
      g.addEventListener("pointerdown", e => this._drag(e, g));
    });

    tbody.querySelectorAll("button.exp").forEach(b => {
      b.addEventListener("click", e => this._toggleExpand(e.currentTarget.dataset.gs));
    });

    this._applyFilter();
    requestAnimationFrame(() => this._recolor());
  }

  _toggleDisabled(k) {
    const row = this._row(k);
    if (!row) return;
    row.disabled = !row.disabled;
    this._dirty = true;

    const tr = this.querySelector(`tbody tr[data-k="${row._k}"]`);
    const btn = tr && tr.querySelector("button.tog");
    if (btn) {
      btn.textContent = row.disabled ? "OFF" : "ON";
      btn.classList.toggle("isoff", row.disabled);
      btn.title = row.disabled ? "Disabled — click to enable" : "Enabled — click to disable";
    }
    if (tr) {
      tr.classList.toggle("dis", row.disabled);
      if (row.disabled) tr.dataset.dis = "1"; else delete tr.dataset.dis;
    }

    const label = `${row.filament || "Row"}${row.color_name ? " · " + row.color_name : ""}`;
    if (row.disabled && !this._showDisabled) {
      this._msg(`${label} disabled and hidden — “Show disabled” to see it. `
        + "Press Save to write it to the file.");
    } else {
      this._msg(`${label} ${row.disabled ? "disabled" : "enabled"} — `
        + "press Save to write it to the file.");
    }

    this._applyFilter();
  }

  // Whether any of a group's rows is currently on screen. Reordering is always
  // allowed — hidden rows simply keep their positions — but the arrow buttons
  // must step over groups the filter or the toggles hide, or a click would
  // swap with something invisible and appear to do nothing.
  _groupVisible(group) {
    return group.some(r => {
      const tr = this.querySelector(`tbody tr[data-k="${r._k}"]`);
      return tr && tr.style.display !== "none";
    });
  }

  _openSettings() {
    const toggleRow = (cls, on, label, hint) => `
      <div class="bte-target">
        <button class="tog${on ? "" : " isoff"}" data-set="${cls}">${on ? "ON" : "OFF"}</button>
        <span class="bte-target-label">
          <span class="bte-target-name">${label}</span>${
          hint ? `<span class="bte-target-cur">${hint}</span>` : ""}
        </span>
      </div>`;

    const draw = () => {
      const dis = this._disabledCount();
      const pairs = this._groups().filter(g => g.length > 1).length;
      return toggleRow("showdis", this._showDisabled,
          `Show disabled${dis ? ` (${dis})` : ""}`,
          "Disabled rows appear washed out")
        + toggleRow("expand", this._expandDefault,
          `Expand related by default${pairs ? ` (${pairs} pairs)` : ""}`,
          "A spool's second tag as a child row; ▸ on the row overrides")
        + `<div class="bte-target">
            <span class="bte-target-label"><span class="bte-target-name">Sort rows</span></span>
            <button class="tbtn" data-sort="type">By type</button>
            <button class="tbtn" data-sort="price">By price</button>
          </div>`
        + `<div class="bte-target"><span class="bte-target-label">
            <span class="bte-target-name" style="font-weight:600">Columns</span>
            <span class="bte-target-cur">Display only — saving always writes every field.</span>
          </span></div>`
        + this._order.map(key => {
          const col = BTE_COLS.find(c => c.key === key);
          const on = !this._hidden.has(key);
          return `<div class="bte-target" data-col="${key}">
            <button class="tog${on ? "" : " isoff"}" data-toggle="${key}"
                    title="${on ? "Shown — click to hide" : "Hidden — click to show"}"
                    >${on ? "ON" : "OFF"}</button>
            <span class="bte-target-label"><span class="bte-target-name">${
              this._esc(col.label || col.key)}</span></span>
            <span class="arrows">
              <button class="cup" data-move="${key}">▲</button>
              <button class="cdown" data-move="${key}">▼</button>
            </span>
          </div>`;
        }).join("");
    };

    const ov = document.createElement("div");
    ov.className = "bte-modal";
    ov.innerHTML = `
      <div class="bte-sheet" role="dialog" aria-modal="true">
        <div class="bte-sheet-head">
          <div class="bte-sheet-title">Table settings</div>
        </div>
        <div class="bte-sheet-body"></div>
        <div class="bte-sheet-foot">
          <button class="tbtn reset-cols">Reset columns</button>
          <button class="tbtn close">Done</button>
        </div>
      </div>`;

    const body = ov.querySelector(".bte-sheet-body");
    const render = () => {
      body.innerHTML = draw();
      body.querySelectorAll("[data-set]").forEach(b => {
        b.addEventListener("click", e => {
          const which = e.currentTarget.dataset.set;
          if (which === "showdis") {
            this._showDisabled = !this._showDisabled;
            this._applyFilter();
          } else {
            this._expandDefault = !this._expandDefault;
            // The new default applies everywhere: per-spool overrides were
            // relative to the old one and would now mean the opposite.
            this._expandOverrides.clear();
            this._saveCols();
            this._paint();
          }
          render();
        });
      });
      body.querySelectorAll("[data-sort]").forEach(b => {
        b.addEventListener("click", e => {
          if (e.currentTarget.dataset.sort === "type") {
            this._rows.sort((a, b) =>
              (a.filament + a.color_name).toLowerCase() < (b.filament + b.color_name).toLowerCase() ? -1 : 1);
          } else {
            this._rows.sort((a, b) => (Number(b.cost_per_kg) || 0) - (Number(a.cost_per_kg) || 0));
          }
          this._rows = this._grouped();
          this._dirty = true;
          this._paint();
          this._msg("Reordered — press Save to write it to the file.");
        });
      });
      body.querySelectorAll("[data-toggle]").forEach(b => {
        b.addEventListener("click", e => {
          const key = e.currentTarget.dataset.toggle;
          if (this._hidden.has(key)) this._hidden.delete(key); else this._hidden.add(key);
          this._saveCols(); render(); this._refreshTable();
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
          this._saveCols(); render(); this._refreshTable();
        });
      });
    };
    render();

    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    ov.querySelector("button.close").addEventListener("click", close);
    ov.querySelector("button.reset-cols").addEventListener("click", () => {
      this._order = BTE_DEFAULT_ORDER.slice();
      this._hidden = new Set();
      this._saveCols(); render(); this._refreshTable();
    });
    document.addEventListener("keydown", esc);
    this.appendChild(ov);
  }

  _headHtml() {
    return `<th class="tight" style="width:56px"><button class="modeBtn" title="Switch reorder mode"></button></th>`
      + this._cols().map(c => `<th class="${c.tight ? "tight" : ""}"${
          c.width ? ` style="width:${c.width}"` : ""}>${
          c.key === "price"
            ? `<span class="phead">${this._esc(this._cfg.unit)}</span>`
            : this._esc(c.label)}</th>`).join("")
      + `<th class="tight" style="width:44px"></th><th class="tight" style="width:30px"></th>`;
  }

  // Header and body only. A full _render() would rebuild the card's innerHTML
  // and take any open dialog down with it.
  _refreshTable() {
    const head = this.querySelector("thead tr");
    if (!head) return;
    head.innerHTML = this._headHtml();
    const modeBtn = this.querySelector(".modeBtn");
    if (modeBtn) {
      modeBtn.addEventListener("click", () => {
        this._mode = this._mode === "drag" ? "arrows" : "drag";
        this._paint();
      });
    }
    this._paint();
  }

  _cell(col, r, bg) {
    const k = r._k;
    switch (col.key) {
      case "swatch":
        return `<td><input class="sw" type="color" data-k="${k}" data-f="color_code"
                value="${this._esc(this._norm(r.color_code))}"></td>`;
      case "filament":
        return `<td><input class="cell" type="text" data-k="${k}" data-f="filament"
                value="${this._esc(r.filament)}"></td>`;
      case "hex":
        return `<td><input class="cell hx" type="text" data-k="${k}" data-f="hex"
                value="${this._esc(this._norm(r.color_code))}"
                style="color:${this._textFor(r.color_code, bg)}"></td>`;
      case "color_name":
        return `<td><input class="cell" type="text" data-k="${k}" data-f="color_name"
                value="${this._esc(r.color_name)}"></td>`;
      case "serial":
        return `<td><input class="cell ser" type="text" data-k="${k}" data-f="serial"
                value="${this._esc(r.serial)}"></td>`;
      case "serial_2":
        return `<td><input class="cell ser" type="text" data-k="${k}" data-f="serial_2"
                placeholder="other side" value="${this._esc(r.serial_2 || "")}"></td>`;
      case "price":
        return `<td><span class="pricecell">
                  <input class="cell p" type="number" step="0.01" min="0" data-k="${k}"
                         data-f="cost_per_kg" value="${(Number(r.cost_per_kg) || 0).toFixed(2)}">
                  <button class="setdef" data-k="${k}"
                          title="Push this price into one of the filament price entities">SET</button>
                </span></td>`;
      default:
        return "<td></td>";
    }
  }

  _move(k, dir) {
    // Reorder by spool, so a pair steps over its neighbour intact.
    const groups = this._groups();
    const i = groups.findIndex(g => g.some(r => r._k === Number(k)));
    if (i < 0) return;
    let j = i + dir;
    while (j >= 0 && j < groups.length && !this._groupVisible(groups[j])) j += dir;
    if (j < 0 || j >= groups.length) return;
    const tmp = groups[i];
    groups[i] = groups[j];
    groups[j] = tmp;
    this._rows = groups.flat();
    this._dirty = true;
    this._paint();
  }

  // Provided by the tag-library sensor, resolved from the entity registry —
  // the default price first, then one entry per configured slot. Lost in a
  // refactor once, so the SET button died with "not a function": keep the
  // fallback so even a sensor without the attribute yields a working picker.
  _priceTargets() {
    const st = this._hass && this._hass.states[this._cfg.entity];
    const targets = (st && st.attributes && st.attributes.price_targets) || [];
    if (targets.length) return targets;
    return [{ entity_id: this._cfg.default_price_entity, label: "Default price" }];
  }

  _openPricePicker(k) {
    const row = this._row(k);
    if (!row) return;
    const val = Number(row.cost_per_kg) || 0;
    const targets = this._priceTargets();
    const what = `${this._esc(row.filament || "this filament")}`
      + (row.color_name ? ` · ${this._esc(row.color_name)}` : "");

    const ov = document.createElement("div");
    ov.className = "bte-modal";
    ov.innerHTML = `
      <div class="bte-sheet" role="dialog" aria-modal="true">
        <div class="bte-sheet-head">
          <div class="bte-sheet-title">Set price ${val.toFixed(2)} ${this._esc(this._cfg.unit)}</div>
          <div class="bte-sheet-sub">${what}</div>
        </div>
        <div class="bte-sheet-body">
          ${targets.map(t => `
            <div class="bte-target">
              <span class="bte-target-label">
                <span class="bte-target-name">${this._esc(t.label)}</span>
                <span class="bte-target-cur" data-cur="${this._esc(t.entity_id)}"></span>
              </span>
              <button class="setdef pick" data-ent="${this._esc(t.entity_id)}">SET</button>
            </div>`).join("")}
        </div>
        <div class="bte-sheet-foot">
          <button class="tbtn close">Cancel</button>
        </div>
      </div>`;

    // show what each target currently holds, so a wrong click is obvious
    ov.querySelectorAll("[data-cur]").forEach(el => {
      const s = this._hass && this._hass.states[el.dataset.cur];
      const cur = s ? Number(s.state) : NaN;
      el.textContent = isNaN(cur) ? "" : `now ${cur.toFixed(2)}`;
    });

    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", e => { if (e.target === ov) close(); });
    ov.querySelector("button.close").addEventListener("click", close);
    ov.querySelectorAll("button.pick").forEach(b => {
      b.addEventListener("click", async e => {
        const ent = e.currentTarget.dataset.ent;
        close();
        await this._applyPrice(ent, val, row);
      });
    });

    document.addEventListener("keydown", esc);
    this.appendChild(ov);
  }

  async _applyPrice(entity_id, val, row) {
    try {
      await this._hass.callService(entity_id.split(".")[0], "set_value",
        { entity_id, value: val });
      const st = this._hass.states[entity_id];
      const name = (st && st.attributes && st.attributes.friendly_name) || entity_id;
      this._msg(`${name} set to ${val.toFixed(2)} ${this._cfg.unit}`
        + (row.filament ? ` (${row.filament}${row.color_name ? " · " + row.color_name : ""}).` : "."));
    } catch (err) {
      this._msg("Could not set price: " + err, "err");
    }
  }

  _edit(el) {
    const row = this._row(el.dataset.k);
    if (!row) return;
    const f = el.dataset.f;
    const bg = this._bg();

    if (f === "cost_per_kg") {
      row.cost_per_kg = Number(el.value) || 0;
    } else if (f === "hex" || f === "color_code") {
      row.color_code = this._norm(el.value);
    } else {
      row[f] = el.value;
    }

    // A spool's two rows describe one physical thing, so the descriptive
    // fields stay identical across the pair. Serials are what tell the two
    // tags apart, so they stay per-row.
    if (f !== "serial" && f !== "serial_2") {
      for (const other of this._groupOf(row._k)) {
        if (other._k === row._k) continue;
        if (f === "cost_per_kg") other.cost_per_kg = row.cost_per_kg;
        else if (f === "hex" || f === "color_code") other.color_code = row.color_code;
        else other[f] = row[f];
        this._syncRowDom(other, bg);
      }
    }
    this._syncRowDom(row, bg);

    this._dirty = true;

    // Changing a serial can form or dissolve a pair — regroup so the partner
    // snaps adjacent (or apart) immediately instead of on the next reload.
    if (f === "serial" || f === "serial_2") {
      this._rows = this._grouped();
      this._paint();
      return;
    }
    this._updateFoot();
  }

  // Bring a row's inputs and search key in line with its data, without a
  // repaint that would steal focus from the field being edited.
  _syncRowDom(r, bg) {
    const tr = this.querySelector(`tbody tr[data-k="${r._k}"]`);
    if (!tr) return;
    const set = (sel, v) => {
      const el = tr.querySelector(sel);
      if (el && el.value !== v) el.value = v;
    };
    set('input[data-f="filament"]', r.filament);
    set('input[data-f="color_name"]', r.color_name);
    set('input[data-f="cost_per_kg"]', (Number(r.cost_per_kg) || 0).toFixed(2));
    set("input.sw", this._norm(r.color_code));
    const hx = tr.querySelector("input.hx");
    if (hx) {
      hx.value = this._norm(r.color_code);
      hx.style.color = this._textFor(r.color_code, bg);
    }
    tr.dataset.s = `${r.filament} ${r.color_name} ${r.color_code} ${r.serial} ${r.serial_2}`
      .toLowerCase().replace(/"/g, "");
  }

  _drag(ev, grip) {
    if (ev.button !== undefined && ev.button !== 0) return;
    ev.preventDefault();

    const tbody = this.querySelector("tbody");
    const tr = grip.closest("tr");
    if (!tr) return;
    // The handle spans the spool, so the partner row travels with it — even
    // one hidden by “Hide related”: insertBefore moves it all the same.
    const moving = [...tbody.querySelectorAll(`tr[data-g="${tr.dataset.g}"]`)];
    moving.forEach(row => row.classList.add("dragging"));

    const move = e => {
      e.preventDefault();
      const y = e.clientY;
      const rows = [...tbody.querySelectorAll("tr[data-k]")]
        .filter(x => !moving.includes(x) && x.style.display !== "none");
      if (!rows.length) return;

      // Hit-test whole spools, not rows. Dropping between the two rows of a
      // pair would split it, only for the grouping to snap it back together
      // on the next paint — the drop would appear not to stick.
      const blocks = [];
      for (const row of rows) {
        const tail = blocks[blocks.length - 1];
        if (tail && tail.g === row.dataset.g) tail.last = row;
        else blocks.push({ g: row.dataset.g, first: row, last: row });
      }

      const place = before => moving.forEach(row => tbody.insertBefore(row, before));
      const first = blocks[0];
      const last = blocks[blocks.length - 1];
      if (y < first.first.getBoundingClientRect().top) { place(first.first); return; }
      if (y > last.last.getBoundingClientRect().bottom) { moving.forEach(r => tbody.appendChild(r)); return; }

      for (const b of blocks) {
        const top = b.first.getBoundingClientRect().top;
        const bottom = b.last.getBoundingClientRect().bottom;
        if (y >= top && y <= bottom) {
          const after = y > (top + bottom) / 2;
          place(after ? b.last.nextSibling : b.first);
          break;
        }
      }
    };

    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      moving.forEach(row => row.classList.remove("dragging"));
      const keys = [...tbody.querySelectorAll("tr[data-k]")].map(x => Number(x.dataset.k));
      const same = keys.every((k, i) => this._rows[i] && this._rows[i]._k === k);
      if (!same) {
        this._rows = keys.map(k => this._row(k)).filter(Boolean);
        // Repaint so the group indexes and pair borders match the new order.
        this._rows = this._grouped();
        this._dirty = true;
        this._paint();
      }
    };

    document.addEventListener("pointermove", move, { passive: false });
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  }

  _applyFilter() {
    const qs = this._filter;
    const rows = [...this.querySelectorAll("tbody tr[data-s]")];
    let hiddenDis = 0;
    let hiddenRel = 0;

    for (const tr of rows) {
      const isDis = tr.dataset.dis === "1";
      // A collapsed spool shows only its first row — unless the filter is
      // searching, when a child that matches must not hide from it.
      const collapsedChild = tr.dataset.p2 === "1" && !this._isExpanded(tr.dataset.gs) && !qs;
      const hit = (!qs || tr.dataset.s.includes(qs))
        && (this._showDisabled || !isDis)
        && !collapsedChild;
      tr.style.display = hit ? "" : "none";
      if (!hit && isDis && !this._showDisabled) hiddenDis++;
      else if (!hit && collapsedChild) hiddenRel++;
    }

    // The handle cell lives on the first row and spans the pair. A child row
    // shown without its parent would render one cell short and shift left, so
    // a visible child always brings its parent, and the span always matches
    // what is actually visible.
    for (const child of rows) {
      if (child.dataset.p2 !== "1" || child.style.display === "none") continue;
      const parent = rows.find(p => p.dataset.gs === child.dataset.gs && p.dataset.p2 !== "1");
      if (parent && parent.style.display === "none") parent.style.display = "";
    }
    for (const parent of rows) {
      if (parent.dataset.p2 === "1") continue;
      const td = parent.querySelector("td[rowspan]");
      if (!td) continue;
      const child = rows.find(c => c.dataset.gs === parent.dataset.gs && c.dataset.p2 === "1");
      const childVisible = !!child && child.style.display !== "none";
      td.setAttribute("rowspan", childVisible ? 2 : 1);
      parent.classList.toggle("collapsed",
        parent.classList.contains("pairtop") && !childVisible);
    }

    this._shown = rows.filter(tr => tr.style.display !== "none").length;
    this._hiddenDis = hiddenDis;
    this._hiddenRel = hiddenRel;
    this._updateFoot();
  }

  _updateFoot() {
    const c = this.querySelector(".bte-count");
    if (c) {
      const shown = this._shown === undefined ? this._rows.length : this._shown;
      c.textContent = `${shown} of ${this._rows.length} rows`
        + (this._hiddenDis ? ` · ${this._hiddenDis} disabled hidden` : "")
        + (this._hiddenRel ? ` · ${this._hiddenRel} second tags collapsed` : "")
        + (this._dirty ? " · unsaved changes" : "");
    }

    const b = this.querySelector("button.save");
    if (b && !this._busy) { b.disabled = !this._dirty; b.textContent = "Save"; }
  }

  _msg(text, kind) {
    const m = this.querySelector(".bte-msg");
    if (!m) return;
    m.className = "bte-msg" + (kind ? " " + kind : "");
    m.textContent = text;
    m.style.display = text ? "block" : "none";
  }

  _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  async _reload() {
    if (this._dirty && !confirm("Discard unsaved changes and reload from the file?")) return;
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
        this._msg("The file changed on disk (a tag was probably scanned). "
          + "Press ↻ Reload and redo your edits — nothing was written.", "warn");
        this._busy = false;
        btn.textContent = "Save";
        btn.disabled = false;
        return;
      }

      btn.textContent = "Saving…";
      this._msg("Writing the tag library…");
      const [domain, service] = this._cfg.save_service.split(".");
      await this._hass.callService(domain, service, { tags: this._payload() });
    } catch (err) {
      this._msg("Save failed: " + err, "err");
      this._busy = false;
      btn.textContent = "Save";
      btn.disabled = false;
      return;
    }

    // What is on screen IS what was just written — do not reload from the
    // sensor, which lags the write and would flash the pre-save list until
    // its refresh lands. The hass setter adopts that refresh as the new
    // baseline when it arrives (_justSaved).
    this._busy = false;
    this._dirty = false;
    this._justSaved = true;
    this._updateFoot();
    this._msg(`Saved ${this._rows.length} rows. Previous version kept as tags.csv.bak.`);
  }
}

// Defensive: a card loaded twice (stale resource plus new one) would
// otherwise throw on the second define and register nothing at all.
if (!customElements.get("bambu-costs-tags-editor")) customElements.define("bambu-costs-tags-editor", BambuCostsTagsEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "bambu-costs-tags-editor")) window.customCards.push({
  type: "bambu-costs-tags-editor",
  name: "Bambu Costs: Tags Editor",
  description: "Editable, reorderable filament tag library",
});