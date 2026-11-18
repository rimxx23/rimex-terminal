const priceLabel = (value) => Number(value).toFixed(2);
const timeLabel = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

export function createTradeChart(loadCandles) {
  const canvas = document.getElementById("price-chart");
  const context = canvas.getContext("2d");
  const status = document.getElementById("chart-status");
  const summary = document.getElementById("chart-summary");
  const controls = document.getElementById("chart-intervals");
  let interval = "1m";
  let feed;
  let orders = [];
  let trades = [];
  let hover = null;
  let pending;
  let range;

  function draw() {
    if (!context || !feed?.candles.length) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width < 130 || height < 90) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    const padding = { left: 9, right: 53, top: 12, bottom: 27 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const candles = feed.candles.slice(-Math.max(12, Math.floor(plotWidth / 6)));
    const xSize = plotWidth / candles.length;
    const endX = width - padding.right;
    const low = Math.min(...candles.map((candle) => Number(candle.low)));
    const high = Math.max(...candles.map((candle) => Number(candle.high)));
    const margin = Math.max((high - low) * .11, .02);
    const ceiling = high + margin;
    const floor = low - margin;
    const y = (price) => padding.top + (ceiling - Number(price)) / (ceiling - floor) * plotHeight;
    const x = (index) => padding.left + (index + .5) * xSize;
    const viewIndex = hover === null ? candles.length - 1 : Math.max(0, Math.min(hover, candles.length - 1));
    range = { left: padding.left, step: xSize, count: candles.length };

    function line(x1, y1, x2, y2, color, dash = []) {
      context.strokeStyle = color;
      context.setLineDash(dash);
      context.beginPath();
      context.moveTo(x1, y1);
      context.lineTo(x2, y2);
      context.stroke();
      context.setLineDash([]);
    }

    context.font = "10px ui-monospace, monospace";
    context.textBaseline = "middle";
    for (let step = 0; step <= 4; step++) {
      const tick = ceiling - (ceiling - floor) * step / 4;
      const py = y(tick);
      line(padding.left, py, endX, py, "#333");
      context.fillStyle = "#b7b7b7";
      context.fillText(priceLabel(tick), endX + 5, py);
    }
    const labels = Math.max(2, Math.floor(plotWidth / 95));
    for (let step = 0; step < labels; step++) {
      const index = Math.min(candles.length - 1, Math.round((candles.length - 1) * step / labels));
      const px = x(index);
      line(px, padding.top, px, height - padding.bottom, "#292929");
      context.fillStyle = "#a5a5a5";
      context.fillText(timeLabel.format(candles[index].time * 1000), Math.max(px - 10, 0), height - 12);
    }

    candles.forEach((candle, index) => {
      const rising = Number(candle.close) >= Number(candle.open);
      const color = rising ? "#e9e9e9" : "#818181";
      const center = x(index);
      const top = Math.min(y(candle.open), y(candle.close));
      const h = Math.max(1, Math.abs(y(candle.open) - y(candle.close)));
      const w = Math.max(2, Math.min(xSize * .63, 9));
      line(center, y(candle.high), center, y(candle.low), color);
      context.fillStyle = color;
      context.fillRect(center - w / 2, top, w, h);
    });

    function overlayInRange(value) {
      const number = Number(value);
      return number >= floor && number <= ceiling;
    }

    for (const order of orders) {
      if (order.status !== "open" || !overlayInRange(order.price)) continue;
      const py = y(order.price);
      line(padding.left, py, endX, py, "#b1b1b1", order.side === "buy" ? [5, 5] : [2, 5]);
      context.fillStyle = "#d9d9d9";
      context.fillText(order.side === "buy" ? "B" : "S", endX - 14, Math.max(8, py - 7));
    }

    for (const trade of trades) {
      const candleIndex = candles.findIndex(
        (candle) => trade.created_at >= candle.time && trade.created_at < candle.time + feed.seconds,
      );
      if (candleIndex < 0 || !overlayInRange(trade.price)) continue;
      const center = x(candleIndex);
      const py = y(trade.price);
      const buy = trade.side === "buy";
      context.beginPath();
      context.arc(center, py, 7, 0, Math.PI * 2);
      context.fillStyle = buy ? "#f4f4f4" : "#171717";
      context.fill();
      context.strokeStyle = "#eee";
      context.stroke();
      context.fillStyle = buy ? "#111" : "#f4f4f4";
      context.fillText(buy ? "B" : "S", center - 3, py + .5);
    }

    if (hover !== null) line(x(viewIndex), padding.top, x(viewIndex), height - padding.bottom, "#818181", [3, 4]);
    const candle = candles[viewIndex];
    summary.textContent = `${timeLabel.format(candle.time * 1000)}  O ${priceLabel(candle.open)}  H ${priceLabel(candle.high)}  L ${priceLabel(candle.low)}  C ${priceLabel(candle.close)}`;
  }

  async function refresh() {
    if (document.hidden || pending?.interval === interval) return;
    const request = { interval };
    pending = request;
    try {
      const response = await loadCandles(request.interval);
      if (pending !== request) return;
      feed = response;
      status.textContent = feed.stale ? "Showing cached Binance candles" : "";
      draw();
    } catch {
      if (pending === request) status.textContent = "Chart data is temporarily unavailable.";
    } finally {
      if (pending === request) pending = undefined;
    }
  }

  controls.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-interval]");
    if (!button || button.dataset.interval === interval) return;
    interval = button.dataset.interval;
    hover = null;
    feed = null;
    range = null;
    context?.clearRect(0, 0, canvas.width, canvas.height);
    summary.textContent = "";
    status.textContent = "Loading candles…";
    for (const item of controls.querySelectorAll("button")) {
      item.setAttribute("aria-pressed", String(item === button));
    }
    refresh();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!range) return;
    const index = Math.floor((event.offsetX - range.left) / range.step);
    if (hover !== index) {
      hover = index;
      draw();
    }
  });
  canvas.addEventListener("pointerleave", () => { hover = null; draw(); });
  canvas.addEventListener("keydown", (event) => {
    if (!range || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const current = hover ?? range.count - 1;
    hover = Math.max(0, Math.min(current + (event.key === "ArrowLeft" ? -1 : 1), range.count - 1));
    draw();
  });
  new ResizeObserver(draw).observe(canvas);

  return {
    start() {
      refresh();
      setInterval(refresh, 8000);
    },
    update(nextOrders, nextTrades) {
      orders = nextOrders;
      trades = nextTrades;
      draw();
    },
  };
}
