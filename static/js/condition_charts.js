/* Courbes d'évolution du conditionnel : <canvas data-series="id-du-json"> + {{ series|json_script:"id-du-json" }}.
   La mesure est tracée en bleu, chaque point coloré selon son niveau ; les seuils en pointillé. */
(function () {
  "use strict";
  if (!window.Chart) return;
  var LEVEL_COLORS = { normal: "#17B26A", warning: "#F79009", alarm: "#D92D20", critical: "#912018", unknown: "#98A2B3" };
  var THRESHOLDS = [
    ["warning_high", EM_T("Attention"), "#F79009"], ["alarm_high", EM_T("Alarme"), "#D92D20"], ["critical_high", EM_T("Critique"), "#912018"],
    ["warning_low", EM_T("Attention (bas)"), "#F79009"], ["alarm_low", EM_T("Alarme (bas)"), "#D92D20"], ["critical_low", EM_T("Critique (bas)"), "#912018"]
  ];
  document.querySelectorAll("canvas[data-series]").forEach(function (canvas) {
    var source = document.getElementById(canvas.dataset.series);
    if (!source) return;
    var s = JSON.parse(source.textContent);
    if (!s.values.length) return;
    var datasets = [{
      label: EM_T("Mesure") + (s.unit ? " (" + s.unit + ")" : ""), data: s.values, borderColor: "#1F5FBF", backgroundColor: "#1F5FBF",
      pointBackgroundColor: s.levels.map(function (l) { return LEVEL_COLORS[l] || "#1F5FBF"; }),
      pointBorderColor: s.levels.map(function (l) { return LEVEL_COLORS[l] || "#1F5FBF"; }),
      pointRadius: 4, tension: 0.2, borderWidth: 2
    }];
    THRESHOLDS.forEach(function (t) {
      if (s[t[0]] && s[t[0]].length) {
        datasets.push({ label: t[1], data: s[t[0]], borderColor: t[2], borderDash: [6, 4], borderWidth: 1.5,
          pointRadius: 0, stepped: true, fill: false, spanGaps: true });
      }
    });
    new Chart(canvas, {
      type: "line",
      data: { labels: s.labels, datasets: datasets },
      options: {
        maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { grid: { color: "#F2F4F7" } } },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } } }
      }
    });
  });
})();
