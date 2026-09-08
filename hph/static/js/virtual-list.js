/**
 * 固定行高の仮想スクロールリスト。
 * 表示範囲の行だけを DOM に置くことで、数千行でもスクロールが軽い。
 */
export function createVirtualList({
  scroller,
  viewport,
  spacer,
  rowsHost,
  rowHeight,
  overscan = 8,
  renderRow,
}) {
  let rows = [];
  let firstRendered = -1;
  let lastRendered = -1;

  function render(force = false) {
    const total = rows.length;
    spacer.style.height = `${total * rowHeight}px`;
    const scrollTop = scroller.scrollTop;
    const visible = Math.ceil(scroller.clientHeight / rowHeight);
    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
    const end = Math.min(total, start + visible + overscan * 2);
    if (!force && start === firstRendered && end === lastRendered) return;
    firstRendered = start;
    lastRendered = end;

    const fragment = document.createDocumentFragment();
    for (let i = start; i < end; i += 1) {
      const node = renderRow(rows[i], i);
      if (node) fragment.append(node);
    }
    rowsHost.style.transform = `translateY(${start * rowHeight}px)`;
    rowsHost.replaceChildren(fragment);
  }

  scroller.addEventListener("scroll", () => render(), { passive: true });
  const observer = new ResizeObserver(() => render(true));
  observer.observe(scroller);

  return {
    setRows(next) {
      rows = next;
      render(true);
    },
    refresh() {
      render(true);
    },
    get rows() {
      return rows;
    },
    scrollToIndex(index) {
      if (index < 0) return;
      const top = index * rowHeight;
      const bottom = top + rowHeight;
      if (top < scroller.scrollTop) scroller.scrollTop = top;
      else if (bottom > scroller.scrollTop + scroller.clientHeight) {
        scroller.scrollTop = bottom - scroller.clientHeight;
      }
      render();
    },
    viewport,
  };
}
