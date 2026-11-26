// « Mes candidatures » : recharge la fenêtre toute seule quand elle est restée blanche ou
// déconnectée (redémarrage du serveur après une mise à jour, PC sorti de veille...).
// Injecté une fois dans la page par app/dashboard.py (st.html, unsafe_allow_javascript).
(function () {
  if (window.__mesCandidaturesWatchdog) return;
  window.__mesCandidaturesWatchdog = true;

  var EVERY_MS = 3000;          // une vérification toutes les 3 s (fenêtre visible seulement)
  var BLANK_MS = 12000;         // page vide ou « déconnectée » pendant 12 s -> rechargement
  var MIN_GAP_MS = 20000;       // jamais deux rechargements à moins de 20 s
  var MAX_PER_5MIN = 3;         // et pas plus de 3 en 5 minutes (évite une boucle)
  var KEY = "mesCandidaturesReloads";

  var serverWasDown = false;
  var badSince = null;

  function recentReloads() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "[]").filter(function (t) { return Date.now() - t < 300000; }); }
    catch (e) { return []; }
  }

  function reload(why) {
    var done = recentReloads();
    if (done.length >= MAX_PER_5MIN || (done.length && Date.now() - done[done.length - 1] < MIN_GAP_MS)) return;
    done.push(Date.now());
    try { sessionStorage.setItem(KEY, JSON.stringify(done)); } catch (e) {}
    console.log("[Mes candidatures] rechargement de la fenêtre : " + why);
    window.location.reload();
  }

  function serverUp() {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 4000);
    return fetch("/_stcore/health", { cache: "no-store", signal: ctrl.signal })
      .then(function (r) { clearTimeout(timer); return r.ok; })
      .catch(function () { clearTimeout(timer); return false; });
  }

  function pageLooksBroken() {
    var text = document.body ? document.body.innerText || "" : "";
    if (/Connection error|Is Streamlit still running|Connection timed out|Erreur de connexion/i.test(text)) return true;
    var main = document.querySelector('[data-testid="stMainBlockContainer"]');
    if (!main) return false;                       // structure inconnue : ne rien faire
    return (main.innerText || "").trim().length < 3;
  }

  setInterval(function () {
    if (document.hidden) { badSince = null; return; }
    serverUp().then(function (up) {
      if (!up) { serverWasDown = true; badSince = null; return; }
      if (serverWasDown) {                          // le serveur vient de redémarrer
        serverWasDown = false;
        setTimeout(function () { reload("serveur redémarré"); }, 1500);
        return;
      }
      if (pageLooksBroken()) {
        badSince = badSince || Date.now();
        if (Date.now() - badSince > BLANK_MS) reload("page vide ou déconnectée");
      } else {
        badSince = null;
      }
    });
  }, EVERY_MS);
})();
