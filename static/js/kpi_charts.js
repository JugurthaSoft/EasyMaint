/* Graphiques des indicateurs : données dans les <script type="application/json"> kpi-trend, kpi-split, kpi-units. */
(function () {
  "use strict";
  if (!window.Chart) return;
  function data(id) { var el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; }
  var trend = data("kpi-trend"), split = data("kpi-split"), units = data("kpi-units");
  var base = { maintainAspectRatio: false, animation: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } } };
  var PALETTE = ["#D92D20", "#1F5FBF", "#7A5AF8", "#17B26A", "#F79009", "#98A2B3"];
  function canvas(name) { return document.querySelector('canvas[data-kpi="' + name + '"]'); }

  if (trend && canvas("failures")) {
    new Chart(canvas("failures"), {
      data: { labels: trend.labels, datasets: [
        { type: "bar", label: EM_T("Pannes"), data: trend.failures, backgroundColor: "#F97066", yAxisID: "y" },
        { type: "line", label: EM_T("Disponibilité (%)"), data: trend.availability, borderColor: "#17B26A", backgroundColor: "#17B26A", yAxisID: "y1", spanGaps: true }
      ] },
      options: Object.assign({}, base, { scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, y1: { position: "right", suggestedMin: 80, max: 100, grid: { display: false } } } })
    });
  }
  if (trend && canvas("mtbf")) {
    new Chart(canvas("mtbf"), {
      type: "line",
      data: { labels: trend.labels, datasets: [
        { label: "MTBF (h)", data: trend.mtbf, borderColor: "#1F5FBF", backgroundColor: "#1F5FBF", yAxisID: "y", spanGaps: true },
        { label: "MTTR (h)", data: trend.mttr, borderColor: "#F79009", backgroundColor: "#F79009", yAxisID: "y1", spanGaps: true }
      ] },
      options: Object.assign({}, base, { scales: { y: { beginAtZero: true }, y1: { position: "right", beginAtZero: true, grid: { display: false } } } })
    });
  }
  if (trend && canvas("cost")) {
    new Chart(canvas("cost"), {
      type: "bar", data: { labels: trend.labels, datasets: [{ label: EM_T("Coût"), data: trend.cost, backgroundColor: "#1F5FBF" }] },
      options: Object.assign({}, base, { plugins: { legend: { display: false } } })
    });
  }
  if (split && split.values.length && canvas("split")) {
    new Chart(canvas("split"), { type: "doughnut", data: { labels: split.labels, datasets: [{ data: split.values, backgroundColor: PALETTE }] }, options: base });
  }
  if (units && units.values.length && canvas("units")) {
    new Chart(canvas("units"), {
      type: "bar", data: { labels: units.labels, datasets: [{ label: EM_T("OT clos"), data: units.values, backgroundColor: "#1F5FBF" }] },
      options: Object.assign({}, base, { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { ticks: { precision: 0 } } } })
    });
  }
})();
