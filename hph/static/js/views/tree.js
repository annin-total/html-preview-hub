/**
 * サイドバーのツリー（フォルダ + ファイル）。
 * 仮想スクロールで描画するため、数千件でも切り替えが即応する。
 */

import { el, highlight } from '../util.js';
import { createVirtualList } from '../virtual-list.js';

const ROW_HEIGHT = 30;

const FOLDER_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3.5 6.5A1.5 1.5 0 015 5h3.9l1.6 2H19a1.5 1.5 0 011.5 1.5v9A1.5 1.5 0 0119 19H5a1.5 1.5 0 01-1.5-1.5z"/></svg>';
const FILE_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M13 3H7a1.5 1.5 0 00-1.5 1.5v15A1.5 1.5 0 007 21h10a1.5 1.5 0 001.5-1.5V8.5z"/><path d="M13 3v5.5h5.5"/></svg>';
const TEX_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M13 3H7a1.5 1.5 0 00-1.5 1.5v15A1.5 1.5 0 007 21h10a1.5 1.5 0 001.5-1.5V8.5z"/><path d="M13 3v5.5h5.5"/><path d="M8.6 12.4h4.2M10.7 12.4V17"/></svg>';
const CARET =
  '<svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5 5 5-5"/></svg>';

export function createTreeView({ store, dom, onOpenFile }) {
  const list = createVirtualList({
    scroller: dom.scroller,
    viewport: dom.viewport,
    spacer: dom.spacer,
    rowsHost: dom.rows,
    rowHeight: ROW_HEIGHT,
    renderRow,
  });

  function renderRow(row) {
    if (!row) return null;
    const terms = store.treeTerms;
    if (row.type === 'folder') {
      return el(
        'div',
        {
          class: `tree__row tree__row--folder${row.collapsed ? ' is-collapsed' : ''}`,
          style: `height:${ROW_HEIGHT}px`,
          title: row.folder.displayPath,
          onclick: () => toggleFolder(row.folder.id),
        },
        [
          el('span', { class: 'tree__caret', html: CARET }),
          el('span', { class: 'tree__icon', html: FOLDER_ICON }),
          el('span', { class: 'tree__label', html: highlight(row.folder.displayPath, terms) }),
          el('span', { class: 'tree__meta', text: String(row.count) }),
        ],
      );
    }
    const isActive = store.activeFileId === row.file.id;
    return el(
      'div',
      {
        class: `tree__row${isActive ? ' is-active' : ''}`,
        style: `height:${ROW_HEIGHT}px;padding-left:26px`,
        title: `${row.folder.displayPath}/${row.file.name}`,
        onclick: () => onOpenFile(row.file),
      },
      [
        el('span', { class: 'tree__icon', html: row.file.kind === 'tex' ? TEX_ICON : FILE_ICON }),
        el('span', { class: 'tree__label', html: highlight(store.fileLabel(row.file), terms) }),
        store.isFavorite(row.file.id) ? el('span', { class: 'tree__star', text: '★' }) : null,
      ],
    );
  }

  function toggleFolder(folderId) {
    if (store.collapsed.has(folderId)) store.collapsed.delete(folderId);
    else store.collapsed.add(folderId);
    render();
  }

  function render() {
    const rows = store.treeRows();
    list.setRows(rows);
    const files = rows.filter((row) => row.type === 'file').length;
    const folders = rows.filter((row) => row.type === 'folder').length;
    dom.foot.textContent = `${folders} フォルダ / ${files} ファイル`;
  }

  /** 選択中のファイルが隠れている場合は展開してスクロールする。 */
  function revealActive() {
    const file = store.file(store.activeFileId);
    if (!file) return;
    const folderId = `${file.rootId}:${file.dir}`;
    if (store.collapsed.has(folderId)) {
      store.collapsed.delete(folderId);
      render();
    }
    const index = list.rows.findIndex((row) => row.type === 'file' && row.id === store.activeFileId);
    if (index >= 0) list.scrollToIndex(index);
    else list.refresh();
  }

  /** 上下キーでの移動。`delta` は行数。 */
  function move(delta) {
    const fileRows = list.rows.filter((row) => row.type === 'file');
    if (fileRows.length === 0) return null;
    const current = fileRows.findIndex((row) => row.id === store.activeFileId);
    const next = current < 0 ? 0 : Math.min(fileRows.length - 1, Math.max(0, current + delta));
    return fileRows[next].file;
  }

  return { render, revealActive, move, refresh: () => list.refresh() };
}
