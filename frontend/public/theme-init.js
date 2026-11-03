// Applies a saved Light/Dark choice before the page paints, so a reload
// doesn't flash the other theme. Loaded as a same-origin file from <head>
// (script-src 'self'), not as an inline script. "System" (or blocked
// storage) leaves the attribute off and app/globals.css follows the OS.
// Key and values must match lib/theme.ts.
(function () {
  try {
    var choice = window.localStorage.getItem("consultrag-theme");
    if (choice === "light" || choice === "dark") {
      document.documentElement.setAttribute("data-theme", choice);
    }
  } catch (e) {
    // Storage blocked: follow the system theme.
  }
})();
