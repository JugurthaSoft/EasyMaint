/* Graphiques de l'accueil (blocs « Équipements par unité » et « Pannes et disponibilité · 12 mois »). */
(function () {
  "use strict";
  if (!window.Chart) return;
  function data(id) { var el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; }
  var legend = { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } };
  var workshops = data("dash-workshops"), canvas = document.querySelector('canvas[data-dash="workshops"]');
  if (workshops && canvas) {
    new Chart(canvas, {
      type: "bar",
      data: { labels: workshops.labels, datasets: [
        { label: EM_T("En service"), data: workshops.in_service, backgroundColor: "#1F5FBF", borderRadius: 3 },
        { label: EM_T("Arrêtés"), data: workshops.stopped, backgroundColor: "#98A2B3", borderRadius: 3 },
        { label: EM_T("En panne"), data: workshops.broken, backgroundColor: "#D92D20", borderRadius: 3 }
      ] },
      options: { indexAxis: "y", maintainAspectRatio: false,
        scales: { x: { stacked: true, ticks: { precision: 0 }, grid: { color: "#F2F4F7" } }, y: { stacked: true, grid: { display: false } } },
        plugins: { legend: legend } }
    });
  }
  var trend = data("dash-trend"), trendCanvas = document.querySelector('canvas[data-dash="trend"]');
  if (trend && trendCanvas) {
    new Chart(trendCanvas, {
      data: { labels: trend.labels, datasets: [
        { type: "bar", label: EM_T("Pannes"), data: trend.failures, backgroundColor: "#F97066", yAxisID: "y" },
        { type: "line", label: EM_T("Disponibilité (%)"), data: trend.availability, borderColor: "#17B26A", backgroundColor: "#17B26A", yAxisID: "y1", spanGaps: true }
      ] },
      options: { maintainAspectRatio: false, animation: false, plugins: { legend: legend },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, y1: { position: "right", suggestedMin: 80, max: 100, grid: { display: false } } } }
    });
  }
})();
