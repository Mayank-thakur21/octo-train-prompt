/*
 * Pre-paint theme bootstrap for Prompt Engineering Studio.
 * Reads the theme preference saved by the app (localStorage key "pes.theme",
 * JSON-encoded "dark" | "light" | "system") and toggles the `dark` class on
 * <html> before React mounts, so the page never flashes the wrong theme.
 */
(function () {
  "use strict";
  var preference = "system";
  try {
    var raw = window.localStorage.getItem("pes.theme");
    if (raw !== null) {
      var parsed = JSON.parse(raw);
      if (parsed === "dark" || parsed === "light" || parsed === "system") {
        preference = parsed;
      }
    }
  } catch {
    // Storage blocked or value corrupted: fall back to the system preference.
    preference = "system";
  }
  var dark =
    preference === "dark" ||
    (preference === "system" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  var root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
})();
