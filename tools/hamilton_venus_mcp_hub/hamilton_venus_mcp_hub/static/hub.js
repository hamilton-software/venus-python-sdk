/* Shared helpers for the hub's dashboard pages (fleet overview + per-instrument detail).
   Plain script, no bundler -- loaded with a plain <script src="/static/hub.js"> tag. */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function relativeTime(epochSeconds) {
  if (epochSeconds === null || epochSeconds === undefined) return "never";
  const deltaS = Math.max(0, (Date.now() / 1000) - epochSeconds);
  if (deltaS < 2) return "just now";
  if (deltaS < 60) return Math.floor(deltaS) + "s ago";
  if (deltaS < 3600) return Math.floor(deltaS / 60) + "m ago";
  return Math.floor(deltaS / 3600) + "h ago";
}

function clockTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString();
}

// ISO timestamps from the spoke are UTC ("...+00:00"); show them in the viewer's local time.
function formatLocalDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", second: "2-digit",
  });
}

// The spoke reports volumes in uL. A reservoir holds tens of mL, where "33336.7125" is hard to read:
// show mL (one decimal) from 1 mL up, and uL below that, so a 250 uL aspirate still reads "250 µL".
function formatVolumeUl(ul) {
  if (ul === null || ul === undefined || ul === "" || Number.isNaN(Number(ul))) return "—";
  const v = Number(ul);
  if (Math.abs(v) >= 1000) return (Math.round(v / 100) / 10).toFixed(1) + " mL";
  return (Math.round(v * 10) / 10) + " µL";
}

// Consumable levels: reagents are volumes (uL), everything else (tips, plates...) is a plain count.
function formatConsumableLevel(row) {
  const isVolume = row.kind === "reagent";
  const fmt = v => isVolume ? formatVolumeUl(v) : Math.round(v * 100) / 100;
  const level = row.level !== null && row.level !== undefined ? fmt(row.level) : "—";
  const capacity = row.capacity ? " / " + (isVolume ? formatVolumeUl(row.capacity) : Math.round(row.capacity)) : "";
  return level + capacity;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
  return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
}

// -- dark mode -----------------------------------------------------------------------------

function restoreTheme() {
  let saved = "light";
  try { saved = localStorage.getItem("theme") || "light"; } catch (e) { /* storage unavailable */ }
  document.documentElement.setAttribute("data-theme", saved);
  updateDarkModeIcon(saved);
}

function toggleDarkMode() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("theme", next); } catch (e) { /* storage unavailable */ }
  updateDarkModeIcon(next);
}

// Simple, self-contained icons (explicit width/height/viewBox on the <svg> itself, not
// relying on external CSS to size them) -- a small 24x24 viewBox with plain primitives
// (circle/line/path) rather than hand-derived path data on a large viewBox, which is what
// produced the clipped/tiny-dot rendering these replaced (a mismatched/miscalculated path
// on a 640x640 viewBox, effectively invisible at icon size).
const ICON_SUN =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<circle cx="12" cy="12" r="4"/>' +
  '<line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/>' +
  '<line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/>' +
  '<line x1="4.6" y1="4.6" x2="6" y2="6"/><line x1="18" y1="18" x2="19.4" y2="19.4"/>' +
  '<line x1="4.6" y1="19.4" x2="6" y2="18"/><line x1="18" y1="6" x2="19.4" y2="4.6"/>' +
  "</svg>";
const ICON_MOON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">' +
  '<path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 ' +
  '5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/></svg>';

function updateDarkModeIcon(theme) {
  const btn = document.getElementById("dark-mode-btn");
  if (!btn) return;
  // Dark mode active -> show the sun (click to switch back to light), and vice versa.
  btn.innerHTML = theme === "dark" ? ICON_SUN : ICON_MOON;
  btn.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
}

// -- sidebar ---------------------------------------------------------------------------------

const NAV_STATE_DOT = { idle: "idle", running: "running", error: "error", unreachable: "unreachable", unknown: "unknown" };

const ICON_HOME = '<svg viewBox="0 0 640 640"><path opacity=".4" d="M96 334.5c25.6-22.4 51.2-44.7 76.7-67.1 49.1-42.9 98.2-85.9 147.3-128.9 74.7 65.4 149.4 130.7 224.1 196.1l.4 201.3c0 22.1-17.9 40.1-40 40.1H424c-22.1 0-40-17.9-40-40v-88.3c0-17.7-14.3-32-32-32h-64c-17.7 0-32 14.3-32 32V536c0 22.1-17.9 40-40 40h-79.9c-22.1 0-40-17.9-40-40z"/><path d="M298.9 71.9c12.1-10.5 30.1-10.5 42.2 0l256 224c13.3 11.6 14.6 31.9 3 45.2s-31.9 14.6-45.2 3L320 138.5 85.1 344.1c-13.3 11.6-33.5 10.3-45.2-3s-10.3-33.5 3-45.2z"/></svg>';
const ICON_INSTRUMENT = '<svg viewBox="0 0 640 640"><path opacity=".4" d="M576 320c0 141.4-114.6 256-256 256S64 461.4 64 320 178.6 64 320 64s256 114.6 256 256m-448 0c0 17.7 14.3 32 32 32s32-14.3 32-32-14.3-32-32-32-32 14.3-32 32m48-112c0 17.7 14.3 32 32 32s32-14.3 32-32-14.3-32-32-32-32 14.3-32 32m80 208c0 35.3 28.7 64 64 64s64-28.7 64-64c0-1.7-.1-3.3-.2-5-.1-.7-.1-1.5-.2-2.1 0-.2 0-.5-.1-.6-.1-.6-.2-1.2-.2-1.8-3.2-21.2-16.6-39-35.2-48-1.3-.7-2.7-1.3-4.1-1.8V152c0-13.3-10.7-24-24-24s-24 10.7-24 24v204.7c-1.5.6-2.9 1.2-4.3 1.9-18.4 9-31.7 26.6-34.9 47.5-.2 1.6-.4 3.2-.6 4.9-.1 1.7-.2 3.3-.2 5m144-208c0 17.7 14.3 32 32 32s32-14.3 32-32-14.3-32-32-32-32 14.3-32 32m48 112c0 17.7 14.3 32 32 32s32-14.3 32-32-14.3-32-32-32-32 14.3-32 32"/><path d="M344 152c0-13.3-10.7-24-24-24s-24 10.7-24 24v204.7c-23.5 9.5-40 32.5-40 59.3 0 35.3 28.7 64 64 64s64-28.7 64-64c0-26.9-16.5-49.9-40-59.3z"/></svg>';

function renderSidebar(spokes, activeSpokeId) {
  const nav = document.getElementById("sidebar-nav");
  if (!nav) return;
  const items = [];
  items.push(`<a class="nav-item${!activeSpokeId ? " active" : ""}" href="/dashboard">
      <span class="nav-icon">${ICON_HOME}</span><span>Fleet overview</span></a>`);
  items.push('<div class="nav-section-label">Instruments</div>');
  for (const s of spokes) {
    const dotClass = NAV_STATE_DOT[s.state] || "unknown";
    items.push(`<a class="nav-item${s.id === activeSpokeId ? " active" : ""}" href="/spokes/${encodeURIComponent(s.id)}">
        <span class="nav-icon">${ICON_INSTRUMENT}</span><span class="nav-label"><span>${esc(s.id)}</span>${s.instrument_type ? `<span class="nav-type">${esc(s.instrument_type)}</span>` : ""}</span>
        <span class="nav-state-dot ${dotClass}" title="${esc(s.state)}"></span></a>`);
  }
  nav.innerHTML = items.join("");
}

document.addEventListener("DOMContentLoaded", restoreTheme);
