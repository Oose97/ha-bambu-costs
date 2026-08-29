// The job on the printer, as the row it will be logged as — editable while
// it prints. Fields the user touches are stored as an overlay by the
// integration and win at logging time; everything untouched keeps following
// live data. Measured values (elapsed, layer, energy, electricity) are shown
// read-only: they are captured at the finish, not decided in advance.
const BPN_FIELDS = [
  { k: "layers",      t: "Layers",        num: true, w: 7 },
  { k: "weight",      t: "Weight",        num: true, w: 9, unit: "g" },
  { k: "length",      t: "Length",        num: true, w: 9, unit: "m" },
  { k: "nozzle",      t: "Nozzle",        w: 6, combo: true },
  { k: "nozzle_type", t: "Nozzle type",   w: 22, combo: true },
  { k: "types",       t: "Material",      w: 24 },
  { k: "f_cost",      t: "Filament cost", num: true, w: 9, unit: "$" },
];

// The nozzle combos, exactly as the jobs table has them: focusing the field
// drops a popup listing EVERY option, the field itself stays free text, the
// stored value keeps the printer's own spelling and only the label is pretty.
const BPN_NOZZLE_SIZES = ["0.2", "0.4", "0.6", "0.8"];
const BPN_NOZZLE_TYPES = [
  "stainless_steel",
  "hardened_steel",
  "high_flow_hardened_steel",
  "tungsten_carbide",
  "high_flow_tungsten_carbide",
];

class BambuCostsPrintingNow extends HTMLElement {
  setConfig(cfg) {
    if (!cfg.entity) throw new Error("Define an entity (sensor.bambu_costs_current_job)");
    this._cfg = Object.assign({ title: "Printing now", currency: null }, cfg);
    this._built = false;
    this._sig = null;
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._cfg.entity];
    if (!this._cfg.currency) {
      this._cfg.currency = (st && st.attributes && st.attributes.currency) || "€";
    }
    if (!this._built) { this._render(); this._paint(); return; }
    // Never repaint under the user's cursor — a focused input means an edit
    // is in progress, and the change event will bring everything back in
    // sync through the service round-trip anyway.
    if (this.contains(document.activeElement)) return;
    const sig = JSON.stringify((st && st.attributes) || {}) + (st ? st.state : "");
    if (sig === this._sig) return;
    this._sig = sig;
    this._paint();
  }

  getCardSize() { return 6; }

  // ── data ─────────────────────────────────────────────────
  _st() { return this._hass && this._hass.states[this._cfg.entity]; }
  _attrs() { const st = this._st(); return (st && st.attributes) || {}; }
  _row() { return this._attrs().row || {}; }
  _edited() { return new Set(this._attrs().edited || []); }

  _esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  _cur() {
    const cur = this._cfg.currency;
    return { EUR: "€", USD: "$", GBP: "£" }[cur] || cur;
  }

  _hmin(m) { return `${Math.floor(m / 60)}h ${Math.round(m % 60)}min`; }

  // "high_flow_hardened_steel" → "HF Hardened Steel", like the jobs table.
  _typeDisp(v) {
    return String(v || "")
      .split("_")
      .map(w => w ? w[0].toUpperCase() + w.slice(1) : w)
      .join(" ")
      .replace(/^High Flow\b/, "HF");
  }

  // Display transform per field; the stored value keeps the raw spelling.
  _disp(k, v) {
    if (k === "nozzle") return String(v || "").replace(/^0(?=[.,])/, "");
    if (k === "nozzle_type") return this._typeDisp(v);
    return v || "";
  }

  _num(v, dp) {
    const n = parseFloat(v);
    return isNaN(n) ? "" : (dp === undefined ? n : n.toFixed(dp));
  }

  _withEntry(data) {
    const id = this._attrs().entry_id;
    return id ? Object.assign({ entry_id: id }, data) : data;
  }

  // ── shell ────────────────────────────────────────────────
  _render() {
    this.innerHTML = `
      <ha-card header="${this._esc(this._cfg.title)}">
        <style>
          /* Sized against the card itself, not the viewport — a full-width
             card and a narrow column each get a layout that fits them. */
          .bpn-wrap { padding:0 16px 16px; font-size:13px; container-type:inline-size; }
          .bpn-idle { padding:28px 0 14px; text-align:center; opacity:.5; }
          .bpn-top { display:flex; gap:16px; align-items:stretch; }
          .bpn-top img { width:min(38cqw, 340px); min-width:160px; aspect-ratio:1;
            height:auto; object-fit:contain; border-radius:12px; align-self:flex-start;
            box-shadow:0 0 0 1px var(--divider-color); cursor:pointer; flex:none; }
          /* Maintenance runs get a wrench where the render would be — the
             log gets no picture, so the card should not promise one. */
          .bpn-covm { width:min(38cqw, 340px); min-width:160px; aspect-ratio:1;
            border-radius:12px; align-self:flex-start; flex:none;
            display:flex; align-items:center; justify-content:center;
            box-shadow:0 0 0 1px var(--divider-color);
            color:var(--secondary-text-color); }
          .bpn-covm svg { width:45%; height:45%; opacity:.55; }
          .bpn-mnote { margin-top:10px; padding:8px 10px; border-radius:8px;
            font-size:12.5px; background:rgba(255,152,0,.14); }
          .bpn-head { flex:1; min-width:0; }
          .bpn-sub { font-size:12px; color:var(--secondary-text-color); margin-top:4px; }
          .bpn-meas { display:flex; flex-wrap:wrap; gap:6px 14px; margin:12px 0 4px;
            font-size:12px; color:var(--secondary-text-color); }
          .bpn-meas b { color:var(--primary-text-color); font-weight:600; }
          /* auto-fill with a bounded track: a wide card gets more columns,
             never one field stretched across half a screen. */
          .bpn-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr));
            gap:2px 22px; margin-top:6px; }
          .bpn-fieldrow { display:flex; align-items:center; justify-content:space-between;
            gap:10px; padding:5px 0; border-bottom:1px solid var(--divider-color);
            max-width:300px; }
          @container (max-width:520px) {
            .bpn-top { flex-direction:column; }
            .bpn-top img { width:100%; max-height:240px; min-width:0; aspect-ratio:auto; }
            .bpn-covm { width:100%; aspect-ratio:auto; height:140px; min-width:0; }
            .bpn-fieldrow { max-width:none; }
          }
          .bpn-label { color:var(--secondary-text-color); font-size:12px; white-space:nowrap; }
          input.cell { padding:4px 6px; border-radius:7px; border:1px solid transparent;
            background:transparent; color:var(--primary-text-color); font:inherit;
            font-size:13px; min-width:0; }
          input.cell:hover { border-color:var(--divider-color); }
          input.cell:focus { border-color:var(--primary-color);
            background:var(--card-background-color); outline:none; }
          input.cell.num { text-align:right; appearance:textfield; -moz-appearance:textfield; }
          input.cell.num::-webkit-outer-spin-button,
          input.cell.num::-webkit-inner-spin-button { -webkit-appearance:none; margin:0; }
          input.cell.job { font-size:15px; font-weight:600; width:100%; }
          /* A touched field wears the accent: the overlay owns it now. */
          input.cell.ed, input.tsw.ed { box-shadow:inset 2px 0 0 var(--primary-color); }
          .cu { font-size:11px; color:var(--secondary-text-color); white-space:nowrap; }
          .bpn-trays { margin-top:10px; }
          .bpn-trayhead { font-weight:600; font-size:12.5px; margin:8px 0 2px; }
          /* Table-shaped: the name column takes the slack, the number columns
             stay the width of their numbers — at any card width. */
          .trrow { display:grid; grid-template-columns:auto minmax(140px, 1fr) auto auto auto;
            gap:2px 14px; align-items:center; padding:7px 0;
            border-bottom:1px solid var(--divider-color); }
          .trrow .trmain { min-width:0; display:flex; flex-direction:column; }
          .trline { display:flex; gap:4px; align-items:center; margin:1px 0;
            justify-content:flex-end; }
          .trmain .trline { justify-content:flex-start; }
          @container (max-width:520px) {
            .trrow { grid-template-columns:auto 1fr auto; }
            .trrow .trline.tn { grid-column:2 / -1; }
          }
          .tsw { width:26px; height:26px; padding:0; border:none; background:none;
            border-radius:5px; cursor:pointer; flex:none;
            box-shadow:0 0 0 1px var(--divider-color); }
          .bpn-foot { display:flex; justify-content:space-between; align-items:center;
            margin-top:12px; min-height:28px; font-size:12px;
            color:var(--secondary-text-color); }
          .tbtn { background:none; border:1px solid var(--divider-color);
            color:var(--primary-text-color); border-radius:8px; padding:5px 10px;
            font-size:12px; cursor:pointer; white-space:nowrap; }
          .tbtn:hover { border-color:var(--primary-color); color:var(--primary-color); }
          .bpn-msg.err { color:var(--error-color,#f44336); }
          .bpn-dd { position:fixed; z-index:100000; background:var(--card-background-color);
            border:1px solid var(--divider-color); border-radius:8px; padding:4px 0;
            box-shadow:0 6px 20px rgba(0,0,0,.28); font-size:12.5px;
            max-height:40vh; overflow-y:auto; }
          .bpn-dd .opt { padding:5px 12px; cursor:pointer; white-space:nowrap;
            color:var(--primary-text-color); }
          .bpn-dd .opt:hover { background:rgba(var(--rgb-primary-color),.12); }
          .bpn-dd .opt.on { color:var(--primary-color); font-weight:600; }
        </style>
        <div class="bpn-wrap"></div>
      </ha-card>`;
    this._built = true;

    const wrap = this.querySelector(".bpn-wrap");

    wrap.addEventListener("change", e => {
      const el = e.target.closest("[data-f], [data-tf]");
      if (el) this._edit(el);
    });

    wrap.addEventListener("click", e => {
      if (e.target.closest(".reset")) {
        if (confirm("Drop every edit and follow the printer again?")) this._reset();
        return;
      }
      const img = e.target.closest("img.cov");
      if (img && img.src) this._openImage(img.src);
    });

    // The nozzle combos: the full option list on focus, free text kept.
    wrap.addEventListener("focusin", e => {
      const inp = e.target.closest("input.combo");
      if (inp) this._openCombo(inp);
    });
    wrap.addEventListener("focusout", () => this._closeCombo());
    wrap.addEventListener("keydown", e => {
      if (e.key === "Escape") this._closeCombo();
    });
  }

  _openCombo(inp) {
    this._closeCombo();
    const f = inp.dataset.f;
    const opts = f === "nozzle" ? BPN_NOZZLE_SIZES : BPN_NOZZLE_TYPES;
    const label = v => f === "nozzle" ? v.replace(/^0(?=\.)/, "") : this._typeDisp(v);

    const dd = document.createElement("div");
    dd.className = "bpn-dd";
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
      inp.dispatchEvent(new Event("change", { bubbles: true }));
    });

    this.appendChild(dd);
    const r = inp.getBoundingClientRect();
    dd.style.left = r.left + "px";
    dd.style.minWidth = Math.max(r.width, 90) + "px";
    const h = dd.offsetHeight;
    dd.style.top = (r.bottom + h + 4 > window.innerHeight ? r.top - h - 2 : r.bottom + 2) + "px";
    this._dd = dd;
  }

  _closeCombo() {
    if (this._dd) { this._dd.remove(); this._dd = null; }
  }

  // ── body ─────────────────────────────────────────────────
  _paint() {
    const wrap = this.querySelector(".bpn-wrap");
    const st = this._st();
    if (!st || st.state !== "printing") {
      wrap.innerHTML = `<div class="bpn-idle">No print running</div>`;
      return;
    }

    const row = this._row();
    const edited = this._edited();
    const cur = this._esc(this._cur());
    const planned = parseFloat(this._attrs().mins_planned) || 0;

    // The slicer's render of the job, via the printer integration's image
    // entity — its entity_picture carries a fresh access token every update.
    const coverEntity = this._attrs().cover_entity;
    const coverState = coverEntity && this._hass.states[coverEntity];
    const coverSrc = (coverState && coverState.attributes
      && coverState.attributes.entity_picture) || "";

    const ed = k => edited.has(k) ? " ed" : "";
    const fieldRow = f => `
      <div class="bpn-fieldrow">
        <span class="bpn-label">${this._esc(f.t)}</span>
        <span style="display:flex;align-items:center;gap:3px">
          <input class="cell${f.num ? " num" : ""}${f.combo ? " combo" : ""}${ed(f.k)}"
            ${f.num ? `type="number" step="any"` : `type="text" autocomplete="off"`}
            data-f="${f.k}" style="width:${f.w}ch"
            value="${this._esc(f.num ? this._num(row[f.k]) : this._disp(f.k, row[f.k]))}">
          ${f.unit ? `<span class="cu">${f.unit === "$" ? cur : f.unit}</span>` : ""}
        </span>
      </div>`;

    const trayRow = (t, i) => `
      <div class="trrow">
        <input type="color" class="tsw${ed(`trays.${i}.color`)}" data-i="${i}" data-tf="color"
          value="${this._esc(/^#[0-9a-f]{6}/i.test(t.color || "") ? t.color.slice(0, 7) : "#808080")}">
        <span class="trmain">
          <span class="trline">
            <input class="cell${ed(`trays.${i}.label`)}" data-i="${i}" data-tf="label"
              value="${this._esc(t.label || "")}" style="width:6ch" title="Slot">
            <input class="cell${ed(`trays.${i}.type`)}" data-i="${i}" data-tf="type"
              value="${this._esc(t.type || "")}" style="width:15ch" placeholder="material">
          </span>
          <span class="trline">
            <input class="cell${ed(`trays.${i}.name`)}" data-i="${i}" data-tf="name"
              value="${this._esc(t.name || "")}" style="width:21ch" placeholder="colour name">
          </span>
        </span>
        <span class="trline tn"><input class="cell num${ed(`trays.${i}.weight`)}" type="number" step="any"
          data-i="${i}" data-tf="weight" value="${this._num(t.weight)}" style="width:8ch"><span class="cu">g</span></span>
        <span class="trline tn"><input class="cell num${ed(`trays.${i}.price`)}" type="number" step="any"
          data-i="${i}" data-tf="price" value="${this._num(t.price)}" style="width:8ch"><span class="cu">${cur}/kg</span></span>
        <span class="trline tn"><input class="cell num${ed(`trays.${i}.cost`)}" type="number" step="any"
          data-i="${i}" data-tf="cost" value="${this._num(t.cost)}" style="width:8ch"><span class="cu">${cur}</span></span>
      </div>`;

    const layers = this._num(row.layers, 0);
    const done = this._num(row.layers_done, 0);
    const maint = !!this._attrs().maintenance;
    // mdi:wrench — the log gets no picture in maintenance mode.
    const wrench = `<div class="bpn-covm" title="Maintenance mode"><svg viewBox="0 0 24 24">
      <path fill="currentColor" d="M22.7,19L13.6,9.9C14.5,7.6 14,4.9 12.1,3C10.1,1
      7.1,0.6 4.7,1.7L9,6L6,9L1.6,4.7C0.4,7.1 0.9,10.1 2.9,12.1C4.8,14 7.5,14.5
      9.8,13.6L18.9,22.7C19.3,23.1 19.9,23.1 20.3,22.7L22.6,20.4C23.1,20 23.1,19.3
      22.7,19Z"/></svg></div>`;
    const sub = `${this._esc(row.time || "0h 0min")} elapsed${
      planned > 0 ? ` of ~${this._esc(this._hmin(planned))}` : ""}${
      layers ? ` · layer ${done || "?"} / ${layers}` : ""}`;

    if (maint) {
      // Representative of what will be logged: the name is Maintenance, the
      // bill is electricity, and no filament figure survives — so none are
      // offered for editing.
      wrap.innerHTML = `
        <div class="bpn-top">
          ${wrench}
          <div class="bpn-head">
            <input class="cell job" value="Maintenance" disabled
              title="Maintenance mode names the job itself">
            <div class="bpn-sub">${sub}</div>
            <div class="bpn-meas">
              <span>Energy <b>${this._num(row.kwh, 3)}</b> kWh</span>
              <span>Electricity <b>${this._num(row.p_cost, 4)}</b> ${cur}</span>
              <span>Will log <b>${this._num(row.p_cost, 4)}</b> ${cur}</span>
            </div>
            <div class="bpn-mnote">Maintenance mode — this run logs as
              electricity only: no filament figures, no picture. The switch on
              the device page turns it off.</div>
          </div>
        </div>`;
      return;
    }

    wrap.innerHTML = `
      <div class="bpn-top">
        ${coverSrc ? `<img class="cov" src="${this._esc(coverSrc)}" alt="">` : ""}
        <div class="bpn-head">
          <input class="cell job${ed("job")}" data-f="job" value="${this._esc(row.job || "")}">
          <div class="bpn-sub">${sub}</div>
          <div class="bpn-meas">
            <span>Energy <b>${this._num(row.kwh, 3)}</b> kWh</span>
            <span>Electricity <b>${this._num(row.p_cost, 4)}</b> ${cur}</span>
            <span>Total so far <b>${this._num(row.cost, 4)}</b> ${cur}</span>
            ${parseFloat(this._attrs().cost_predicted) > 0
              ? `<span title="Filament plus the projected electricity — the print's own rate past 5% of the plan, the last print's before that">Predicted total <b>${
                  this._num(this._attrs().cost_predicted, 4)}</b> ${cur}</span>`
              : ""}
          </div>
          <div class="bpn-grid">${BPN_FIELDS.map(fieldRow).join("")}</div>
        </div>
      </div>
      ${(row.trays || []).length ? `<div class="bpn-trays">
        <div class="bpn-trayhead">Filament</div>
        ${(row.trays || []).map(trayRow).join("")}
      </div>` : ""}
      <div class="bpn-foot">
        <span class="bpn-msg">${edited.size
          ? `${edited.size} field${edited.size === 1 ? "" : "s"} edited — the log will use them`
          : "Edits made here are what the finished job logs"}</span>
        ${edited.size ? `<button class="tbtn reset">↺ Reset edits</button>` : ""}
      </div>`;
  }

  // ── edits ────────────────────────────────────────────────
  async _edit(el) {
    const row = this._row();
    const patch = {};

    if (el.dataset.f) {
      const k = el.dataset.f;
      const def = BPN_FIELDS.find(f => f.k === k);
      if (k === "nozzle") {
        // The display drops the leading zero; the stored value never does.
        const t = String(el.value).trim().replace(",", ".");
        patch[k] = t.startsWith(".") ? "0" + t : t;
      } else if (k === "nozzle_type") {
        // A pretty label (or the raw spelling, any case) maps back to the
        // printer's own value; anything else is free text, stored as typed.
        const t = String(el.value).trim();
        const hit = BPN_NOZZLE_TYPES.find(o =>
          o.toLowerCase() === t.toLowerCase()
          || this._typeDisp(o).toLowerCase() === t.toLowerCase());
        patch[k] = hit || t;
      } else {
        patch[k] = def && def.num
          ? parseFloat(String(el.value).replace(",", ".")) || 0
          : el.value;
      }
    } else {
      const i = Number(el.dataset.i);
      const f = el.dataset.tf;
      const trays = (row.trays || []).map(t => Object.assign({}, t));
      const t = trays[i];
      if (!t) return;
      const numeric = f === "weight" || f === "price" || f === "cost";
      t[f] = numeric ? (parseFloat(String(el.value).replace(",", ".")) || 0) : el.value;
      const tp = { [f]: t[f] };
      // Weight or price moved: the line's cost follows, the same way the
      // logger computes it; a direct cost edit stands on its own. The row's
      // weight and filament cost then follow the slots.
      if (f === "weight" || f === "price") {
        t.cost = Math.round((parseFloat(t.weight) || 0) / 1000 * (parseFloat(t.price) || 0) * 1e4) / 1e4;
        tp.cost = t.cost;
        this._setVal(`[data-i="${i}"][data-tf="cost"]`, t.cost);
      }
      patch.trays = { [String(i)]: tp };
      if (numeric) {
        patch.weight = Math.round(trays.reduce((s, x) => s + (parseFloat(x.weight) || 0), 0) * 1e3) / 1e3;
        patch.f_cost = Math.round(trays.reduce((s, x) => s + (parseFloat(x.cost) || 0), 0) * 1e4) / 1e4;
        this._setVal(`[data-f="weight"]`, patch.weight);
        this._setVal(`[data-f="f_cost"]`, patch.f_cost);
      }
    }

    try {
      await this._hass.callService("bambu_costs", "update_current_job",
        this._withEntry({ patch }));
    } catch (err) {
      const m = this.querySelector(".bpn-msg");
      if (m) { m.textContent = "Could not save the edit: " + (err.message || err); m.className = "bpn-msg err"; }
      return;
    }
    // The sensor's refresh repaints unless an input holds focus; either way
    // the overlay is stored, so nothing is lost by not repainting now.
    this._sig = null;
    if (!this.contains(document.activeElement)) this._paint();
  }

  _setVal(sel, v) { const el = this.querySelector(sel); if (el) el.value = v; }

  async _reset() {
    try {
      await this._hass.callService("bambu_costs", "update_current_job",
        this._withEntry({ clear: true }));
    } catch (err) { /* the message line will show stale state at worst */ }
    this._sig = null;
    this._paint();
  }

  _openImage(src) {
    const ov = document.createElement("div");
    ov.style.cssText = `position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.72);
      display:flex;align-items:center;justify-content:center;padding:24px;`;
    // The render is a transparent PNG — over the dark overlay it would float
    // as a ghost, so the enlarged view gets a solid card-coloured backing.
    ov.innerHTML = `<img src="${this._esc(src)}" style="max-width:min(90vw,640px);
      max-height:80vh;border-radius:14px;padding:16px;box-sizing:border-box;
      background:var(--card-background-color,#fff);
      box-shadow:0 12px 48px rgba(0,0,0,.5);">`;
    const close = () => { ov.remove(); document.removeEventListener("keydown", esc); };
    const esc = e => { if (e.key === "Escape") close(); };
    ov.addEventListener("click", close);
    document.addEventListener("keydown", esc);
    document.body.appendChild(ov);
  }
}

// Defensive: a card loaded twice (stale resource plus new one) would
// otherwise throw on the second define and register nothing at all.
if (!customElements.get("bambu-costs-printing-now")) customElements.define("bambu-costs-printing-now", BambuCostsPrintingNow);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "bambu-costs-printing-now")) window.customCards.push({
  type: "bambu-costs-printing-now",
  name: "Bambu Costs: Printing Now",
  description: "The job on the printer, editable while it prints",
});
