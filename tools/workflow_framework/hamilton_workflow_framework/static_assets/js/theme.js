const THEME_STORAGE_KEY = "hamilton-theme";

// Heroicons-style sun/moon (24x24 viewBox -- see the <svg id="dark-mode-icon">
// markup in each app's index.html, which must use viewBox="0 0 24 24" to
// match). The previous 640x640-viewBox icons had a "sun" whose rays touched
// the edge of the viewBox (clipping at this button's small render size) and
// a "moon" that was actually a circle with two eye-dots and a curved mouth --
// reading as a smiley face rather than a crescent moon.
const SUN_ICON_PATH =
  "M12 2.25a.75.75 0 0 1 .75.75v2.25a.75.75 0 0 1-1.5 0V3a.75.75 0 0 1 .75-.75ZM7.5 12a4.5 4.5 0 1 1 9 0 4.5 4.5 0 0 1-9 0ZM18.894 6.166a.75.75 0 0 0-1.06-1.06l-1.591 1.59a.75.75 0 1 0 1.06 1.061l1.591-1.59ZM21.75 12a.75.75 0 0 1-.75.75h-2.25a.75.75 0 0 1 0-1.5H21a.75.75 0 0 1 .75.75ZM17.834 18.894a.75.75 0 0 0 1.06-1.06l-1.59-1.591a.75.75 0 1 0-1.061 1.06l1.59 1.591ZM12 18a.75.75 0 0 1 .75.75V21a.75.75 0 0 1-1.5 0v-2.25A.75.75 0 0 1 12 18ZM7.758 17.303a.75.75 0 0 0-1.061-1.06l-1.591 1.59a.75.75 0 0 0 1.06 1.061l1.591-1.59ZM6 12a.75.75 0 0 1-.75.75H3a.75.75 0 0 1 0-1.5h2.25A.75.75 0 0 1 6 12ZM6.697 7.757a.75.75 0 0 0 1.06-1.06l-1.59-1.591a.75.75 0 0 0-1.061 1.06l1.59 1.591Z";
const MOON_ICON_PATH =
  "M9.528 1.718a.75.75 0 0 1 .162.819A8.97 8.97 0 0 0 9 6a9 9 0 0 0 9 9 8.97 8.97 0 0 0 3.463-.69.75.75 0 0 1 .981.98 10.503 10.503 0 0 1-9.694 6.46c-5.799 0-10.5-4.701-10.5-10.5 0-4.368 2.667-8.112 6.46-9.694a.75.75 0 0 1 .818.162Z";

function updateDarkModeIcon(theme) {
  const path = document.querySelector("#dark-mode-icon path");
  if (!path) return;
  path.setAttribute("d", theme === "dark" ? SUN_ICON_PATH : MOON_ICON_PATH);
}

function restoreTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY) || "light";
  document.documentElement.setAttribute("data-theme", saved);
  updateDarkModeIcon(saved);
}

function toggleDarkMode() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem(THEME_STORAGE_KEY, next);
  updateDarkModeIcon(next);
  // Canvas-drawn content (e.g. TADM charts) bakes theme colors into pixels at
  // draw time rather than following CSS variables, so it needs an explicit
  // repaint nudge on top of the automatic CSS cascade everything else gets.
  document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
}

document.addEventListener("DOMContentLoaded", () => {
  restoreTheme();
  const btn = document.getElementById("dark-mode-btn");
  if (btn) btn.addEventListener("click", toggleDarkMode);
});
