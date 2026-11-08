/* Graphiques des coûts : répartition par catégorie (barres empilées), évolution mensuelle, budget / réel cumulés. */
(function () {
  "use strict";
  if (!window.Chart) return;
  var COLORS = ["#1F5FBF", "#F79009", "#7A5AF8", "#98A2B3"];
  var money = function (v) { return Number(v).toLocaleString(window.EM_LOCALE || "fr-FR", { maximumFractionDigits: 0 }); };
  function data(id) { var el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; }
  var base = { maintainAspectRatio: false, animation: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } } };

  document.querySelectorAll("canvas[data-costs]").forEach(function (canvas) {
    var s = data(canvas.dataset.costs); if (!s) return;
    var horizontal = canvas.dataset.type === "hbar";
    new Chart(canvas, {
      type: "bar",
      data: { labels: s.labels, datasets: s.series.map(function (serie, i) { return { label: serie.label, data: serie.values, backgroundColor: COLORS[i] }; }) },
      options: Object.assign({}, base, {
        indexAxis: horizontal ? "y" : "x",
        scales: { x: { stacked: true, ticks: { callback: horizontal ? function (v) { return money(v); } : undefined } },
                  y: { stacked: true, ticks: { callback: horizontal ? undefined : function (v) { return money(v); } } } }
      })
    });
  });

  document.querySelectorAll("canvas[data-trend]").forEach(function (canvas) {
    var s = data(canvas.dataset.trend); if (!s) return;
    new Chart(canvas, {
      type: "bar",
      data: { labels: s.labels, datasets: [
        { label: String(s.year), data: s.current, backgroundColor: "#1F5FBF" },
        { label: String(s.year - 1), data: s.previous, backgroundColor: "#D0D5DD" }
      ] },
      options: Object.assign({}, base, { scales: { y: { ticks: { callback: money } } } })
    });
  });

  document.querySelectorAll("canvas[data-budget]").forEach(function (canvas) {
    var s = data(canvas.dataset.budget); if (!s) return;
    var cumul = function (values) { var t = 0; return values.map(function (v) { t += v; return t; }); };
    new Chart(canvas, {
      type: "line",
      data: { labels: s.labels, datasets: [
        { label: EM_T("Budget cumulé"), data: cumul(s.planned), borderColor: "#98A2B3", borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
        { label: EM_T("Réel cumulé"), data: cumul(s.actual), borderColor: "#1F5FBF", backgroundColor: "#1F5FBF", pointRadius: 3, borderWidth: 2 }
      ] },
      options: Object.assign({}, base, { scales: { y: { ticks: { callback: money } } } })
    });
  });
})();
