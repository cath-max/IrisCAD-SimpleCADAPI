// Stitches 7 labeled PNGs into one grid image for vision-model feedback.
const DEFAULT_LAYOUT = [
  ["iso"],
  ["front", "back"],
  ["top", "bottom"],
  ["left", "right"],
];

export async function compositeGrid(images, opts = {}) {
  const tileSize = opts.tileSize ?? 512;

  // Index the rendered images by perspectives; 
  // Perspectives that are rendered but not mentioned in the layout (such as front right) are appended to the end by 2 per line.
  const byView = new Map(images.map(({ view, bytes }) => [view, bytes]));
  const rows = DEFAULT_LAYOUT
    .map((row) => row.filter((view) => byView.has(view)))
    .filter((row) => row.length > 0);
  const inLayout = new Set(DEFAULT_LAYOUT.flat());
  const extras = images.map(({ view }) => view).filter((v) => !inLayout.has(v));
  for (let i = 0; i < extras.length; i += 2) {
    rows.push(extras.slice(i, i + 2));
  }

  const columns = Math.max(...rows.map((row) => row.length));
  const canvas = new OffscreenCanvas(columns * tileSize, rows.length * tileSize);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#f5f5f7";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  let firstTile = true;
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
    const row = rows[rowIndex];
    const startX = (canvas.width - row.length * tileSize) / 2;
    for (let colIndex = 0; colIndex < row.length; colIndex++) {
      const view = row[colIndex];
      const x = startX + colIndex * tileSize;
      const y = rowIndex * tileSize;
      await drawTile(ctx, byView.get(view), view, x, y, tileSize);
      if (firstTile && opts.legend && opts.legend.length) {
        drawLegend(ctx, opts.legend, x, y);
      }
      firstTile = false;
    }
  }

  return canvas.convertToBlob({ type: "image/png" });
}

async function drawTile(ctx, bytes, view, x, y, tileSize) {
  const blob = new Blob([bytes], { type: "image/png" });
  const bitmap = await createImageBitmap(blob);

  const scale = Math.min(tileSize / bitmap.width, tileSize / bitmap.height);
  const drawWidth = bitmap.width * scale;
  const drawHeight = bitmap.height * scale;
  const drawX = x + (tileSize - drawWidth) / 2;
  const drawY = y + (tileSize - drawHeight) / 2;
  ctx.drawImage(bitmap, drawX, drawY, drawWidth, drawHeight);

  ctx.strokeStyle = "#c4c4c8";
  ctx.strokeRect(x + 0.5, y + 0.5, tileSize - 1, tileSize - 1);

  ctx.fillStyle = "#1a1d24";
  ctx.font = "bold 20px sans-serif";
  ctx.fillText(view, x + 10, y + 26);
}



function drawLegend(ctx, legend, x, y) {
  let legendY = y + 44;
  ctx.font = "13px sans-serif";
  for (const entry of legend) {
    const [r, g, b] = entry.color;
    ctx.fillStyle = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
    ctx.fillRect(x + 10, legendY - 10, 12, 12);
    ctx.fillStyle = "#1a1d24";
    ctx.fillText(entry.label ?? entry.tag, x + 28, legendY);
    legendY += 18;
  }
}
