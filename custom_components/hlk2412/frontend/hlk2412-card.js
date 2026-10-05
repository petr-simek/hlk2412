/* HLK-LD2412 radar card: live per-gate energies and threshold editor.
 *
 * Talks to the hlk2412 integration over its websocket API:
 *   hlk2412/subscribe      live frames + config/connection state
 *   hlk2412/write_config   gates, timeout, polarity, sensitivities
 *   hlk2412/reload_config, hlk2412/engineering, hlk2412/calibrate
 */

const VERSION = "1.2.0";

const STRINGS = {
  en: {
    connected: "Connected",
    via: "via",
    disconnected: "Disconnected",
    engineering: "Engineering",
    basic: "Basic",
    moving: "Moving",
    still: "Still",
    nobody: "Nobody",
    light: "Light",
    move_chart: "Moving energy",
    still_chart: "Still energy",
    eng_off: "Per-gate energies are only reported in engineering mode.",
    eng_on_btn: "Turn on engineering",
    eng_off_btn: "Turn off engineering",
    min_gate: "Min gate",
    max_gate: "Max gate",
    from: "from",
    to: "to",
    unmanned: "Unmanned delay (s)",
    polarity: "OUT pin",
    pol_high: "High when occupied",
    pol_low: "Low when occupied",
    save: "Save to radar",
    discard: "Discard",
    reload: "Read from radar",
    calibrate: "Background calibration",
    calibrating: "Calibrating…",
    reset_peaks: "Reset peaks",
    record: "Record empty room",
    recording: "Recording… {s} s",
    suggest: "Set thresholds = noise + {m}",
    margin: "Margin",
    saved: "Saved to radar",
    dirty: "Unsaved changes",
    hint: "Drag in the chart to set a gate threshold.",
    no_entry: "Select a radar in the card editor.",
    radar: "Radar",
    failed: "Failed: {e}",
  },
  cs: {
    connected: "Připojeno",
    via: "přes",
    disconnected: "Odpojeno",
    engineering: "Engineering",
    basic: "Základní",
    moving: "Pohyb",
    still: "Statický",
    nobody: "Nikdo",
    light: "Světlo",
    move_chart: "Energie pohybu",
    still_chart: "Energie statická",
    eng_off: "Energie jednotlivých gate posílá radar jen v engineering režimu.",
    eng_on_btn: "Zapnout engineering",
    eng_off_btn: "Vypnout engineering",
    min_gate: "Min gate",
    max_gate: "Max gate",
    from: "od",
    to: "do",
    unmanned: "Zpoždění neobsazeno (s)",
    polarity: "OUT pin",
    pol_high: "High při obsazení",
    pol_low: "Low při obsazení",
    save: "Uložit do radaru",
    discard: "Zahodit",
    reload: "Načíst z radaru",
    calibrate: "Kalibrace pozadí",
    calibrating: "Kalibruji…",
    reset_peaks: "Vynulovat špičky",
    record: "Nahrát prázdnou místnost",
    recording: "Nahrávám… {s} s",
    suggest: "Nastavit prahy = šum + {m}",
    margin: "Rezerva",
    saved: "Uloženo do radaru",
    dirty: "Neuložené změny",
    hint: "Tažením v grafu nastavíš práh pro gate.",
    no_entry: "Vyber radar v editoru karty.",
    radar: "Radar",
    failed: "Chyba: {e}",
  },
};

const RECORD_SECONDS = 30;
const W = 560;
const H = 210;
const M = { l: 30, r: 8, t: 14, b: 34 };

const CSS = `
  :host { display: block; }
  ha-card { padding: 12px 16px 16px; }
  .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .title { font-size: 1.15em; font-weight: 500; margin-right: auto; }
  .chip { font-size: .8em; padding: 2px 8px; border-radius: 10px;
          background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .chip.ok { background: rgba(var(--rgb-success-color, 67,160,71), .18); color: var(--success-color, #43a047); }
  .chip.warn { background: rgba(var(--rgb-warning-color, 255,166,0), .18); color: var(--warning-color, #ffa600); }
  .chip.bad { background: rgba(var(--rgb-error-color, 219,68,55), .18); color: var(--error-color, #db4437); }
  .presence { display: flex; gap: 16px; flex-wrap: wrap; margin: 10px 0 4px; font-size: .95em; }
  .presence .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                   margin-right: 6px; background: var(--disabled-color, #bbb); vertical-align: middle; }
  .presence .on.move .dot { background: var(--hlk-move); }
  .presence .on.still .dot { background: var(--hlk-still); }
  .presence .muted { color: var(--secondary-text-color); }
  .charts { display: grid; grid-template-columns: 1fr; gap: 4px; }
  @container (min-width: 900px) { .charts { grid-template-columns: 1fr 1fr; } }
  .chart h4 { margin: 8px 0 0; font-weight: 500; font-size: .9em; color: var(--secondary-text-color); }
  svg { width: 100%; height: auto; touch-action: none; user-select: none; display: block; }
  svg.edit { cursor: ns-resize; }
  .notice { padding: 12px; margin: 8px 0; border-radius: 8px; text-align: center;
            background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .row { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: end; margin-top: 10px; }
  label { display: flex; flex-direction: column; font-size: .8em; color: var(--secondary-text-color); gap: 2px; }
  input, select { font: inherit; font-size: 1rem; color: var(--primary-text-color);
                  background: var(--card-background-color); border: 1px solid var(--divider-color);
                  border-radius: 6px; padding: 4px 6px; }
  input[type=number] { width: 5.5em; }
  button { font: inherit; font-size: .9em; cursor: pointer; border-radius: 18px; padding: 6px 14px;
           border: 1px solid var(--primary-color); background: transparent; color: var(--primary-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button:disabled { opacity: .45; cursor: default; }
  .spacer { flex: 1; }
  .hint { font-size: .8em; color: var(--secondary-text-color); margin-top: 6px; }
  .dirty { color: var(--warning-color, #ffa600); font-size: .85em; align-self: center; }
`;

function esc(value) {
  return String(value).replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

function fmt(template, vars) {
  return template.replace(/\{(\w+)\}/g, (_, k) => vars[k]);
}

class Hlk2412Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._state = null; // config + connection from the integration
    this._live = null; // last report frame
    this._draft = null; // locally edited config (null = clean)
    this._peaks = null;
    this._rec = null; // empty-room recording
    this._noise = null;
    this._margin = 10;
    this._busy = "";
    this._drag = null;
    this._built = false;
  }

  static getConfigElement() {
    return document.createElement("hlk2412-card-editor");
  }

  static async getStubConfig(hass) {
    try {
      const devices = await hass.callWS({ type: "hlk2412/devices" });
      return { entry_id: devices.length ? devices[0].entry_id : "" };
    } catch (e) {
      return { entry_id: "" };
    }
  }

  setConfig(config) {
    const changed = !this._config || this._config.entry_id !== config.entry_id;
    this._config = { ...config };
    if (changed) {
      this._unsubscribe();
      this._state = this._live = this._draft = this._peaks = this._noise = null;
      this._subscribe();
    }
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      const lang = (hass.locale && hass.locale.language) || hass.language || "en";
      this._t = STRINGS[lang.split("-")[0]] || STRINGS.en;
      this._subscribe();
      this._render();
    }
  }

  connectedCallback() {
    this._subscribe();
  }

  disconnectedCallback() {
    this._unsubscribe();
  }

  getCardSize() {
    return 9;
  }

  getGridOptions() {
    return { columns: "full", rows: "auto" };
  }

  // ---------------------------------------------------------------- data

  _subscribe() {
    if (this._unsub || !this._hass || !this._config || !this._config.entry_id || !this.isConnected) {
      return;
    }
    const entryId = this._config.entry_id;
    this._unsub = this._hass.connection
      .subscribeMessage((msg) => this._onMessage(msg), {
        type: "hlk2412/subscribe",
        entry_id: entryId,
      })
      .catch((err) => {
        this._unsub = null;
        this._error = err.message || String(err);
        this._render();
      });
  }

  _unsubscribe() {
    if (this._unsub) {
      const unsub = this._unsub;
      this._unsub = null;
      unsub.then((fn) => fn && fn()).catch(() => {});
    }
  }

  _onMessage(msg) {
    this._error = null;
    if (msg.state) {
      const prevEng = this._state && this._state.engineering_mode;
      this._state = msg.state;
      if (!msg.state.connected) this._live = null;
      if (prevEng !== msg.state.engineering_mode) this._peaks = null;
      this._render();
    }
    if (msg.live) {
      this._live = msg.live;
      this._trackPeaks(msg.live);
      if (!this._built || this._state === null) this._render();
      else this._updateLive();
    }
  }

  _trackPeaks(live) {
    const n = this._gates();
    if (live.move_gate_0_energy == null) return;
    if (!this._peaks) this._peaks = { move: Array(n).fill(0), still: Array(n).fill(0) };
    for (let i = 0; i < n; i++) {
      const m = live[`move_gate_${i}_energy`] || 0;
      const s = live[`static_gate_${i}_energy`] || 0;
      this._peaks.move[i] = Math.max(this._peaks.move[i], m);
      this._peaks.still[i] = Math.max(this._peaks.still[i], s);
      if (this._rec) {
        this._rec.move[i] = Math.max(this._rec.move[i], m);
        this._rec.still[i] = Math.max(this._rec.still[i], s);
      }
    }
  }

  _gates() {
    return (this._state && this._state.gates) || 14;
  }

  _cfg() {
    if (this._draft) return this._draft;
    const s = this._state || {};
    const n = this._gates();
    return {
      min_gate: s.min_gate ?? 0,
      max_gate: s.max_gate ?? n,
      unmanned_duration: s.unmanned_duration ?? 5,
      out_pin_polarity: s.out_pin_polarity ?? 0,
      motion: Array.from({ length: n }, (_, i) => s[`motion_sensitivity_gate_${i}`] ?? 0),
      motionless: Array.from({ length: n }, (_, i) => s[`motionless_sensitivity_gate_${i}`] ?? 0),
    };
  }

  _edit(fn) {
    const draft = this._draft || JSON.parse(JSON.stringify(this._cfg()));
    fn(draft);
    this._draft = draft;
  }

  _isAdmin() {
    return !this._hass || !this._hass.user || this._hass.user.is_admin;
  }

  async _call(type, extra = {}, busy = type) {
    this._busy = busy;
    this._render();
    try {
      const state = await this._hass.callWS({ type, entry_id: this._config.entry_id, ...extra });
      if (state) this._state = state;
      return true;
    } catch (err) {
      this._toast(fmt(this._t.failed, { e: err.message || err.code || err }));
      return false;
    } finally {
      this._busy = "";
      this._render();
    }
  }

  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true })
    );
  }

  async _save() {
    const c = this._cfg();
    const ok = await this._call("hlk2412/write_config", {
      min_gate: c.min_gate,
      max_gate: c.max_gate,
      unmanned_duration: c.unmanned_duration,
      out_pin_polarity: c.out_pin_polarity,
      motion: c.motion,
      motionless: c.motionless,
    }, "save");
    if (ok) {
      this._draft = null;
      this._toast(this._t.saved);
      this._render();
    }
  }

  _startRecording() {
    const n = this._gates();
    this._rec = { until: Date.now() + RECORD_SECONDS * 1000, move: Array(n).fill(0), still: Array(n).fill(0) };
    this._noise = null;
    const tick = () => {
      if (!this._rec) return;
      if (Date.now() >= this._rec.until) {
        this._noise = { move: this._rec.move, still: this._rec.still };
        this._rec = null;
        clearInterval(this._recTimer);
        this._render();
        return;
      }
      // Only touch the button so a drag in the chart is not interrupted.
      const btn = this.shadowRoot.getElementById("record");
      if (btn) {
        btn.textContent = fmt(this._t.recording, {
          s: Math.max(0, Math.ceil((this._rec.until - Date.now()) / 1000)),
        });
      }
    };
    clearInterval(this._recTimer);
    this._recTimer = setInterval(tick, 1000);
    this._render();
  }

  _applyNoise() {
    if (!this._noise) return;
    const m = Number(this._margin) || 0;
    this._edit((d) => {
      d.motion = this._noise.move.map((v) => Math.min(100, Math.round(v + m)));
      d.motionless = this._noise.still.map((v) => Math.min(100, Math.round(v + m)));
    });
    this._render();
  }

  // -------------------------------------------------------------- render

  _render() {
    if (!this._t || !this._config) return;
    const t = this._t;
    const root = this.shadowRoot;
    if (!this._config.entry_id) {
      root.innerHTML = `<style>${CSS}</style><ha-card><div class="notice">${t.no_entry}</div></ha-card>`;
      this._built = false;
      return;
    }
    const s = this._state;
    const live = this._live || {};
    const c = this._cfg();
    const eng = s && s.engineering_mode;
    const connected = s && s.connected;
    const busy = !!this._busy || !connected;
    const admin = this._isAdmin();
    const title = this._config.title || (s && s.title) || this._title || "HLK-2412";
    const n = this._gates();

    // The radar stores min_gate as the first gate index but max_gate as a
    // gate count (14 = up to gate 13); options show gate index + distance.
    const gs = this._gateSize();
    const opts = (values, sel, label) =>
      values.map((g) => `<option value="${g}" ${g === sel ? "selected" : ""}>${label(g)}</option>`).join("");
    const minOpts = opts(Array.from({ length: n }, (_, g) => g), c.min_gate,
      (g) => `${g} (${t.from} ${+(g * gs).toFixed(2)} m)`);
    const maxOpts = opts(Array.from({ length: n }, (_, k) => k + 1), c.max_gate,
      (g) => `${g - 1} (${t.to} ${+(g * gs).toFixed(2)} m)`);

    root.innerHTML = `
      <style>${CSS}
        :host { --hlk-move: var(--hlk2412-move-color, #2196f3); --hlk-still: var(--hlk2412-still-color, #ff9800);
                --hlk-thr: var(--hlk2412-threshold-color, #e91e63); }
      </style>
      <ha-card style="container-type: inline-size">
        <div class="head">
          <span class="title">${esc(title)}</span>
          ${s && s.firmware_version ? `<span class="chip">${s.firmware_version}</span>` : ""}
          ${connected && s.connection_path ? this._pathChip(s.connection_path) : ""}
          <span class="chip">${eng ? t.engineering : t.basic}</span>
          <span class="chip ${connected ? "ok" : "bad"}">${connected ? t.connected : t.disconnected}</span>
        </div>
        ${this._error ? `<div class="notice">${esc(this._error)}</div>` : ""}
        <div class="presence" id="presence">${this._presenceHtml(live)}</div>
        ${
          eng
            ? `<div class="charts">
                 <div class="chart"><h4>${t.move_chart}</h4><svg id="move" viewBox="0 0 ${W} ${H}" class="${admin ? "edit" : ""}"></svg></div>
                 <div class="chart"><h4>${t.still_chart}</h4><svg id="still" viewBox="0 0 ${W} ${H}" class="${admin ? "edit" : ""}"></svg></div>
               </div>
               ${admin ? `<div class="hint">${t.hint}</div>` : ""}`
            : `<div class="notice">${t.eng_off}</div>`
        }
        ${
          admin
            ? `
        <div class="row">
          <label>${t.min_gate}<select id="min_gate" ${busy ? "disabled" : ""}>${minOpts}</select></label>
          <label>${t.max_gate}<select id="max_gate" ${busy ? "disabled" : ""}>${maxOpts}</select></label>
          <label>${t.unmanned}<input id="unmanned" type="number" min="0" max="65535" value="${c.unmanned_duration}" ${busy ? "disabled" : ""}></label>
          <label>${t.polarity}<select id="polarity" ${busy ? "disabled" : ""}>
            <option value="0" ${c.out_pin_polarity === 0 ? "selected" : ""}>${t.pol_high}</option>
            <option value="1" ${c.out_pin_polarity === 1 ? "selected" : ""}>${t.pol_low}</option>
          </select></label>
        </div>
        ${
          eng
            ? `<div class="row">
                 <button id="peaks">${t.reset_peaks}</button>
                 <button id="record" ${this._rec ? "disabled" : ""}>${
                   this._rec ? fmt(t.recording, { s: Math.max(0, Math.ceil((this._rec.until - Date.now()) / 1000)) }) : t.record
                 }</button>
                 ${
                   this._noise
                     ? `<label>${t.margin}<input id="margin" type="number" min="0" max="100" value="${this._margin}"></label>
                        <button id="suggest">${fmt(t.suggest, { m: this._margin })}</button>`
                     : ""
                 }
               </div>`
            : ""
        }
        <div class="row">
          <button id="eng" ${busy ? "disabled" : ""}>${eng ? t.eng_off_btn : t.eng_on_btn}</button>
          <button id="calib" ${busy || (s && s.calibration_active) ? "disabled" : ""}>${
            s && s.calibration_active ? t.calibrating : t.calibrate
          }</button>
          <span class="spacer"></span>
          ${this._draft ? `<span class="dirty">${t.dirty}</span>` : ""}
          <button id="reload" ${busy ? "disabled" : ""}>${t.reload}</button>
          <button id="discard" ${this._draft ? "" : "disabled"}>${t.discard}</button>
          <button id="save" class="primary" ${busy || !this._draft ? "disabled" : ""}>${
            this._busy === "save" ? "…" : t.save
          }</button>
        </div>`
            : ""
        }
      </ha-card>`;
    this._built = true;
    this._bind();
    this._updateLive();
  }

  _pathChip(path) {
    const rssi = path.rssi;
    const cls = rssi == null ? "" : rssi >= -75 ? "ok" : rssi < -88 ? "bad" : "warn";
    return `<span class="chip ${cls}" title="${esc(path.source)}">${this._t.via} ${esc(path.name)}${
      rssi == null ? "" : ` · ${rssi} dBm`
    }</span>`;
  }

  _gateSize() {
    return (this._state && this._state.gate_size) || 0.75;
  }

  _presenceHtml(live) {
    const t = this._t;
    if (!this._state || !this._state.connected || !this._live) return `<span class="muted">—</span>`;
    const cm = (v) => (v == null ? "—" : `${(v / 100).toFixed(2)} m`);
    const parts = [
      `<span class="${live.moving ? "on move" : ""}"><span class="dot"></span>${t.moving} ${
        live.moving ? `${cm(live.move_distance_cm)} · ${live.move_energy}` : ""
      }</span>`,
      `<span class="${live.stationary ? "on still" : ""}"><span class="dot"></span>${t.still} ${
        live.stationary ? `${cm(live.still_distance_cm)} · ${live.still_energy}` : ""
      }</span>`,
    ];
    if (!live.occupancy) parts.push(`<span class="muted">${t.nobody}</span>`);
    if (live.light_level != null) parts.push(`<span class="muted">${t.light} ${live.light_level}</span>`);
    return parts.join("");
  }

  _bind() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    const on = (id, ev, fn) => {
      const el = $(id);
      if (el) el.addEventListener(ev, fn);
    };
    on("min_gate", "change", (e) => {
      this._edit((d) => {
        d.min_gate = Number(e.target.value);
        if (d.max_gate <= d.min_gate) d.max_gate = d.min_gate + 1;
      });
      this._render();
    });
    on("max_gate", "change", (e) => {
      this._edit((d) => {
        d.max_gate = Number(e.target.value);
        if (d.min_gate >= d.max_gate) d.min_gate = d.max_gate - 1;
      });
      this._render();
    });
    on("unmanned", "change", (e) => {
      const v = Math.max(0, Math.min(65535, Math.round(Number(e.target.value) || 0)));
      this._edit((d) => (d.unmanned_duration = v));
      this._render();
    });
    on("polarity", "change", (e) => {
      this._edit((d) => (d.out_pin_polarity = Number(e.target.value)));
      this._render();
    });
    on("margin", "change", (e) => {
      this._margin = Math.max(0, Math.min(100, Number(e.target.value) || 0));
      this._render();
    });
    on("peaks", "click", () => {
      this._peaks = null;
      this._updateLive();
    });
    on("record", "click", () => this._startRecording());
    on("suggest", "click", () => this._applyNoise());
    on("eng", "click", () =>
      this._call("hlk2412/engineering", { enable: !(this._state && this._state.engineering_mode) })
    );
    on("calib", "click", () => this._call("hlk2412/calibrate"));
    on("reload", "click", async () => {
      if (await this._call("hlk2412/reload_config")) this._draft = null;
      this._render();
    });
    on("discard", "click", () => {
      this._draft = null;
      this._render();
    });
    on("save", "click", () => this._save());
    if (this._isAdmin()) {
      for (const id of ["move", "still"]) {
        const svg = $(id);
        if (svg) this._bindDrag(svg, id === "move" ? "motion" : "motionless");
      }
    }
  }

  _bindDrag(svg, key) {
    const n = this._gates();
    const cw = (W - M.l - M.r) / n;
    const point = (ev) => {
      const r = svg.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / r.width) * W;
      const y = ((ev.clientY - r.top) / r.height) * H;
      const gate = Math.max(0, Math.min(n - 1, Math.floor((x - M.l) / cw)));
      const value = Math.max(0, Math.min(100, Math.round(((H - M.b - y) / (H - M.b - M.t)) * 100)));
      return { gate, value };
    };
    const apply = (ev) => {
      const { gate, value } = point(ev);
      // While dragging horizontally, fill every gate passed over.
      const from = this._drag && this._drag.gate != null ? this._drag.gate : gate;
      const [a, b] = from < gate ? [from, gate] : [gate, from];
      this._edit((d) => {
        for (let g = a; g <= b; g++) d[key][g] = value;
      });
      this._drag = { key, gate };
      this._updateLive();
    };
    svg.addEventListener("pointerdown", (ev) => {
      if (!this._state || !this._state.connected) return;
      svg.setPointerCapture(ev.pointerId);
      this._drag = { key, gate: null };
      apply(ev);
    });
    svg.addEventListener("pointermove", (ev) => {
      if (this._drag && this._drag.key === key) apply(ev);
    });
    const end = () => {
      if (!this._drag) return;
      this._drag = null;
      this._render(); // show "unsaved" state
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
  }

  _updateLive() {
    const root = this.shadowRoot;
    const presence = root.getElementById("presence");
    if (presence) presence.innerHTML = this._presenceHtml(this._live || {});
    const c = this._cfg();
    const live = this._live || {};
    const move = root.getElementById("move");
    if (move) {
      move.innerHTML = this._chart(
        "move_gate_",
        c.motion,
        this._peaks && this._peaks.move,
        this._noise && this._noise.move,
        live.moving ? live.move_distance_cm : null,
        "var(--hlk-move)",
        c
      );
    }
    const still = root.getElementById("still");
    if (still) {
      still.innerHTML = this._chart(
        "static_gate_",
        c.motionless,
        this._peaks && this._peaks.still,
        this._noise && this._noise.still,
        live.stationary ? live.still_distance_cm : null,
        "var(--hlk-still)",
        c
      );
    }
  }

  _chart(prefix, thresholds, peaks, noise, targetCm, color, c) {
    const n = this._gates();
    const live = this._live || {};
    const cw = (W - M.l - M.r) / n;
    const ph = H - M.t - M.b;
    const y = (v) => M.t + ph - (Math.max(0, Math.min(100, v)) / 100) * ph;
    const gs = this._gateSize();
    const out = [];
    // grid
    for (const v of [0, 25, 50, 75, 100]) {
      out.push(
        `<line x1="${M.l}" x2="${W - M.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--divider-color)" stroke-width="1"/>`,
        `<text x="${M.l - 4}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="var(--secondary-text-color)">${v}</text>`
      );
    }
    for (let i = 0; i < n; i++) {
      const x = M.l + i * cw;
      const inRange = i >= c.min_gate && i < c.max_gate;
      if (!inRange) {
        out.push(`<rect x="${x}" y="${M.t}" width="${cw}" height="${ph}" fill="var(--secondary-text-color)" opacity=".12"/>`);
      }
      const e = live[`${prefix}${i}_energy`];
      const thr = thresholds[i];
      if (e != null) {
        const over = inRange && e >= thr;
        out.push(
          `<rect x="${x + cw * 0.18}" y="${y(e)}" width="${cw * 0.64}" height="${y(0) - y(e)}" rx="2"
             fill="${color}" opacity="${over ? 1 : 0.45}"/>`
        );
      }
      if (noise) {
        out.push(`<rect x="${x + 2}" y="${y(noise[i])}" width="${cw - 4}" height="${y(0) - y(noise[i])}"
                   fill="none" stroke="var(--secondary-text-color)" stroke-dasharray="3 2" stroke-width="1"/>`);
      }
      if (peaks) {
        out.push(`<line x1="${x + cw * 0.12}" x2="${x + cw * 0.88}" y1="${y(peaks[i])}" y2="${y(peaks[i])}"
                   stroke="${color}" stroke-width="2"/>`);
      }
      out.push(
        `<line x1="${x + 2}" x2="${x + cw - 2}" y1="${y(thr)}" y2="${y(thr)}" stroke="var(--hlk-thr)" stroke-width="3" stroke-linecap="round"/>`,
        `<text x="${x + cw / 2}" y="${Math.max(M.t + 8, y(thr) - 4)}" font-size="10" text-anchor="middle" fill="var(--hlk-thr)">${thr}</text>`,
        `<text x="${x + cw / 2}" y="${H - M.b + 13}" font-size="11" text-anchor="middle" fill="var(--primary-text-color)">${i}</text>`,
        `<text x="${x + cw / 2}" y="${H - M.b + 26}" font-size="9" text-anchor="middle" fill="var(--secondary-text-color)">${+(i * gs).toFixed(2)}</text>`
      );
    }
    if (targetCm != null) {
      const tx = M.l + Math.min(n, targetCm / 100 / gs) * cw;
      out.push(`<line x1="${tx}" x2="${tx}" y1="${M.t}" y2="${y(0)}" stroke="var(--primary-text-color)" stroke-dasharray="4 3" stroke-width="1.5"/>`);
    }
    return out.join("");
  }
}

class Hlk2412CardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      hass
        .callWS({ type: "hlk2412/devices" })
        .then((devices) => {
          this._devices = devices;
          this._render();
        })
        .catch(() => {});
    }
  }

  _render() {
    if (!this._config) return;
    const devices = this._devices || [];
    this.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px">
        <label style="display:flex;flex-direction:column;gap:4px">Radar
          <select id="entry" style="font:inherit;padding:6px">
            <option value="">—</option>
            ${devices
              .map(
                (d) =>
                  `<option value="${d.entry_id}" ${d.entry_id === this._config.entry_id ? "selected" : ""}>${esc(d.title)}</option>`
              )
              .join("")}
          </select>
        </label>
        <label style="display:flex;flex-direction:column;gap:4px">Title
          <input id="title" style="font:inherit;padding:6px" value="${esc(this._config.title || "")}">
        </label>
      </div>`;
    this.querySelector("#entry").addEventListener("change", (e) => this._set("entry_id", e.target.value));
    this.querySelector("#title").addEventListener("change", (e) => this._set("title", e.target.value || undefined));
  }

  _set(key, value) {
    const config = { ...this._config, [key]: value };
    if (value === undefined) delete config[key];
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

customElements.define("hlk2412-card", Hlk2412Card);
customElements.define("hlk2412-card-editor", Hlk2412CardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hlk2412-card",
  name: "HLK-LD2412 radar",
  description: "Live per-gate energies and threshold editor for HLK-LD2412 radars.",
  preview: false,
});
console.info(`%c HLK2412-CARD %c ${VERSION} `, "color:#fff;background:#e91e63", "");
