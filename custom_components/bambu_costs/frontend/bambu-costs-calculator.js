// Sentinel for the manual entry. A real key is "type|name|price", so this
// cannot collide — and unlike a control character it survives being written
// into a data- attribute and read back.
const OTHER_KEY = "__other__";

class BambuCostsCalculator extends HTMLElement {
  setConfig(cfg) {
    if (!cfg.entity) throw new Error("Define an entity (sensor.bambu_costs_tag_library)");
    this._cfg = Object.assign({
      title: "Print cost calculator",
      currency: "€",
      rate_per_minute: 0.0008,
      margin_percent: 30,
      vat_percent: 21,
      remember: true,
    }, cfg);

    this._nextKey = 1;
    this._lines = [this._newLine()];
    this._minutes = "";
    this._rate = String(this._cfg.rate_per_minute);
    this._margin = String(this._cfg.margin_percent);
    this._vat = String(this._cfg.vat_percent);

    this._openK = null;
    this._dropFilter = "";
    this._optSig = null;
    this._built = false;

    this._restore();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._render(); return; }

    // Only touch the DOM when the tag list itself changed — hass updates constantly
    // and a blind re-render would eat whatever the user is typing.
    const sig = this._sig();
    if (sig !== this._optSig) {
      this._optSig = sig;
      if (this._openK !== null) this._paintDrop();
      this._paintLines();
    }
  }

  get hass() { return this._hass; }

  getCardSize() { return 8; }

  disconnectedCallback() { this._closeDrop(); }

  // ── data ─────────────────────────────────────────────────
  _sensorData() {
    const st = this._hass && this._hass.states[this._cfg.entity];
    return (st && st.attributes && st.attributes.data) || [];
  }

  // 6th CSV column is optional — missing/blank/unrecognised means enabled.
  _isDisabled(v) {
    if (typeof v === "boolean") return v;
    const s = String(v == null ? "" : v).trim().toLowerCase();
    return s === "disabled" || s === "1" || s === "true" || s === "yes";
  }

  _norm(v) {
    const m = String(v || "").match(/([0-9a-f]{6})/i);
    return m ? "#" + m[1].toUpperCase() : "#808080";
  }

  // Spools usually carry two RFID tags, so the same filament appears twice with
  // different serials. Collapse on type + colour name + price.
  _options() {
    // Two rows naming each other's serial are the two tags on one spool, so
    // they collapse to a single choice even if their type or price differ.
    const partnerOf = new Map();
    for (const r of this._sensorData()) {
      const a = String(r.serial || "").trim().toLowerCase();
      const b = String(r.serial_2 || "").trim().toLowerCase();
      if (a && b) { partnerOf.set(a, b); partnerOf.set(b, a); }
    }

    const map = new Map();
    const claimed = new Set();
    for (const r of this._sensorData()) {
      if (this._isDisabled(r.disabled)) continue;
      const type = String(r.filament || "").trim();
      const name = String(r.color_name || "").trim();
      const price = Number(r.cost_per_kg) || 0;
      if (!type && !name) continue;

      const serial = String(r.serial || "").trim().toLowerCase();
      if (serial && claimed.has(serial)) continue;
      if (serial) {
        claimed.add(serial);
        const other = partnerOf.get(serial);
        if (other) claimed.add(other);
      }

      const key = `${type}|${name}|${price.toFixed(2)}`;
      if (!map.has(key)) {
        map.set(key, { key, type, name, price, color: this._norm(r.color_code) });
      }
    }

    const out = [...map.values()].sort((a, b) => {
      const x = (a.type + " " + a.name).toLowerCase();
      const y = (b.type + " " + b.name).toLowerCase();
      return x < y ? -1 : x > y ? 1 : 0;
    });
    // Always last: filament that is not in the library, priced by hand.
    out.push({ key: OTHER_KEY, type: "Other", name: "enter the price yourself",
               price: 0, color: "#808080", other: true });
    return out;
  }

  _sig() { return this._options().map(o => o.key).join(""); }

  _opt(key) { return this._options().find(o => o.key === key) || null; }

  // ── state helpers ────────────────────────────────────────
  _newLine() { return { _k: this._nextKey++, key: "", grams: "", price: "" }; }

  _line(k) { return this._lines.find(l => l._k === Number(k)); }

  // Accepts "12.5" and "12,5"; treats "1,234.5" as a thousands separator.
  _num(v) {
    let s = String(v == null ? "" : v).replace(/\s/g, "");
    if (!s) return 0;
    if (s.indexOf(",") >= 0 && s.indexOf(".") >= 0) s = s.replace(/,/g, "");
    else s = s.replace(",", ".");
    const n = parseFloat(s);
    return isFinite(n) && n > 0 ? n : 0;
  }

  _money(n) { return `${this._cfg.currency}${(Math.round(n * 100) / 100).toFixed(2)}`; }

  // The per-minute rate is far smaller than a cent — electricity alone lands around
  // 0.0005 — so 2dp currency would show €0.00. Six decimals, trailing zeros trimmed.
  _rateStr(n) {
    const s = (Math.round(n * 1e6) / 1e6).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    return `${this._cfg.currency}${s || "0"}`;
  }

  _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ── persistence (local to the browser, no HA entities involved) ───────────
  _storeKey() { return `bambu-costs-calc:${this._cfg.entity}:${this._cfg.title}`; }

  _save() {
    if (!this._cfg.remember) return;
    try {
      localStorage.setItem(this._storeKey(), JSON.stringify({
        lines: this._lines.map(l => ({ key: l.key, grams: l.grams, price: l.price })),
        minutes: this._minutes, rate: this._rate,
        margin: this._margin, vat: this._vat,
      }));
    } catch (e) { /* private mode / quota — not worth surfacing */ }
  }

  _restore() {
    if (!this._cfg.remember) return;
    try {
      const raw = localStorage.getItem(this._storeKey());
      if (!raw) return;
      const s = JSON.parse(raw);
      if (Array.isArray(s.lines) && s.lines.length) {
        this._lines = s.lines.map(l => ({
          _k: this._nextKey++, key: String(l.key || ""), grams: String(l.grams || ""),
          price: String(l.price || ""),
        }));
      }
      if (s.minutes !== undefined) this._minutes = String(s.minutes);
      if (s.rate !== undefined) this._rate = String(s.rate);
      if (s.margin !== undefined) this._margin = String(s.margin);
      if (s.vat !== undefined) this._vat = String(s.vat);
    } catch (e) { /* corrupt payload — fall back to defaults */ }
  }

  // ── maths ────────────────────────────────────────────────
  // Nothing is rounded until it is displayed.
  _totals() {
    const rows = this._lines.map(l => {
      const o = this._opt(l.key);
      const g = this._num(l.grams);
      // "Other" takes its price from the line rather than the library.
      const price = o ? (o.other ? this._num(l.price) : o.price) : 0;
      return { line: l, opt: o, grams: g, price, cost: o ? (g / 1000) * price : 0 };
    });

    const filament = rows.reduce((a, r) => a + r.cost, 0);
    const grams = rows.reduce((a, r) => a + r.grams, 0);
    const minutes = this._num(this._minutes);
    const rate = this._num(this._rate);
    const runtime = minutes * rate;
    const subtotal = filament + runtime;

    // Markup on cost: price = cost × (1 + m).
    const marginAmt = subtotal * (this._num(this._margin) / 100);
    const net = subtotal + marginAmt;

    const vatAmt = net * (this._num(this._vat) / 100);

    return { rows, filament, grams, minutes, rate, runtime, subtotal,
             marginAmt, net, vatAmt, total: net + vatAmt };
  }

  // ── render ───────────────────────────────────────────────
  _render() {
    this.innerHTML = `
      <ha-card header="${this._esc(this._cfg.title)}">
        <style>
          .cc-wrap { padding: 0 16px 16px; }
          .cc-sec { font-size:11px; text-transform:uppercase; letter-spacing:.4px;
            color:var(--secondary-text-color); margin:6px 0 8px; font-weight:500; }
          /* The picker asks for 200px. When the card is too narrow to give it that
             alongside the weight controls the row wraps, rather than squeezing the
             filament name down to nothing on a phone-width column. */
          .cc-line { display:flex; gap:8px; align-items:center; margin-bottom:8px;
            flex-wrap:wrap; }
          .cc-pick { position:relative; flex:1 1 200px; min-width:0; }
          .cc-tail { display:flex; gap:8px; align-items:center; margin-left:auto; }
          .cc-trig { width:100%; display:flex; align-items:center; gap:8px; text-align:left;
            padding:8px 10px; border-radius:9px; border:1px solid var(--divider-color);
            background:var(--card-background-color); color:var(--primary-text-color);
            font-size:13px; cursor:pointer; min-height:38px; box-sizing:border-box; }
          .cc-trig:hover { border-color:var(--primary-color); }
          .cc-trig.open { border-color:var(--primary-color); }
          /* inset ring so white / very pale swatches stay visible on the light theme
             and dark ones stay visible on the pure-black phone theme */
          .sw { width:18px; height:18px; border-radius:4px; flex:none;
            box-shadow: inset 0 0 0 1px rgba(128,128,128,.55); }
          .cc-lbl { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; }
          .cc-lbl .nm { color:var(--secondary-text-color); }
          .cc-lbl.ph { color:var(--secondary-text-color); }
          .cc-pr { flex:none; font-variant-numeric:tabular-nums;
            color:var(--secondary-text-color); font-size:12px; }
          .cc-caret { flex:none; color:var(--secondary-text-color); font-size:10px; }

          .cc-drop { position:absolute; z-index:9; top:calc(100% + 4px); left:0; right:0;
            background:var(--card-background-color); border:1px solid var(--divider-color);
            border-radius:10px; box-shadow:0 6px 22px rgba(0,0,0,.35); overflow:hidden; }
          .cc-drop input.s { width:100%; box-sizing:border-box; border:none;
            border-bottom:1px solid var(--divider-color); background:transparent;
            color:var(--primary-text-color); font-size:13px; padding:9px 11px; outline:none; }
          .cc-list { max-height:270px; overflow-y:auto; }
          .cc-opt { width:100%; display:flex; align-items:center; gap:8px; text-align:left;
            padding:8px 11px; border:none; background:none; cursor:pointer;
            color:var(--primary-text-color); font-size:13px; }
          .cc-opt:hover, .cc-opt.hl { background:rgba(var(--rgb-primary-color),.14); }
          .cc-opt.sel { background:rgba(var(--rgb-primary-color),.08); }
          .cc-none { padding:14px 11px; font-size:12.5px; color:var(--secondary-text-color); }

          input.g.pr { width:82px; }
          input.g { width:96px; flex:none; box-sizing:border-box; padding:8px 10px;
            border-radius:9px; border:1px solid var(--divider-color);
            background:var(--card-background-color); color:var(--primary-text-color);
            font-size:13px; text-align:right; min-height:38px; }
          input.g:focus, .cc-f input:focus { border-color:var(--primary-color); outline:none; }
          .unit { flex:none; font-size:12px; color:var(--secondary-text-color); width:14px; }
          .cc-cost { flex:none; width:74px; text-align:right; font-size:12px;
            font-variant-numeric:tabular-nums; color:var(--secondary-text-color); }
          .rm { flex:none; background:none; border:none; color:var(--secondary-text-color);
            cursor:pointer; font-size:14px; padding:2px 4px; border-radius:6px; width:24px; }
          .rm:hover { color:var(--error-color,#f44336); }
          .rm.hide { visibility:hidden; }

          .tbtn { background:none; border:1px solid var(--divider-color);
            color:var(--primary-text-color); border-radius:8px; padding:6px 10px;
            font-size:12px; cursor:pointer; }
          .tbtn:hover { border-color:var(--primary-color); color:var(--primary-color); }

          .cc-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
            gap:8px 12px; margin-bottom:4px; }
          .cc-f { display:flex; flex-direction:column; gap:4px; }
          .cc-f label { font-size:11px; color:var(--secondary-text-color); }
          .cc-f input { width:100%; box-sizing:border-box; padding:8px 10px; border-radius:9px;
            border:1px solid var(--divider-color); background:var(--card-background-color);
            color:var(--primary-text-color); font-size:13px; text-align:right; }

          hr.cc-hr { border:none; border-top:1px solid var(--divider-color); margin:14px 0 10px; }
          table.cc-out { width:100%; border-collapse:collapse; font-size:13px; }
          table.cc-out td { padding:3px 0; }
          table.cc-out td.v { text-align:right; font-variant-numeric:tabular-nums;
            white-space:nowrap; }
          table.cc-out td.k { color:var(--secondary-text-color); }
          table.cc-out tr.rule td { border-top:1px solid var(--divider-color); padding-top:7px; }
          table.cc-out tr.tot td { font-size:17px; font-weight:600; padding-top:8px;
            color:var(--primary-text-color); }
          table.cc-out tr.tot td.k { color:var(--primary-text-color); }
          .cc-foot { display:flex; justify-content:space-between; align-items:center;
            margin-top:12px; gap:12px; }
          .cc-note { font-size:11px; color:var(--secondary-text-color); }
        </style>
        <div class="cc-wrap">
          <div class="cc-sec">Filament</div>
          <div class="cc-lines"></div>
          <button class="tbtn add">+ Add filament</button>

          <div class="cc-sec" style="margin-top:16px">Print</div>
          <div class="cc-grid">
            <div class="cc-f"><label>Runtime (min)</label>
              <input class="fi" data-f="minutes" type="text" inputmode="decimal" placeholder="0"></div>
            <div class="cc-f"><label>Rate (${this._esc(this._cfg.currency)}/min)</label>
              <input class="fi" data-f="rate" type="text" inputmode="decimal"></div>
            <div class="cc-f"><label>Margin (%)</label>
              <input class="fi" data-f="margin" type="text" inputmode="decimal"></div>
            <div class="cc-f"><label>VAT (%)</label>
              <input class="fi" data-f="vat" type="text" inputmode="decimal"></div>
          </div>

          <hr class="cc-hr">
          <table class="cc-out"><tbody></tbody></table>

          <div class="cc-foot">
            <span class="cc-note"></span>
            <button class="tbtn reset">Reset</button>
          </div>
        </div>
      </ha-card>`;

    this._built = true;
    this._optSig = this._sig();

    const q = s => this.querySelector(s);

    q(".add").addEventListener("click", () => {
      this._lines.push(this._newLine());
      this._paintLines();
      this._save();
    });

    q(".reset").addEventListener("click", () => {
      this._lines = [this._newLine()];
      this._minutes = "";
      this._rate = String(this._cfg.rate_per_minute);
      this._margin = String(this._cfg.margin_percent);
      this._vat = String(this._cfg.vat_percent);
      this._syncFields();
      this._paintLines();
      this._save();
    });

    this.querySelectorAll("input.fi").forEach(inp => {
      inp.addEventListener("input", e => {
        this["_" + e.target.dataset.f] = e.target.value;
        this._calc();
        this._save();
      });
    });

    this._syncFields();
    this._paintLines();
  }

  _syncFields() {
    const set = (f, v) => {
      const el = this.querySelector(`input.fi[data-f="${f}"]`);
      if (el) el.value = v;
    };
    set("minutes", this._minutes);
    set("rate", this._rate);
    set("margin", this._margin);
    set("vat", this._vat);
  }

  _optLabel(o) {
    return `<span class="sw" style="background:${this._esc(o.color)}"></span>
      <span class="cc-lbl">${this._esc(o.type)}${o.name
        ? ` <span class="nm">· ${this._esc(o.name)}</span>` : ""}</span>
      <span class="cc-pr">${o.other ? "" : this._money(o.price) + "/kg"}</span>`;
  }

  _paintLines() {
    const host = this.querySelector(".cc-lines");
    if (!host) return;
    const many = this._lines.length > 1;

    host.innerHTML = this._lines.map(l => {
      const o = this._opt(l.key);
      const inner = o ? this._optLabel(o)
        : `<span class="sw" style="background:transparent"></span>
           <span class="cc-lbl ph">Select filament…</span>`;
      return `<div class="cc-line" data-k="${l._k}">
        <span class="cc-pick">
          <button class="cc-trig" data-k="${l._k}">${inner}<span class="cc-caret">▾</span></button>
        </span>
        <span class="cc-tail">
          ${o && o.other ? `<input class="g pr" data-k="${l._k}" type="text" inputmode="decimal"
                 placeholder="price" value="${this._esc(l.price || "")}"
                 aria-label="Price per kilogram">
            <span class="unit">/kg</span>` : ""}
          <input class="g" data-k="${l._k}" type="text" inputmode="decimal"
                 placeholder="0" value="${this._esc(l.grams)}" aria-label="Weight in grams">
          <span class="unit">g</span>
          <span class="cc-cost" data-k="${l._k}"></span>
          <button class="rm ${many ? "" : "hide"}" data-k="${l._k}" title="Remove">✕</button>
        </span>
      </div>`;
    }).join("");

    host.querySelectorAll("button.cc-trig").forEach(b => {
      b.addEventListener("click", e => {
        e.stopPropagation();
        const k = Number(e.currentTarget.dataset.k);
        if (this._openK === k) this._closeDrop(); else this._openDrop(k);
      });
    });

    host.querySelectorAll("input.g").forEach(inp => {
      inp.addEventListener("input", e => {
        const l = this._line(e.target.dataset.k);
        if (!l) return;
        if (e.target.classList.contains("pr")) l.price = e.target.value;
        else l.grams = e.target.value;
        this._calc();
        this._save();
      });
    });

    host.querySelectorAll("button.rm").forEach(b => {
      b.addEventListener("click", e => {
        const k = Number(e.currentTarget.dataset.k);
        if (this._lines.length <= 1) return;
        if (this._openK === k) this._closeDrop();
        this._lines = this._lines.filter(l => l._k !== k);
        this._paintLines();
        this._save();
      });
    });

    this._calc();
  }

  // ── dropdown ─────────────────────────────────────────────
  _openDrop(k) {
    this._closeDrop();
    this._openK = k;
    this._dropFilter = "";
    this._hl = 0;
    this._paintDrop();

    this._away = ev => {
      const pick = this.querySelector(`.cc-line[data-k="${k}"] .cc-pick`);
      if (pick && !pick.contains(ev.target)) this._closeDrop();
    };
    this._keys = ev => {
      if (ev.key === "Escape") { ev.preventDefault(); this._closeDrop(); }
    };
    document.addEventListener("click", this._away, true);
    document.addEventListener("keydown", this._keys);

    const s = this.querySelector(".cc-drop input.s");
    if (s) s.focus();
  }

  _closeDrop() {
    if (this._away) { document.removeEventListener("click", this._away, true); this._away = null; }
    if (this._keys) { document.removeEventListener("keydown", this._keys); this._keys = null; }
    const d = this.querySelector(".cc-drop");
    if (d) d.remove();
    this.querySelectorAll(".cc-trig.open").forEach(t => t.classList.remove("open"));
    this._openK = null;
  }

  _paintDrop() {
    const k = this._openK;
    if (k === null) return;
    const pick = this.querySelector(`.cc-line[data-k="${k}"] .cc-pick`);
    const line = this._line(k);
    if (!pick || !line) return;

    const trig = pick.querySelector(".cc-trig");
    if (trig) trig.classList.add("open");

    const f = this._dropFilter.toLowerCase();
    const all = this._options();
    const list = f
      ? all.filter(o => `${o.type} ${o.name}`.toLowerCase().includes(f))
      : all;
    if (this._hl >= list.length) this._hl = Math.max(0, list.length - 1);

    let drop = pick.querySelector(".cc-drop");
    if (!drop) {
      drop = document.createElement("div");
      drop.className = "cc-drop";
      drop.innerHTML = `<input class="s" type="text" placeholder="Search filament…">
        <div class="cc-list"></div>`;
      pick.appendChild(drop);

      const s = drop.querySelector("input.s");
      s.addEventListener("click", e => e.stopPropagation());
      s.addEventListener("input", e => {
        this._dropFilter = e.target.value;
        this._hl = 0;
        this._paintDrop();
      });
      s.addEventListener("keydown", e => {
        const rows = [...drop.querySelectorAll("button.cc-opt")];
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          if (!rows.length) return;
          this._hl = Math.max(0, Math.min(rows.length - 1,
            this._hl + (e.key === "ArrowDown" ? 1 : -1)));
          this._paintDrop();
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (rows[this._hl]) rows[this._hl].click();
        }
      });
    }

    const body = drop.querySelector(".cc-list");
    body.innerHTML = list.length
      ? list.map((o, i) => `<button class="cc-opt${o.key === line.key ? " sel" : ""}${
          i === this._hl ? " hl" : ""}" data-key="${this._esc(o.key)}">${
          this._optLabel(o)}</button>`).join("")
      : `<div class="cc-none">${all.length
          ? "No filament matches that search."
          : "No enabled filament found in " + this._esc(this._cfg.entity) + "."}</div>`;

    body.querySelectorAll("button.cc-opt").forEach(b => {
      b.addEventListener("click", e => {
        e.stopPropagation();
        line.key = e.currentTarget.dataset.key;
        this._closeDrop();
        this._paintLines();
        this._save();
      });
    });

    const hl = body.querySelector("button.cc-opt.hl");
    if (hl && hl.scrollIntoView) hl.scrollIntoView({ block: "nearest" });
  }

  // ── output ───────────────────────────────────────────────
  _calc() {
    const t = this._totals();

    t.rows.forEach(r => {
      const el = this.querySelector(`.cc-cost[data-k="${r.line._k}"]`);
      if (el) el.textContent = r.opt && r.grams ? this._money(r.cost) : "";
    });

    const rows = [
      ["Filament" + (t.grams ? ` · ${(Math.round(t.grams * 100) / 100)} g` : ""),
       this._money(t.filament), ""],
      ["Runtime" + (t.minutes ? ` · ${t.minutes} min × ${this._rateStr(t.rate)}` : ""),
       this._money(t.runtime), ""],
      ["Cost subtotal", this._money(t.subtotal), "rule"],
      [`Margin · ${this._num(this._margin)}%`, "+ " + this._money(t.marginAmt), ""],
      ["Net price", this._money(t.net), "rule"],
      [`VAT · ${this._num(this._vat)}%`, "+ " + this._money(t.vatAmt), ""],
      ["Total", this._money(t.total), "tot rule"],
    ];

    const tb = this.querySelector("table.cc-out tbody");
    if (tb) {
      tb.innerHTML = rows.map(([k, v, cls]) =>
        `<tr class="${cls}"><td class="k">${this._esc(k)}</td>
         <td class="v">${this._esc(v)}</td></tr>`).join("");
    }

    const note = this.querySelector(".cc-note");
    if (note) {
      const missing = t.rows.filter(r => !r.opt && this._num(r.line.grams) > 0).length;
      note.textContent = missing
        ? `${missing} row${missing > 1 ? "s have" : " has"} a weight but no filament selected`
        : "";
    }
  }
}

// Defensive: a card loaded twice (stale resource plus new one) would
// otherwise throw on the second define and register nothing at all.
if (!customElements.get("bambu-costs-calculator")) customElements.define("bambu-costs-calculator", BambuCostsCalculator);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "bambu-costs-calculator")) window.customCards.push({
  type: "bambu-costs-calculator",
  name: "Bambu Costs: Cost Calculator",
  description: "Manual print-cost estimate from the filament tag list, runtime, margin and VAT",
});
