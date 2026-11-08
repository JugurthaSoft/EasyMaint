/* Personnalisation de l'accueil : flèches pour monter / descendre un bloc (l'ordre envoyé suit celui de la liste). */
(function () {
  "use strict";
  var list = document.getElementById("block-list");
  if (!list) return;
  list.addEventListener("click", function (event) {
    var button = event.target.closest("[data-move]");
    if (!button) return;
    var row = button.closest("[data-row]");
    if (button.dataset.move === "up" && row.previousElementSibling) {
      list.insertBefore(row, row.previousElementSibling);
    } else if (button.dataset.move === "down" && row.nextElementSibling) {
      list.insertBefore(row.nextElementSibling, row);
    }
    button.focus();
  });
})();
