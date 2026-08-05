class BambuCostsTagsEditor extends HTMLElement {
  setConfig(cfg) {
    if (!cfg.entity) throw new Error("Define an entity (sensor.bambu_costs_tag_library)");
    this._cfg = Object.assign({
      title: "Filament tags",
      save_service: "bambu_costs.write_tags",
      default_price_entity: "number.bambu_costs_default_filament_price",
      unit: "€/kg",
    }, cfg);
    this._rows = [];
    this._baseSig = null;
    this._dirty = false;
    this._filter = "";
    this._showDisabled = false;
    this._nextKey = 1;
    this._built = false;
    this._busy = false;
    this._mode = (window.matchMedia && window.matchMedia("(pointer: coarse)").matches)
      ? "arrows" : "drag";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._load(); this._render(); return; }
    if (this._dirty || this._busy) return;
    if (JSON.stringify(this._sensorData()) === this._baseSig) return;
    this._load();
    this._render();
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
      cost_per_kg: Number(r.cost_per_kg) || 0,
      disabled: this._isDisabled(r.disabled),
    }));
    this._dirty = false;
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

  _payload() {
    return this._rows.map(r => ({
      filament: this._clean(r.filament),
      color_code: this._clean(r.color_code),
      color_name: this._clean(r.color_name),
      serial: this._clean(r.serial),
      cost_per_kg: Number(r.cost_per_kg) || 0,
      disabled: !!r.disabled,
    }));
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
            <button class="tbtn sortType">Sort: type</button>
            <button class="tbtn sortPrice">Sort: price</button>
            <button class="tbtn showdis">Show disabled</button>
            <button class="tbtn reload">↻ Reload</button>
          </div>
          <div class="bte-msg"></div>
          <div class="bte-scroll">
            <table class="bte">
              <thead><tr>
                <th class="tight" style="width:56px"><button class="modeBtn" title="Switch reorder mode"></button></th>
                <th class="tight" style="width:34px"></th>
                <th>Filament</th>
                <th style="width:100px">Hex</th>
                <th>Color</th>
                <th style="width:150px">Serial</th>
                <th class="tight" style="width:120px"><span class="phead">${this._esc(this._cfg.unit)}</span></th>
                <th class="tight" style="width:44px"></th>
                <th class="tight" style="width:30px"></th>
              </tr></thead>
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
        color_name: "", serial: "", cost_per_kg: 0, disabled: false });
      this._dirty = true;
      this._paint();
      const first = this.querySelector("tbody tr input.cell");
      if (first) first.focus();
    });

    q(".sortType").addEventListener("click", () => {
      this._rows.sort((a, b) =>
        (a.filament + a.color_name).toLowerCase() < (b.filament + b.color_name).toLowerCase() ? -1 : 1);
      this._dirty = true;
      this._paint();
      this._msg("Reordered by type — press Save to write it to the file.");
    });

    q(".sortPrice").addEventListener("click", () => {
      this._rows.sort((a, b) => (Number(b.cost_per_kg) || 0) - (Number(a.cost_per_kg) || 0));
      this._dirty = true;
      this._paint();
      this._msg("Reordered by price — press Save to write it to the file.");
    });

    q(".showdis").addEventListener("click", () => {
      this._showDisabled = !this._showDisabled;
      this._applyFilter();
      this._msg(this._showDisabled
        ? "Showing disabled entries — they appear washed out."
        : "Disabled entries hidden.");
    });

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

    tbody.innerHTML = this._rows.map((r, idx) => {
      const key = `${r.filament} ${r.color_name} ${r.color_code} ${r.serial}`
        .toLowerCase().replace(/"/g, "");
      const handle = this._mode === "drag"
        ? `<span class="grip" data-k="${r._k}" title="Drag to reorder">⠿</span>`
        : `<span class="arrows">
             <button class="up" data-k="${r._k}" title="Move up" ${idx === 0 ? "disabled" : ""}>▲</button>
             <button class="down" data-k="${r._k}" title="Move down" ${idx === total - 1 ? "disabled" : ""}>▼</button>
           </span>`;
      return `<tr data-k="${r._k}" data-s="${this._esc(key)}"${r.disabled ? ' data-dis="1" class="dis"' : ""}>
        <td>${handle}</td>
        <td><input class="sw" type="color" data-k="${r._k}" data-f="color_code"
             value="${this._esc(this._norm(r.color_code))}"></td>
        <td><input class="cell" type="text" data-k="${r._k}" data-f="filament"
             value="${this._esc(r.filament)}"></td>
        <td><input class="cell hx" type="text" data-k="${r._k}" data-f="hex"
             value="${this._esc(this._norm(r.color_code))}"
             style="color:${this._textFor(r.color_code, bg)}"></td>
        <td><input class="cell" type="text" data-k="${r._k}" data-f="color_name"
             value="${this._esc(r.color_name)}"></td>
        <td><input class="cell ser" type="text" data-k="${r._k}" data-f="serial"
             value="${this._esc(r.serial)}"></td>
        <td><span class="pricecell">
              <input class="cell p" type="number" step="0.01" min="0" data-k="${r._k}"
                     data-f="cost_per_kg" value="${(Number(r.cost_per_kg) || 0).toFixed(2)}">
              <button class="setdef" data-k="${r._k}"
                      title="Use this price as the default / backup filament cost">SET</button>
            </span></td>
        <td class="togcell"><button class="tog${r.disabled ? " isoff" : ""}" data-k="${r._k}"
              title="${r.disabled ? "Disabled — click to enable" : "Enabled — click to disable"}"
              >${r.disabled ? "OFF" : "ON"}</button></td>
        <td><button class="del" data-k="${r._k}" title="Delete row">✕</button></td>
      </tr>`;
    }).join("") || `<tr><td colspan="9" style="text-align:center;padding:24px;opacity:.5">
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
      b.addEventListener("click", e => this._setDefaultPrice(e.currentTarget.dataset.k));
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

  // Rows are hidden with display:none rather than removed, so whenever anything is
  // hidden the visible order no longer matches this._rows — block reordering instead
  // of silently moving a row past something the user cannot see.
  _reorderBlock() {
    if (this._filter) return "Clear the filter before reordering rows.";
    if (!this._showDisabled && this._disabledCount())
      return "Turn on “Show disabled” before reordering rows.";
    return null;
  }

  _move(k, dir) {
    const block = this._reorderBlock();
    if (block) {
      this._msg(block, "warn");
      return;
    }
    const i = this._rows.findIndex(r => r._k === Number(k));
    const j = i + dir;
    if (i < 0 || j < 0 || j >= this._rows.length) return;
    const tmp = this._rows[i];
    this._rows[i] = this._rows[j];
    this._rows[j] = tmp;
    this._dirty = true;
    this._paint();
  }

  async _setDefaultPrice(k) {
    const row = this._row(k);
    if (!row) return;
    const val = Number(row.cost_per_kg) || 0;
    const ent = this._cfg.default_price_entity;
    try {
      await this._hass.callService(ent.split(".")[0], "set_value",
        { entity_id: ent, value: val });
      this._msg(`Default filament cost set to ${val.toFixed(2)} ${this._cfg.unit}`
        + (row.filament ? ` (${row.filament}${row.color_name ? " · " + row.color_name : ""}).` : "."));
    } catch (err) {
      this._msg("Could not set default price: " + err, "err");
    }
  }

  _edit(el) {
    const row = this._row(el.dataset.k);
    if (!row) return;
    const f = el.dataset.f;
    const bg = this._bg();
    const tr = el.closest("tr");

    if (f === "cost_per_kg") {
      row.cost_per_kg = Number(el.value) || 0;
    } else if (f === "hex" || f === "color_code") {
      row.color_code = this._norm(el.value);
      const sw = tr.querySelector("input.sw");
      const hx = tr.querySelector("input.hx");
      if (sw) sw.value = row.color_code;
      if (hx) { hx.value = row.color_code; hx.style.color = this._textFor(row.color_code, bg); }
    } else {
      row[f] = el.value;
    }

    tr.dataset.s = `${row.filament} ${row.color_name} ${row.color_code} ${row.serial}`
      .toLowerCase().replace(/"/g, "");
    this._dirty = true;
    this._updateFoot();
  }

  _drag(ev, grip) {
    const block = this._reorderBlock();
    if (block) {
      this._msg(block, "warn");
      return;
    }
    if (ev.button !== undefined && ev.button !== 0) return;
    ev.preventDefault();

    const tbody = this.querySelector("tbody");
    const tr = grip.closest("tr");
    if (!tr) return;
    tr.classList.add("dragging");

    const move = e => {
      e.preventDefault();
      const y = e.clientY;
      const rows = [...tbody.querySelectorAll("tr[data-k]")]
        .filter(x => x !== tr && x.style.display !== "none");
      if (!rows.length) return;

      const first = rows[0];
      const last = rows[rows.length - 1];
      if (y < first.getBoundingClientRect().top) { tbody.insertBefore(tr, first); return; }
      if (y > last.getBoundingClientRect().bottom) { tbody.appendChild(tr); return; }

      for (const over of rows) {
        const rect = over.getBoundingClientRect();
        if (y >= rect.top && y <= rect.bottom) {
          const after = y > rect.top + rect.height / 2;
          tbody.insertBefore(tr, after ? over.nextSibling : over);
          break;
        }
      }
    };

    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      tr.classList.remove("dragging");
      const keys = [...tbody.querySelectorAll("tr[data-k]")].map(x => Number(x.dataset.k));
      const same = keys.every((k, i) => this._rows[i] && this._rows[i]._k === k);
      if (!same) {
        this._rows = keys.map(k => this._row(k)).filter(Boolean);
        this._dirty = true;
        this._updateFoot();
      }
    };

    document.addEventListener("pointermove", move, { passive: false });
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  }

  _applyFilter() {
    const qs = this._filter;
    let shown = 0;
    let hiddenDis = 0;
    this.querySelectorAll("tbody tr[data-s]").forEach(tr => {
      const isDis = tr.dataset.dis === "1";
      const hit = (!qs || tr.dataset.s.includes(qs)) && (this._showDisabled || !isDis);
      tr.style.display = hit ? "" : "none";
      if (hit) shown++;
      else if (isDis && !this._showDisabled) hiddenDis++;
    });
    const blocked = !!this._reorderBlock();
    this.querySelectorAll(".grip, .arrows").forEach(g => g.classList.toggle("off", blocked));
    this._shown = shown;
    this._hiddenDis = hiddenDis;
    this._updateFoot();
  }

  _updateFoot() {
    const dis = this._disabledCount();

    const t = this.querySelector(".showdis");
    if (t) {
      t.classList.toggle("on", this._showDisabled);
      t.textContent = dis ? `Show disabled (${dis})` : "Show disabled";
    }

    const c = this.querySelector(".bte-count");
    if (c) {
      const shown = this._shown === undefined ? this._rows.length : this._shown;
      c.textContent = `${shown} of ${this._rows.length} rows`
        + (this._hiddenDis ? ` · ${this._hiddenDis} disabled hidden` : "")
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
      await this._sleep(1500);
    } catch (err) {
      this._msg("Save failed: " + err, "err");
      this._busy = false;
      btn.textContent = "Save";
      btn.disabled = false;
      return;
    }

    this._busy = false;
    this._load();
    this._paint();
    this._msg(`Saved ${this._rows.length} rows. Previous version kept as tags.csv.bak.`);
  }
}

customElements.define("bambu-costs-tags-editor", BambuCostsTagsEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "bambu-costs-tags-editor",
  name: "Bambu Costs: Tags Editor",
  description: "Editable, reorderable filament tag library",
});