/**
 * ホーム画面（フォルダカードのグリッド）。
 * 大量のフォルダでも初期表示が重くならないよう、チャンク単位で追記描画する。
 */

import { el, formatDate, highlight } from '../util.js';
import { KINDS, SORTS } from '../state.js';

const CHUNK_SIZE = 48;
const MAX_FILES_PER_CARD = 3;

export function createHomeView({ store, dom, onOpenFile, onOpenFolder, onToggleHidden }) {
  let folders = [];
  let rendered = 0;

  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) appendChunk();
    },
    { root: dom.scroller, rootMargin: '600px' },
  );
  observer.observe(dom.sentinel);

  // --- チップ（並び替え） ---------------------------------------------
  function renderSortChips() {
    dom.sortChips.replaceChildren(
      ...SORTS.map((sort) =>
        el('button', {
          class: 'chip',
          type: 'button',
          'aria-pressed': String(store.prefs.sort === sort.id),
          onclick: () => store.setPref('sort', sort.id),
          text: sort.label,
        }),
      ),
    );
  }

  dom.hiddenChip.addEventListener('click', () => {
    store.setPref('showHidden', !store.prefs.showHidden);
  });

  // 種類チップは、2 種類以上のファイルがあるときだけ出す。
  function renderKindChips() {
    const counts = store.kindCounts();
    const present = KINDS.filter((kind) => kind.id === 'all' || counts.get(kind.id));
    if (present.length <= 2) {
      dom.kindChips.replaceChildren();
      if (store.prefs.kind !== 'all') store.setPref('kind', 'all');
      return;
    }
    dom.kindChips.replaceChildren(
      ...present.map((kind) =>
        el('button', {
          class: 'chip',
          type: 'button',
          'aria-pressed': String(store.prefs.kind === kind.id),
          onclick: () => store.setPref('kind', kind.id),
          text: kind.id === 'all' ? kind.label : `${kind.label} (${counts.get(kind.id)})`,
        }),
      ),
    );
  }

  function renderHiddenChip() {
    const stats = store.stats();
    // 非表示フォルダが 0 件になったら、自動的に通常表示へ戻す。
    if (store.prefs.showHidden && stats.hidden === 0) {
      store.setPref('showHidden', false);
      return;
    }
    dom.hiddenChip.textContent = `非表示フォルダ (${stats.hidden})`;
    dom.hiddenChip.setAttribute('aria-pressed', String(store.prefs.showHidden));
    dom.hiddenChip.hidden = stats.hidden === 0 && !store.prefs.showHidden;
  }

  // --- カード ---------------------------------------------------------
  function buildCard(folder) {
    const terms = store.terms;
    const files = folder.files.slice(0, MAX_FILES_PER_CARD);
    const card = el(
      'article',
      {
        class: 'card',
        role: 'listitem',
        tabindex: '0',
        dataset: { folderId: folder.id },
        title: `${folder.displayPath}\n右クリックで${folder.hidden ? '再表示' : '非表示'}`,
        onclick: () => onOpenFolder(folder),
        onkeydown: (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onOpenFolder(folder);
          }
        },
        oncontextmenu: (event) => {
          event.preventDefault();
          onToggleHidden(folder);
        },
      },
      [
        el('header', { class: 'card__head' }, [
          el('span', {
            class: 'card__icon',
            html: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3.5 6.5A1.5 1.5 0 015 5h3.9l1.6 2H19a1.5 1.5 0 011.5 1.5v9A1.5 1.5 0 0119 19H5a1.5 1.5 0 01-1.5-1.5z"/></svg>',
          }),
          el('h3', { class: 'card__name', html: highlight(folder.name, terms) }),
          folder.depth > 0 || store.index.roots.length > 1
            ? el('span', { class: 'card__root', text: folder.rootName })
            : null,
        ]),
        el(
          'ul',
          { class: 'card__files' },
          files.map((file) =>
            el(
              'li',
              {
                class: `card__file${store.isFavorite(file.id) ? ' is-fav' : ''}`,
                title: file.relPath,
                onclick: (event) => {
                  event.stopPropagation();
                  onOpenFile(file);
                },
              },
              [
                el('span', { html: highlight(store.fileLabel(file), terms) }),
                file.kind !== 'html' ? el('em', { class: 'kind-badge', text: file.kind }) : null,
              ],
            ),
          ),
        ),
        el('footer', { class: 'card__foot' }, [
          el('span', { text: `${folder.fileCount} 件` }),
          el('span', { class: 'card__date', text: formatDate(folder.createdAt) }),
        ]),
      ],
    );
    return card;
  }

  function appendChunk() {
    if (rendered >= folders.length) return;
    const fragment = document.createDocumentFragment();
    const end = Math.min(folders.length, rendered + CHUNK_SIZE);
    for (let i = rendered; i < end; i += 1) fragment.append(buildCard(folders[i]));
    dom.grid.append(fragment);
    rendered = end;
  }

  function renderEmpty() {
    const hasRoots = store.index && store.index.roots.length > 0;
    dom.empty.hidden = folders.length > 0;
    if (folders.length > 0) return;
    dom.empty.replaceChildren(
      el('div', {}, [
        el('p', {
          text: hasRoots
            ? store.query
              ? `「${store.query}」に一致するファイルはありません`
              : 'HTML ファイルが見つかりませんでした'
            : '対象フォルダがまだ登録されていません',
        }),
        el('p', {
          html: hasRoots
            ? '検索条件を変えるか、右上の設定から対象フォルダを追加してください。'
            : '右上の設定ボタン、または <code>python -m hph &lt;フォルダ&gt; --save</code> で追加できます。',
        }),
      ]),
    );
  }

  function render() {
    folders = store.visibleFolders();
    rendered = 0;
    dom.grid.replaceChildren();
    renderSortChips();
    renderKindChips();
    renderHiddenChip();
    renderEmpty();
    appendChunk();
    // 画面が高い場合に備え、追加分が必要かを次フレームで判定する。
    requestAnimationFrame(() => {
      if (dom.scroller.scrollHeight <= dom.scroller.clientHeight) appendChunk();
    });
  }

  return { render };
}
