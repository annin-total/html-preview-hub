const palette = ["#1a1917", "#8d887e", "#e6e2d9", "#d9a441", "#4c78d8"];
document.getElementById("swatches").innerHTML = palette
  .map(
    (color) =>
      `<div class="swatch" style="background:${color}" title="${color}"></div>`,
  )
  .join("");
