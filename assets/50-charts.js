/*
 * Desenha os gráficos do painel com Chart.js.
 *
 * O Python não manda código, manda uma especificação em JSON no atributo
 * `data-chart` de um <div> (ver `ui/charts.py`). Este arquivo só traduz essa
 * especificação para a configuração do Chart.js. Toda regra de negócio —
 * quais séries, que cor, onde ficam as marcas do eixo, como o número é
 * escrito — continua decidida no servidor.
 *
 * Por que um MutationObserver e não uma callback do Dash: as telas são
 * trocadas inteiras pelo Dash (período, aba, cliente), e o gráfico precisa
 * nascer junto com o <div> em qualquer um desses caminhos. Observar o DOM
 * cobre todos eles sem uma callback por gráfico.
 */
(function () {
  "use strict";

  if (!window.Chart) {
    return;
  }

  var live = new Set();

  // As cores vêm do PRÓPRIO gráfico, não do :root: o tema do cliente é
  // aplicado no #app-root (e a sidebar tem tokens próprios), então o :root
  // pode estar com a marca de outra tela.
  function token(element, name, fallback) {
    var value = getComputedStyle(element).getPropertyValue(name);
    return (value && value.trim()) || fallback;
  }

  function wash(hex, alpha) {
    var value = String(hex || "").replace("#", "");
    if (value.length !== 6) {
      return hex;
    }
    var red = parseInt(value.slice(0, 2), 16);
    var green = parseInt(value.slice(2, 4), 16);
    var blue = parseInt(value.slice(4, 6), 16);
    return "rgba(" + red + ", " + green + ", " + blue + ", " + alpha + ")";
  }

  function theme(element) {
    return {
      font: token(element, "--font", "Inter, system-ui, sans-serif"),
      ink: token(element, "--ink", "#0b0b0d"),
      muted: token(element, "--ink-muted", "#767b84"),
      grid: token(element, "--line-soft", "#eff0f2"),
      line: token(element, "--line", "#e6e7ea"),
      surface: token(element, "--surface", "#ffffff"),
    };
  }

  function tooltip(colors, mode) {
    return {
      mode: mode,
      intersect: false,
      backgroundColor: colors.surface,
      borderColor: colors.line,
      borderWidth: 1,
      titleColor: colors.muted,
      bodyColor: colors.ink,
      titleFont: { family: colors.font, size: 11, weight: "500" },
      bodyFont: { family: colors.font, size: 12, weight: "600" },
      padding: 10,
      cornerRadius: 8,
      boxWidth: 8,
      boxHeight: 8,
      boxPadding: 4,
      usePointStyle: true,
      callbacks: {
        // O texto do tooltip vem pronto do servidor: no modo base 100 ele
        // mostra o valor REAL, não o índice.
        label: function (context) {
          var shown = context.dataset.display && context.dataset.display[context.dataIndex];
          return " " + context.dataset.label + "  " + (shown != null ? shown : context.formattedValue);
        },
      },
    };
  }

  function cartesian(spec, colors) {
    var isBar = spec.kind === "bar";
    var last = spec.labels.length - 1;
    var yTicks = (spec.y && spec.y.ticks) || [];
    var yLabels = (spec.y && spec.y.labels) || [];

    var datasets = spec.datasets.map(function (item) {
      var dataset = {
        label: item.label,
        data: item.data,
        display: item.display,
        borderColor: item.color,
        backgroundColor: isBar ? item.color : item.fill ? wash(item.color, 0.1) : item.color,
        pointBackgroundColor: item.color,
        pointBorderColor: colors.surface,
      };
      if (isBar) {
        dataset.borderRadius = 4;
        dataset.borderSkipped = "start";
        dataset.maxBarThickness = 24;
        dataset.categoryPercentage = 0.7;
        dataset.barPercentage = 0.9;
        dataset.hoverBackgroundColor = wash(item.color, 0.8);
      } else {
        dataset.borderWidth = 2;
        dataset.tension = 0.35;
        dataset.fill = item.fill ? "origin" : false;
        dataset.pointHoverRadius = 4;
        dataset.pointHoverBorderWidth = 2;
        // Marcador só no último ponto: o "agora" merece um ponto, o resto não.
        dataset.pointRadius = item.lastPoint
          ? item.data.map(function (_, index) { return index === last ? 4 : 0; })
          : 0;
        dataset.pointBorderWidth = 2;
      }
      return dataset;
    });

    return {
      type: isBar ? "bar" : "line",
      data: { labels: spec.labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 380 },
        interaction: { mode: "index", intersect: false },
        layout: { padding: { top: 6, right: 6 } },
        plugins: {
          legend: { display: false },
          tooltip: tooltip(colors, "index"),
        },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: {
              color: colors.muted,
              font: { family: colors.font, size: 10 },
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: spec.xTicks || 7,
            },
          },
          y: {
            min: 0,
            max: yTicks.length ? yTicks[yTicks.length - 1] : undefined,
            grid: { color: colors.grid, drawTicks: false },
            border: { display: false },
            // As marcas vêm calculadas do servidor em números redondos; o
            // Chart.js só as posiciona.
            afterBuildTicks: function (axis) {
              if (yTicks.length) {
                axis.ticks = yTicks.map(function (value) { return { value: value }; });
              }
            },
            ticks: {
              color: colors.muted,
              font: { family: colors.font, size: 10 },
              padding: 8,
              callback: function (value, index) {
                return yLabels[index] != null ? yLabels[index] : value;
              },
            },
          },
        },
      },
    };
  }

  function doughnut(spec, colors) {
    var item = spec.datasets[0] || { data: [], colors: [] };
    var center = spec.center || {};
    var hasData = item.data.some(function (value) { return value > 0; });

    return {
      type: "doughnut",
      data: {
        labels: spec.labels,
        datasets: [{
          label: item.label,
          // Sem investimento a rosca some; um anel cinza mantém a forma.
          data: hasData ? item.data : [1],
          display: item.display,
          backgroundColor: hasData ? item.colors : [colors.grid],
          borderColor: colors.surface,
          borderWidth: 2,
          hoverOffset: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "68%",
        animation: { duration: 380 },
        layout: { padding: 6 },
        plugins: {
          legend: { display: false },
          tooltip: Object.assign(tooltip(colors, "nearest"), {
            intersect: true,
            enabled: hasData,
          }),
        },
      },
      plugins: [{
        id: "center-total",
        afterDraw: function (chart) {
          var area = chart.chartArea;
          if (!area) {
            return;
          }
          var context = chart.ctx;
          var x = (area.left + area.right) / 2;
          var y = (area.top + area.bottom) / 2;
          context.save();
          context.textAlign = "center";
          context.textBaseline = "middle";
          context.fillStyle = colors.ink;
          context.font = "600 17px " + colors.font;
          context.fillText(center.value || "", x, y - 7);
          context.fillStyle = colors.muted;
          context.font = "400 10px " + colors.font;
          context.fillText(center.label || "", x, y + 12);
          context.restore();
        },
      }],
    };
  }

  function build(spec, element) {
    var colors = theme(element);
    return spec.kind === "doughnut" ? doughnut(spec, colors) : cartesian(spec, colors);
  }

  function render(element) {
    var raw = element.getAttribute("data-chart");
    if (!raw) {
      return;
    }
    var chart = element.__chart;
    if (chart && element.__chartRaw === raw && element.contains(chart.canvas)) {
      return;
    }

    var spec;
    try {
      spec = JSON.parse(raw);
    } catch (error) {
      return;
    }

    var canvas = element.querySelector("canvas");
    if (!canvas) {
      canvas = document.createElement("canvas");
      element.appendChild(canvas);
    }

    var config = build(spec, element);
    if (chart && chart.canvas === canvas && chart.config.type === config.type) {
      // Mesmo gráfico, dados novos: atualiza em vez de recriar, para a
      // transição animar de uma curva para a outra.
      chart.data = config.data;
      chart.options = config.options;
      chart.update();
    } else {
      if (chart) {
        chart.destroy();
      }
      element.__chart = new window.Chart(canvas, config);
    }
    element.__chartRaw = raw;
    live.add(element);
  }

  function sweep() {
    // Gráfico cujo <div> saiu da tela é destruído: sem isso cada troca de
    // período deixava instâncias penduradas ouvindo resize.
    live.forEach(function (element) {
      if (!element.isConnected) {
        if (element.__chart) {
          element.__chart.destroy();
        }
        element.__chart = null;
        live.delete(element);
      }
    });
    document.querySelectorAll("[data-chart]").forEach(render);
  }

  var scheduled = false;
  function schedule() {
    if (scheduled) {
      return;
    }
    scheduled = true;
    window.requestAnimationFrame(function () {
      scheduled = false;
      sweep();
    });
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["data-chart"],
  });
  schedule();
})();
