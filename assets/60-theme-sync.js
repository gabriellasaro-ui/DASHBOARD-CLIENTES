/*
 * Espelha o tema do #app-root no documento inteiro.
 *
 * O tema do cliente chega como estilo inline do #app-root (o Dash troca esse
 * estilo ao navegar entre /admin e o painel de um cliente, sem recarregar).
 * Mas o <body>, as barras de rolagem e o `color-scheme` da página vivem FORA
 * dele: sem este espelho, sair do admin claro para um cliente de tema escuro
 * deixava o fundo da página e a rolagem claros.
 */
(function () {
  "use strict";

  var observed = null;

  function mirror(root) {
    var target = document.documentElement.style;
    var style = root.style;
    for (var index = 0; index < style.length; index += 1) {
      var name = style[index];
      if (name.indexOf("--") === 0) {
        target.setProperty(name, style.getPropertyValue(name));
      }
    }
    if (style.colorScheme) {
      target.colorScheme = style.colorScheme;
    }
  }

  var observer = new MutationObserver(function () {
    if (observed) {
      mirror(observed);
    }
  });

  // O #app-root só existe depois que o Dash monta a página, e é recriado se
  // o layout for servido de novo: procura sempre que o DOM mudar.
  new MutationObserver(function () {
    var root = document.getElementById("app-root");
    if (!root || root === observed) {
      return;
    }
    observed = root;
    observer.disconnect();
    observer.observe(root, { attributes: true, attributeFilter: ["style"] });
    mirror(root);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
