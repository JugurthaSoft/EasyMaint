/* Historique des prix d'achat : <canvas data-prices="id-du-json"> + {{ series|json_script:"id-du-json" }}. */
(function () {
  "use strict";
  if (!window.Chart) return;
  document.querySelectorAll("canvas[data-prices]").forEach(function (canvas) {
    var source = document.getElementById(canvas.dataset.prices);
    if (!source) return;
    var s = JSON.parse(source.textContent);
    if (!s.values.length) return;
    new Chart(canvas, {
      type: "line",
      data: { labels: s.labels, datasets: [{ label: EM_T("Prix unitaire HT"), data: s.values, borderColor: "#1F5FBF",
        backgroundColor: "#1F5FBF", pointRadius: 4, stepped: true, borderWidth: 2 }] },
      options: {
        maintainAspectRatio: false, animation: false,
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } }, y: { grid: { color: "#F2F4F7" } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: function (ctx) { return s.suppliers[ctx.dataIndex]; } } } }
      }
    });
  });
})();
