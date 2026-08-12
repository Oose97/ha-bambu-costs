// The job on the printer, as the row it will be logged as — editable while
// it prints. Fields the user touches are stored as an overlay by the
// integration and win at logging time; everything untouched keeps following
// live data. Measured values (elapsed, layer, energy, electricity) are shown
// read-only: they are captured at the finish, not decided in advance.
const BPN_FIELDS = [
  { k: "layers",      t: "Layers",        num: true, w: 7 },
  { k: "weight",      t: "Weight",        num: true, w: 9, unit: "g" },
  { k: "length",      t: "Length",        num: true, w: 9, unit: "m" },
  { k: "nozzle",      t: "Nozzle",        w: 6 },
  { k: "nozzle_type", t: "Nozzle type",   w: 22 },
  { k: "types",       t: "Material",      w: 24 },
  { k: "f_cost",      t: "Filament cost", num: true, w: 9, unit: "$" },
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
          .bpn-wrap { padding:0 16px 16px; font-size:13px; }
          .bpn-idle { padding:28px 0 14px; text-align:center; opacity:.5; }
          .bpn-top { display:flex; gap:14px; align-items:flex-start; }
          .bpn-top img { width:96px; height:96px; object-fit:cover; border-radius:10px;
            box-shadow:0 0 0 1px var(--divider-color); cursor:pointer; flex:none; }
          .bpn-head { flex:1; min-width:0; }
          .bpn-sub { font-size:12px; color:var(--secondary-text-color); margin-top:4px; }
          .bpn-meas { display:flex; flex-wrap:wrap; gap:6px 14px; margin:12px 0 4px;
            font-size:12px; color:var(--secondary-text-color); }
          .bpn-meas b { color:var(--primary-text-color); font-weight:600; }
          .bpn-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr));
            gap:2px 18px; margin-top:6px; }
          .bpn-fieldrow { display:flex; align-items:center; justify-content:space-between;
            gap:10px; padding:5px 0; border-bottom:1px solid var(--divider-color); }
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
          .trrow { display:flex; align-items:center; gap:10px; padding:7px 0;
            border-bottom:1px solid var(--divider-color); }
          .trrow .trmain { flex:1; min-width:0; display:flex; flex-direction:column; }
          .trline { display:flex; gap:4px; align-items:center; margin:1px 0; }
          .trnum { display:flex; flex-direction:column; align-items:flex-end; }
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
          <input class="cell${f.num ? " num" : ""}${ed(f.k)}"
            ${f.num ? `type="number" step="any"` : `type="text"`}
            data-f="${f.k}" style="width:${f.w}ch"
            value="${this._esc(f.num ? this._num(row[f.k]) : row[f.k] || "")}">
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
        <span class="trnum">
          <span class="trline"><input class="cell num${ed(`trays.${i}.weight`)}" type="number" step="any"
            data-i="${i}" data-tf="weight" value="${this._num(t.weight)}" style="width:8ch"><span class="cu">g</span></span>
          <span class="trline"><input class="cell num${ed(`trays.${i}.price`)}" type="number" step="any"
            data-i="${i}" data-tf="price" value="${this._num(t.price)}" style="width:8ch"><span class="cu">${cur}/kg</span></span>
          <span class="trline"><input class="cell num${ed(`trays.${i}.cost`)}" type="number" step="any"
            data-i="${i}" data-tf="cost" value="${this._num(t.cost)}" style="width:8ch"><span class="cu">${cur}</span></span>
        </span>
      </div>`;

    const layers = this._num(row.layers, 0);
    const done = this._num(row.layers_done, 0);
    wrap.innerHTML = `
      <div class="bpn-top">
        ${coverSrc ? `<img class="cov" src="${this._esc(coverSrc)}" alt="">` : ""}
        <div class="bpn-head">
          <input class="cell job${ed("job")}" data-f="job" value="${this._esc(row.job || "")}">
          <div class="bpn-sub">${this._esc(row.time || "0h 0min")} elapsed${
            planned > 0 ? ` of ~${this._esc(this._hmin(planned))}` : ""}${
            layers ? ` · layer ${done || "?"} / ${layers}` : ""}</div>
        </div>
      </div>
      <div class="bpn-meas">
        <span>Energy <b>${this._num(row.kwh, 3)}</b> kWh</span>
        <span>Electricity <b>${this._num(row.p_cost, 4)}</b> ${cur}</span>
        <span>Total so far <b>${this._num(row.cost, 4)}</b> ${cur}</span>
      </div>
      <div class="bpn-grid">${BPN_FIELDS.map(fieldRow).join("")}</div>
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
      patch[k] = def && def.num
        ? parseFloat(String(el.value).replace(",", ".")) || 0
        : el.value;
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
    ov.innerHTML = `<img src="${this._esc(src)}" style="max-width:min(90vw,640px);
      max-height:80vh;border-radius:14px;box-shadow:0 12px 48px rgba(0,0,0,.5);">`;
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
