/**
 * プレビュー領域。
 *
 * - HTML はそのまま iframe に描画する。既定は `allow-same-origin` を付けない
 *   厳格サンドボックスで、プレビュー対象の CSS / JS はアプリ本体へ干渉できない。
 * - LaTeX はサーバー側で PDF にコンパイルし、ブラウザ内蔵の PDF ビューアで表示する。
 *   PDF はサンドボックス iframe ではビューアが無効になるため、sandbox 属性を付けない
 *   （PDF ビューアは親ページの DOM へアクセスできないため分離は保たれる）。
 * - 一度開いたファイルは iframe プールに残し、再訪時の再読み込みを避ける。
 */

import { el, formatBytes, formatDateTime } from '../util.js';
import { rawUrl } from '../api.js';

const POOL_LIMIT = 6;
const SANDBOX_BASE =
  'allow-scripts allow-forms allow-modals allow-popups allow-downloads allow-popups-to-escape-sandbox';

export function createPreviewView({ store, dom, api, onToggleFavorite, onNotify }) {
  /** fileId → { frame, url } */
  const pool = new Map();
  let current = null;
  let cacheBuster = 0;
  let lastLog = '';

  function sandboxValue() {
    return store.prefs.isolation === 'compat' ? `${SANDBOX_BASE} allow-same-origin` : SANDBOX_BASE;
  }

  function createFrame(file, url, { sandboxed }) {
    const frame = el('iframe', {
      src: url,
      sandbox: sandboxed ? sandboxValue() : null,
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

  function dropFromPool(fileId) {
    const entry = pool.get(fileId);
    if (entry) {
      entry.frame.remove();
      pool.delete(fileId);
    }
  }

  /** プール済みの iframe をそのまま再表示できるなら true。 */
  function showCached(file, url) {
    const cached = pool.get(file.id);
    if (!cached || cached.url !== url) return false;
    cached.frame.style.display = '';
    pool.delete(file.id);
    pool.set(file.id, cached);
    hideError();
    return true;
  }

  function showFrame(file, url, { sandboxed }) {
    if (showCached(file, url)) return;
    dropFromPool(file.id);
    const frame = createFrame(file, url, { sandboxed });
    frame.addEventListener('error', () =>
      showError('プレビューの読み込みに失敗しました', file.relPath),
    );
    pool.set(file.id, { frame, url });
    evict();
    hideError();
  }

  // ------------------------------------------------------------------
  // 表示状態
  // ------------------------------------------------------------------
  function showStatus(message) {
    dom.status.replaceChildren(el('div', { class: 'box', text: message }));
    dom.status.hidden = false;
  }

  function hideStatus() {
    dom.status.hidden = true;
  }

  function showError(title, detail, { log = '', sourceOf = null } = {}) {
    const actions = [];
    if (log) {
      actions.push(
        el('button', {
          class: 'chip chip--sm',
          type: 'button',
          text: 'ログを表示',
          onclick: () => toggleLog(true),
        }),
      );
    }
    if (sourceOf) {
      actions.push(
        el('button', {
          class: 'chip chip--sm',
          type: 'button',
          text: 'ソースを表示',
          onclick: () => showSource(sourceOf),
        }),
      );
    }
    dom.error.replaceChildren(
      el('div', { class: 'box' }, [
        el('h3', { text: title }),
        detail ? el('p', { text: detail }) : null,
        actions.length ? el('div', { class: 'box__actions' }, actions) : null,
      ]),
    );
    dom.error.hidden = false;
  }

  function hideError() {
    dom.error.hidden = true;
  }

  function toggleLog(force) {
    const show = force === undefined ? dom.log.hidden : force;
    dom.log.textContent = lastLog || 'ログはありません';
    dom.log.hidden = !show;
    if (show) dom.source.hidden = true;
  }

  function syncLogButton() {
    dom.logBtn.hidden = !lastLog;
    if (!lastLog) dom.log.hidden = true;
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
    const isTex = file.kind === 'tex';
    dom.favBtn.classList.toggle('is-on', store.isFavorite(file.id));
    dom.isolationBtn.hidden = isTex; // PDF 表示では分離モードの切り替えは意味を持たない
    dom.isolationBtn.textContent = store.prefs.isolation === 'compat' ? '互換' : '分離';
    dom.isolationBtn.title =
      store.prefs.isolation === 'compat'
        ? '互換モード: localStorage 等を許可（分離レベルは下がります）'
        : '分離モード: アプリ本体と完全に分離（localStorage 等は使えません）';
    dom.reloadBtn.textContent = isTex ? '再コンパイル' : '再読込';
    dom.reloadBtn.title = isTex ? '強制的に再コンパイルする (r)' : 'プレビューを再読み込み (r)';
    syncLogButton();
  }

  // ------------------------------------------------------------------
  // HTML / LaTeX それぞれの表示
  // ------------------------------------------------------------------
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

  async function openHtml(file) {
    const url = `${rawUrl(file)}${cacheBuster ? `&t=${cacheBuster}` : ''}`;
    hideAll();
    if (showCached(file, url)) return;
    if (!(await verify(file, url))) return;
    if (current !== file) return; // 検証中に別ファイルへ切り替わった
    showFrame(file, url, { sandboxed: true });
  }

  async function openTex(file, { force = false } = {}) {
    hideAll();
    showStatus(force ? 'LaTeX を再コンパイルしています…' : 'LaTeX をコンパイルしています…');
    let result;
    try {
      result = await api.texCompile(file.id, force);
    } catch (error) {
      hideStatus();
      showError('コンパイルを実行できません', String(error.message || error));
      return;
    }
    if (current !== file) return;
    hideStatus();
    lastLog = result.log || '';
    syncLogButton();

    if (result.status === 'unavailable' || result.status === 'fragment') {
      const title =
        result.status === 'fragment' ? '単体ではコンパイルできません' : 'PDF プレビューを利用できません';
      showError(title, result.message, { log: result.log, sourceOf: file });
      return;
    }
    if (result.status !== 'ok') {
      dropFromPool(file.id);
      showError('コンパイルに失敗しました', result.message || 'ログを確認してください', {
        log: result.log,
        sourceOf: file,
      });
      return;
    }
    if (result.message) onNotify(result.message);
    // PDF はブラウザ内蔵ビューアで表示する（sandbox を付けるとビューアが無効になる）。
    showFrame(file, result.pdfUrl, { sandboxed: false });
  }

  /** ソースを取得して表示する（PDF にできないファイルでも中身は読めるようにする）。 */
  async function showSource(file) {
    try {
      const payload = await api.source(file.id);
      dom.source.textContent = payload.text + (payload.truncated ? '\n\n… (以降は省略)' : '');
      dom.log.hidden = true;
      dom.source.hidden = false;
    } catch (error) {
      onNotify(`ソースを取得できません: ${error.message || error}`);
    }
  }

  // ------------------------------------------------------------------
  async function open(file, options = {}) {
    if (!file) return;
    current = file;
    store.activeFileId = file.id;
    dom.placeholder.hidden = true;
    dom.source.hidden = true;
    dom.log.hidden = true;
    lastLog = '';
    renderCrumbs(file);
    syncActions(file);
    if (file.kind === 'tex') await openTex(file, options);
    else await openHtml(file);
  }

  function reload() {
    if (!current) return;
    if (current.kind === 'tex') {
      dropFromPool(current.id);
      open(current, { force: true });
      return;
    }
    cacheBuster = Date.now();
    dropFromPool(current.id);
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
    await showSource(current);
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
    const changed = latest.updatedAt !== current.updatedAt || latest.size !== current.size;
    current = latest;
    if (changed) {
      dropFromPool(latest.id);
      open(latest);
    } else {
      syncActions(latest);
    }
  }

  dom.favBtn.addEventListener('click', () => current && onToggleFavorite(current));
  dom.reloadBtn.addEventListener('click', reload);
  dom.sourceBtn.addEventListener('click', toggleSource);
  dom.externalBtn.addEventListener('click', openExternally);
  dom.isolationBtn.addEventListener('click', toggleIsolation);
  dom.logBtn.addEventListener('click', () => toggleLog());

  return {
    open,
    reload,
    toggleSource,
    toggleLog,
    refreshIfStale,
    syncActions: () => current && syncActions(current),
    get current() {
      return current;
    },
  };
}
