const BCJT_COLS = [
  { k: "ts",          t: "Date",          type: "text", nowrap: true },
  { k: "job",         t: "Job",           type: "text" },
  { k: "time",        t: "Print time",    type: "text", sortKey: "mins", nowrap: true },
  { k: "layers",      t: "Layers",        type: "num" },
  { k: "weight",      t: "Weight",        type: "num", unit: " g",   dp: 1 },
  { k: "length",      t: "Length",        type: "num", unit: " m",   dp: 2 },
  { k: "nozzle",      t: "Nozzle",        type: "text" },
  { k: "nozzle_type", t: "Nozzle type",   type: "text" },
  { k: "kwh",         t: "Energy",        type: "num", unit: " kWh", dp: 3 },
  { k: "f_cost",      t: "Filament",      type: "num", unit: " €",   dp: 2 },
  { k: "p_cost",      t: "Power",         type: "num", unit: " €",   dp: 2 },
  { k: "cost",        t: "Total",         type: "num", unit: " €",   dp: 2, bold: true },
  //{ k: "per100g",     t: "€/100g",        type: "num", dp: 2 },
  { k: "cover",       t: "Image",         type: "cover", sortable: false },
  { k: "trays",       t: "Filament used", type: "trays", sortable: false },
];

class BambuCostsJobsTable extends HTMLElement {
  setConfig(cfg) {
    if (!cfg.entity) throw new Error("Define an entity (sensor.bambu_costs_job_log)");
    this._cfg = Object.assign({
      title: "Print jobs",
      page_size: 20,
      // Only used when a row predates cover_url; the integration serves covers itself.
      image_base: "/bambu-costs-covers/",
    }, cfg);
    this._sort = { key: "ts", dir: -1 };   // newest first
    this._page = 0;
    this._filter = "";
    this._data = [];
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._cfg.entity];
    const data = (st && st.attributes && st.attributes.data) || [];
    const sig = JSON.stringify(data);
    if (sig === this._sig && this._built) return;
    this._sig = sig;
    this._data = data;
    if (!this._built) this._render(); else this._paint();
  }

  getCardSize() { return 12; }

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

  // ── data ─────────────────────────────────────────────────
  _rows() {
    const q = this._filter;
    if (!q) return this._data;
    return this._data.filter(r => {
      const trays = (r.trays || []).map(t => `${t.label} ${t.name}`).join(" ");
      return `${r.ts} ${r.job} ${r.nozzle} ${r.nozzle_type} ${trays}`.toLowerCase().includes(q);
    });
  }

  _sorted() {
    const { key, dir } = this._sort;
    const col = BCJT_COLS.find(c => (c.sortKey || c.k) === key);
    const num = key === "mins" || (col && col.type === "num");
    return this._rows().slice().sort((a, b) => {
      if (num) return ((parseFloat(a[key]) || 0) - (parseFloat(b[key]) || 0)) * dir;
      const x = String(a[key] ?? "").toLowerCase(), y = String(b[key] ?? "").toLowerCase();
      return x < y ? -dir : x > y ? dir : 0;
    });
  }

  _fmt(col, row) {
    const v = row[col.k];
    if (col.type === "num") {
      const n = parseFloat(v);
      if (isNaN(n)) return "—";
      return n.toFixed(col.dp === undefined ? 0 : col.dp) + (col.unit || "");
    }
    return this._esc(v || "—");
  }

  // Trays arrive as structured objects from the integration, so there is no
  // delimited string left to unpick.
  _traysCell(trays) {
    if (!Array.isArray(trays) || !trays.length) return `<span class="muted">—</span>`;
    return trays.map(t => {
      const rgb = this._parseColor(t.color || "");
      const dot = rgb ? `<i class="dot" style="background:${this._css(rgb)}"></i>` : "";

      const weight = isNaN(parseFloat(t.weight)) ? "" : `${parseFloat(t.weight).toFixed(2)} g`;
      const cNum = parseFloat(t.cost);
      const cost = isNaN(cNum) ? "" : `<span class="tcost"> · ${cNum.toFixed(2)} €</span>`;

      const price = isNaN(parseFloat(t.price)) ? "" : ` @ ${parseFloat(t.price).toFixed(2)} €/kg`;
      const tip = this._esc(`${t.name || t.label || ""}${price}`);
      return `<span class="tray" title="${tip}">${dot}${this._esc(t.label || "?")} ${weight}${cost}</span>`;
    }).join("");
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
          .bcjt-scroll { overflow-x:auto; }
          table.bcjt { width:100%; border-collapse:collapse; font-size:12.5px; }
          table.bcjt th { text-align:left; font-weight:500; color:var(--secondary-text-color);
            font-size:11px; text-transform:uppercase; letter-spacing:.4px; white-space:nowrap;
            padding:6px; border-bottom:1px solid var(--divider-color); user-select:none; }
          table.bcjt th.s { cursor:pointer; }
          table.bcjt th.s:hover { color:var(--primary-text-color); }
          table.bcjt th.active { color:var(--primary-color); }
          table.bcjt td { padding:6px; border-bottom:1px solid var(--divider-color);
            vertical-align:middle; }
          table.bcjt td.nw, table.bcjt th.nw { white-space:nowrap; }
          table.bcjt td.num { text-align:right; white-space:nowrap; }
          table.bcjt td.b { font-weight:600; }
          .muted { opacity:.5; }
          .tray { display:inline-flex; align-items:center; white-space:nowrap;
            margin:1px 6px 1px 0; font-size:11.5px; }
          .tcost { opacity:.65; }
          .dot { display:inline-block; width:9px; height:9px; border-radius:2px;
            margin-right:4px; box-shadow:0 0 0 1px var(--secondary-text-color); }
          a.cover { color:var(--primary-color); cursor:pointer; text-decoration:none;
            font-size:11.5px; white-space:nowrap; }
          a.cover:hover { text-decoration:underline; }
          .bcjt-foot { display:flex; justify-content:space-between; align-items:center;
            margin-top:12px; font-size:12px; color:var(--secondary-text-color); gap:12px; }
          .bcjt-pager { display:flex; align-items:center; gap:6px; }
          .bcjt-pager button { background:none; border:1px solid var(--divider-color);
            color:var(--primary-text-color); border-radius:7px; padding:4px 10px;
            font-size:12px; cursor:pointer; }
          .bcjt-pager button[disabled] { opacity:.35; cursor:default; }
        </style>
        <div class="bcjt-wrap">
          <div class="bcjt-tools">
            <input class="f" type="text" placeholder="Filter jobs…">
          </div>
          <div class="bcjt-scroll">
            <table class="bcjt">
              <thead><tr>${BCJT_COLS.map(c => {
                const sk = c.sortKey || c.k;
                const on = c.sortable === false ? "" : "s";
                return `<th class="${on} ${c.nowrap ? "nw" : ""}" data-k="${sk}"
                  ${c.type === "num" ? 'style="text-align:right"' : ""}>${c.t}</th>`;
              }).join("")}</tr></thead>
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
          </div>
        </div>
      </ha-card>`;

    this._built = true;

    this.querySelector("input.f").addEventListener("input", e => {
      this._filter = e.target.value.toLowerCase();
      this._page = 0;
      this._paint();
    });

    this.querySelector("thead").addEventListener("click", e => {
      const th = e.target.closest("th.s");
      if (!th) return;
      const k = th.dataset.k;
      const col = BCJT_COLS.find(c => (c.sortKey || c.k) === k);
      const defDir = (col && (col.type === "num" || c === "ts")) ? -1 : (k === "ts" ? -1 : 1);
      if (this._sort.key === k) this._sort.dir *= -1;
      else this._sort = { key: k, dir: defDir };
      this._page = 0;
      this._paint();
    });

    this.querySelector(".prev").addEventListener("click", () => {
      if (this._page > 0) { this._page--; this._paint(); }
    });
    this.querySelector(".next").addEventListener("click", () => {
      const max = Math.max(0, Math.ceil(this._rows().length / this._cfg.page_size) - 1);
      if (this._page < max) { this._page++; this._paint(); }
    });

    this.querySelector("tbody").addEventListener("click", e => {
      const a = e.target.closest("a.cover");
      if (!a) return;
      e.preventDefault();
      this._openImage(a.dataset.src, a.dataset.cap);
    });

    this._paint();
  }

  // ── body ─────────────────────────────────────────────────
  _paint() {
    const all = this._sorted();
    const size = this._cfg.page_size;
    const pages = Math.max(1, Math.ceil(all.length / size));
    if (this._page > pages - 1) this._page = pages - 1;
    const slice = all.slice(this._page * size, this._page * size + size);

    this.querySelector("tbody").innerHTML = slice.map(r => `<tr>${
      BCJT_COLS.map(c => {
        if (c.type === "cover") {
          const f = r.cover;
          if (!f || f === "—") return `<td><span class="muted">—</span></td>`;
          const src = r.cover_url || (this._cfg.image_base + f);
          return `<td><a class="cover" data-src="${this._esc(src)}"
            data-cap="${this._esc(r.job || f)}">${this._esc(f)}</a></td>`;
        }
        if (c.type === "trays") return `<td>${this._traysCell(r.trays)}</td>`;
        const cls = [c.type === "num" ? "num" : "", c.nowrap ? "nw" : "", c.bold ? "b" : ""]
          .filter(Boolean).join(" ");
        return `<td class="${cls}">${this._fmt(c, r)}</td>`;
      }).join("")
    }</tr>`).join("") || `<tr><td colspan="${BCJT_COLS.length}"
      style="text-align:center;padding:24px" class="muted">No jobs logged yet</td></tr>`;

    this.querySelectorAll("thead th").forEach(th => {
      const on = th.dataset.k === this._sort.key;
      th.classList.toggle("active", on);
      th.textContent = th.textContent.replace(/ [▲▼]$/, "") + (on ? (this._sort.dir === 1 ? " ▲" : " ▼") : "");
    });

    this.querySelector(".bcjt-count").textContent =
      `${all.length} job${all.length === 1 ? "" : "s"}${this._filter ? " (filtered)" : ""}`;
    this.querySelector(".pg").textContent = `${this._page + 1} / ${pages}`;
    this.querySelector(".prev").disabled = this._page === 0;
    this.querySelector(".next").disabled = this._page >= pages - 1;
  }
}

// Defensive: a card loaded twice (stale resource plus new one) would
// otherwise throw on the second define and register nothing at all.
if (!customElements.get("bambu-costs-jobs-table")) customElements.define("bambu-costs-jobs-table", BambuCostsJobsTable);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "bambu-costs-jobs-table")) window.customCards.push({
  type: "bambu-costs-jobs-table",
  name: "Bambu Costs: Jobs Table",
  description: "Sortable, paginated print job history",
});