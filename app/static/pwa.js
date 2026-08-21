/* STARFACE WebApp — PWA: Service-Worker-Registrierung */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* SW nicht verfügbar (z.B. HTTP statt HTTPS) — App funktioniert trotzdem */
    });
  });
}
