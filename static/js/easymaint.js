/* EasyMaint — comportements communs (aucune dépendance en dehors de Bootstrap et HTMX). */

/* Textes des graphiques : traduits selon la langue de la page (<html lang>). */
(function () {
  var EN = {
    "Mesure": "Measurement", "Attention": "Warning", "Alarme": "Alarm", "Critique": "Critical",
    "Attention (bas)": "Warning (low)", "Alarme (bas)": "Alarm (low)", "Critique (bas)": "Critical (low)",
    "En service": "In service", "Arrêtés": "Stopped", "En panne": "Broken down", "Pannes": "Failures",
    "Disponibilité (%)": "Availability (%)", "Budget cumulé": "Cumulative budget", "Réel cumulé": "Cumulative actual",
    "Prix unitaire HT": "Unit price (excl. tax)", "Coût": "Cost", "OT clos": "Closed WOs"
  };
  var lang = (document.documentElement.lang || "fr").slice(0, 2);
  window.EM_LANG = lang;
  window.EM_LOCALE = lang === "en" ? "en-GB" : "fr-FR";
  window.EM_T = function (text) { return lang === "en" && EN[text] ? EN[text] : text; };
})();

(function () {
  "use strict";

  // Raccourci « / » : place le curseur dans la recherche globale.
  document.addEventListener("keydown", function (event) {
    var target = event.target;
    var typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
    if (event.key === "/" && !typing) {
      var input = document.getElementById("global-search-input");
      if (input) {
        event.preventDefault();
        input.focus();
        input.select();
      }
    }
    if (event.key === "Escape") {
      var dropdown = document.getElementById("search-dropdown");
      if (dropdown) dropdown.innerHTML = "";
    }
  });

  // Ferme la liste de résultats de recherche quand on clique ailleurs.
  document.addEventListener("click", function (event) {
    var box = document.querySelector(".global-search");
    var dropdown = document.getElementById("search-dropdown");
    if (box && dropdown && !box.contains(event.target)) dropdown.innerHTML = "";
  });

  // Les messages de succès disparaissent d'eux-mêmes ; les erreurs restent jusqu'à fermeture.
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".alert-success[data-autoclose]").forEach(function (alert) {
      setTimeout(function () {
        if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(alert).close();
      }, 5000);
    });
  });

  // Demande de confirmation sur les boutons sensibles : <button data-confirm="Texte">.
  document.addEventListener("submit", function (event) {
    var submitter = event.submitter;
    var message = (submitter && submitter.dataset.confirm) || event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  // Impression : <button data-print>.
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-print]");
    if (button) {
      event.preventDefault();
      window.print();
    }
  });

  // Envoi automatique du formulaire de filtre : <select data-autosubmit>.
  document.addEventListener("change", function (event) {
    var target = event.target;
    if (target.matches && target.matches("[data-autosubmit]") && target.form) target.form.submit();
    // Pastilles de filtre : l'apparence suit le bouton radio coché, sans attendre le serveur.
    if (target.matches && target.matches(".pill input[type=radio]")) {
      var scope = target.form || document;
      scope.querySelectorAll(".pill input[type=radio]").forEach(function (radio) {
        if (radio.name === target.name) radio.closest(".pill").classList.toggle("active", radio === target);
      });
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    // Plan préventif : n'affiche que les réglages utiles au mode de déclenchement choisi.
    var trigger = document.getElementById("id_trigger_mode");
    if (trigger) {
      var refresh = function () {
        document.querySelectorAll("[data-trigger]").forEach(function (box) {
          box.hidden = !(trigger.value === "both" || trigger.value === box.dataset.trigger);
        });
      };
      trigger.addEventListener("change", refresh);
      refresh();
    }

    // Chronomètre de l'intervention en cours (vue mobile du technicien).
    var timer = document.getElementById("timer");
    if (timer && timer.dataset.start) {
      var start = parseInt(timer.dataset.start, 10) * 1000;
      var pad = function (n) { return (n < 10 ? "0" : "") + n; };
      var tick = function () {
        var s = Math.max(0, Math.floor((Date.now() - start) / 1000));
        timer.textContent = pad(Math.floor(s / 3600)) + ":" + pad(Math.floor((s % 3600) / 60)) + ":" + pad(s % 60);
      };
      tick();
      setInterval(tick, 1000);
    }
  });
})();
