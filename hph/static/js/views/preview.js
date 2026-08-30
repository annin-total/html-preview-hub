/**
 * プレビュー領域。
 *
 * - iframe を LRU でプールし、一度開いたファイルへの再訪を即時表示にする。
 * - 既定は `allow-same-origin` を付けない厳格サンドボックス。プレビュー対象の
 *   CSS / JS はアプリ本体の DOM・ストレージへ一切アクセスできない。
 */

import { el, formatBytes, formatDateTime } from '../util.js';
import { rawUrl } from '../api.js';

const POOL_LIMIT = 6;
const SANDBOX_BASE = 'allow-scripts allow-forms allow-modals allow-popups allow-downloads allow-popups-to-escape-sandbox';

export function createPreviewView({ store, dom, api, onToggleFavorite, onNotify }) {
  /** fileId → { frame, url } */
  const pool = new Map();
  let current = null;
  let cacheBuster = 0;

  function sandboxValue() {
    return store.prefs.isolation === 'compat' ? `${SANDBOX_BASE} allow-same-origin` : SANDBOX_BASE;
  }

  function createFrame(file) {
    const frame = el('iframe', {
      src: `${rawUrl(file)}${cacheBuster ? `&t=${cacheBuster}` : ''}`,
      sandbox: sandboxValue(),
      referrerpolicy: 'no-referrer',
      loading: 'eager',
      title: file.relPath,
    });
    dom.stage.append(frame);
    return frame;
  }

  function evict() {
    while (pool.size > POOL_LIMIT) {
      const [oldestId, entry] = pool.entries().next().value;
      entry.frame.remove();
      pool.delete(oldestId);
    }
  }

  function hideAll() {
    for (const entry of pool.values()) entry.frame.style.display = 'none';
  }

  /** 実際に読み込めるかを事前に確認し、失敗理由を画面に出す。 */
  async function verify(file, url) {
    try {
      const response = await fetch(url, { method: 'HEAD', cache: 'no-store' });
      if (!response.ok) {
        showError(
          'プレビューを表示できません',
          `${response.status} ${response.statusText} — ${file.relPath}`,
        );
        return false;
      }
    } catch (error) {
      showError('プレビューを表示できません', String(error));
      return false;
    }
    hideError();
    return true;
  }

  function showError(title, detail) {
    dom.error.replaceChildren(
      el('div', { class: 'box' }, [el('h3', { text: title }), el('p', { text: detail })]),
    );
    dom.error.hidden = false;
  }

  function hideError() {
    dom.error.hidden = true;
  }

  function renderCrumbs(file) {
    const folder = store.folderOfFile(file);
    const parts = folder ? folder.displayPath.split('/') : [];
    const nodes = [];
    parts.forEach((part) => {
      nodes.push(el('span', { text: part }));
      nodes.push(el('span', { class: 'sep', text: '/' }));
    });
    nodes.push(el('b', { text: file.name }));
    nodes.push(
      el('span', {
        class: 'sep',
        text: `· ${formatBytes(file.size)} · ${formatDateTime(file.updatedAt)}`,
      }),
    );
    dom.crumbs.replaceChildren(...nodes);
  }

  function syncActions(file) {
    dom.favBtn.classList.toggle('is-on', store.isFavorite(file.id));
    dom.isolationBtn.textContent = store.prefs.isolation === 'compat' ? '互換' : '分離';
    dom.isolationBtn.title =
      store.prefs.isolation === 'compat'
        ? '互換モード: localStorage 等を許可（分離レベルは下がります）'
        : '分離モード: アプリ本体と完全に分離（localStorage 等は使えません）';
  }

  async function open(file) {
    if (!file) return;
    current = file;
    store.activeFileId = file.id;
    dom.placeholder.hidden = true;
    dom.source.hidden = true;
    renderCrumbs(file);
    syncActions(file);

    const url = `${rawUrl(file)}${cacheBuster ? `&t=${cacheBuster}` : ''}`;
    const cached = pool.get(file.id);
    hideAll();
    if (cached && cached.url === url) {
      // 既に読み込み済み → 再フェッチせず即座に表示する。
      cached.frame.style.display = '';
      pool.delete(file.id);
      pool.set(file.id, cached);
      hideError();
      return;
    }
    if (cached) {
      cached.frame.remove();
      pool.delete(file.id);
    }
    if (!(await verify(file, url))) return;
    if (current !== file) return; // 検証中に別ファイルへ切り替わった
    const frame = createFrame(file);
    frame.addEventListener('error', () => showError('プレビューの読み込みに失敗しました', file.relPath));
    pool.set(file.id, { frame, url });
    evict();
  }

  function reload() {
    if (!current) return;
    cacheBuster = Date.now();
    const entry = pool.get(current.id);
    if (entry) {
      entry.frame.remove();
      pool.delete(current.id);
    }
    open(current);
    onNotify('再読み込みしました');
  }

  function toggleIsolation() {
    const next = store.prefs.isolation === 'compat' ? 'strict' : 'compat';
    store.setPref('isolation', next);
    for (const entry of pool.values()) entry.frame.remove();
    pool.clear();
    if (current) open(current);
    onNotify(next === 'compat' ? '互換モードで表示します' : '分離モードで表示します');
  }

  async function toggleSource() {
    if (!current) return;
    if (!dom.source.hidden) {
      dom.source.hidden = true;
      return;
    }
    try {
      const payload = await api.source(current.id);
      dom.source.textContent = payload.text + (payload.truncated ? '\n\n… (以降は省略)' : '');
      dom.source.hidden = false;
    } catch (error) {
      showError('ソースを取得できません', String(error.message || error));
    }
  }

  async function openExternally() {
    if (!current) return;
    try {
      await api.openExternally(current.id);
      onNotify('既定のブラウザで開きました');
    } catch (error) {
      onNotify(`開けませんでした: ${error.message}`);
    }
  }

  /** インデックス更新時、表示中ファイルが変わっていれば読み直す。 */
  function refreshIfStale() {
    if (!current) return;
    const latest = store.file(current.id);
    if (!latest) {
      showError('ファイルが削除されました', current.relPath);
      return;
    }
    const entry = pool.get(latest.id);
    if (entry && entry.url !== `${rawUrl(latest)}${cacheBuster ? `&t=${cacheBuster}` : ''}`) {
      current = latest;
      open(latest);
    } else {
      current = latest;
      syncActions(latest);
    }
  }

  dom.favBtn.addEventListener('click', () => current && onToggleFavorite(current));
  dom.reloadBtn.addEventListener('click', reload);
  dom.sourceBtn.addEventListener('click', toggleSource);
  dom.externalBtn.addEventListener('click', openExternally);
  dom.isolationBtn.addEventListener('click', toggleIsolation);

  return {
    open,
    reload,
    toggleSource,
    refreshIfStale,
    syncActions: () => current && syncActions(current),
    get current() {
      return current;
    },
  };
}
