/**
 * エントリポイント: ルーティング、データ同期、キーボード操作、各ビューの結線。
 */

import { $, debounce, isTypingTarget, storage } from './util.js';
import { api } from './api.js';
import { Store } from './state.js';
import { createHomeView } from './views/home.js';
import { createTreeView } from './views/tree.js';
import { createPreviewView } from './views/preview.js';
import { createSettingsView } from './views/settings.js';

const app = $('#app');
const store = new Store();

const dom = {
  app,
  brand: $('#brand'),
  brandTitle: $('#brandTitle'),
  brandMeta: $('#brandMeta'),
  favoritesToggle: $('#favoritesToggle'),
  favoritesLabel: $('#favoritesLabel'),
  settingsBtn: $('#settingsBtn'),
  homeSearch: $('#homeSearch'),
  treeSearch: $('#treeSearch'),
  backBtn: $('#backBtn'),
  resizer: $('#resizer'),
  toast: $('#toast'),
};

const homeView = createHomeView({
  store,
  dom: {
    grid: $('#folderGrid'),
    sentinel: $('#gridSentinel'),
    empty: $('#homeEmpty'),
    sortChips: $('#sortChips'),
    kindChips: $('#kindChips'),
    hiddenChip: $('#hiddenChip'),
    scroller: $('#homeView'),
  },
  onOpenFile: (file) => navigateToFile(file.id),
  onOpenFolder: (folder) => {
    if (folder.files.length === 0) return;
    navigateToFile(folder.files[0].id);
  },
  onToggleHidden: (folder) => toggleHidden(folder),
});

const treeView = createTreeView({
  store,
  dom: {
    scroller: $('#treeScroller'),
    viewport: $('#treeViewport'),
    spacer: $('#treeSpacer'),
    rows: $('#treeRows'),
    foot: $('#treeFoot'),
  },
  onOpenFile: (file) => navigateToFile(file.id),
});

const previewView = createPreviewView({
  store,
  api,
  dom: {
    stage: $('#stage'),
    placeholder: $('#previewPlaceholder'),
    error: $('#previewError'),
    status: $('#previewStatus'),
    source: $('#previewSource'),
    log: $('#previewLog'),
    crumbs: $('#crumbs'),
    favBtn: $('#favBtn'),
    reloadBtn: $('#reloadBtn'),
    sourceBtn: $('#sourceBtn'),
    logBtn: $('#logBtn'),
    externalBtn: $('#externalBtn'),
    isolationBtn: $('#isolationBtn'),
  },
  onToggleFavorite: (file) => toggleFavorite(file),
  onNotify: notify,
});

const settingsView = createSettingsView({
  dom: { modal: $('#settingsModal'), body: $('#settingsBody'), configPathHint: $('#configPathHint') },
  api,
  onChanged: () => sync(),
  onNotify: notify,
});

// ---------------------------------------------------------------------------
// データ同期
// ---------------------------------------------------------------------------
async function sync() {
  try {
    const token = store.userMutations;
    const payload = await api.index();
    // 取得中にお気に入り／非表示が更新されていたら、古いスナップショットで上書きしない。
    store.load(payload, { preserveUserState: token !== store.userMutations });
    settingsView.setRoots(payload.roots);
  } catch (error) {
    notify(`インデックスを取得できません: ${error.message}`);
  }
}

/** サーバーのロングポーリングに追随して、ファイル変更を自動反映する。 */
async function watchForever() {
  for (;;) {
    try {
      const revision = store.index ? store.index.revision : 0;
      const result = await api.watch(revision);
      if (result.changed) await sync();
    } catch {
      // 接続が切れた場合は少し待って再試行する。
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
}

// ---------------------------------------------------------------------------
// ルーティング（ハッシュベース）
// ---------------------------------------------------------------------------
function currentRoute() {
  const hash = location.hash.replace(/^#/, '');
  const match = hash.match(/^\/f\/(.+)$/);
  return match ? { view: 'preview', fileId: decodeURIComponent(match[1]) } : { view: 'home' };
}

function navigateToFile(fileId) {
  location.hash = `#/f/${encodeURIComponent(fileId)}`;
}

function navigateHome() {
  location.hash = '#/';
}

function applyRoute() {
  const route = currentRoute();
  app.dataset.view = route.view;
  if (route.view === 'preview') {
    const file = store.file(route.fileId);
    if (!file) {
      if (store.index) notify('ファイルが見つかりません');
      navigateHome();
      return;
    }
    store.activeFileId = file.id;
    store.setPref('lastFileId', file.id);
    previewView.open(file);
    treeView.render();
    treeView.revealActive();
    api.touchRecent(file.id).catch(() => {});
  } else {
    homeView.render();
    requestAnimationFrame(() => dom.homeSearch.focus({ preventScroll: true }));
  }
}

// ---------------------------------------------------------------------------
// ユーザー操作
// ---------------------------------------------------------------------------
async function toggleFavorite(file) {
  try {
    const result = await api.toggleFavorite(file.id);
    store.applyUserState({ favorites: result.favorites });
    notify(result.added ? 'お気に入りに追加しました' : 'お気に入りから外しました');
  } catch (error) {
    notify(error.message);
  }
}

async function toggleHidden(folder) {
  try {
    const result = await api.toggleHidden(folder.id);
    store.applyUserState({ hiddenFolders: result.hiddenFolders });
    notify(result.added ? `${folder.name} を非表示にしました` : `${folder.name} を再表示しました`);
  } catch (error) {
    notify(error.message);
  }
}

let toastTimer = 0;
function notify(message) {
  dom.toast.textContent = message;
  dom.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    dom.toast.hidden = true;
  }, 2200);
}

// ---------------------------------------------------------------------------
// ヘッダー・共通 UI
// ---------------------------------------------------------------------------
function renderChrome() {
  const stats = store.stats();
  const roots = store.index ? store.index.roots : [];
  dom.brandTitle.textContent = roots.length === 1 ? roots[0].name : 'html-preview-hub';
  const parts = [`${stats.folders} フォルダ`, `${stats.files} 件`];
  if (roots.length > 1) parts.unshift(`${roots.length} ルート`);
  if (stats.truncated) parts.push('上限に達しました');
  dom.brandMeta.textContent = parts.join(' / ');
  dom.favoritesLabel.textContent = `お気に入り (${store.favorites.size})`;
  dom.favoritesToggle.setAttribute('aria-pressed', String(store.prefs.favoritesOnly));
  app.dataset.sidebar = store.prefs.sidebarVisible ? 'visible' : 'hidden';
  app.style.setProperty('--sidebar-w', `${store.prefs.sidebarWidth}px`);
}

store.subscribe((reason) => {
  renderChrome();
  if (app.dataset.view === 'home') homeView.render();
  else {
    treeView.render();
    if (reason === 'index') previewView.refreshIfStale();
    previewView.syncActions();
  }
});

// ---------------------------------------------------------------------------
// イベント結線
// ---------------------------------------------------------------------------
dom.brand.addEventListener('click', navigateHome);
dom.backBtn.addEventListener('click', navigateHome);
dom.settingsBtn.addEventListener('click', () => settingsView.open(store.index ? store.index.roots : []));
dom.favoritesToggle.addEventListener('click', () => {
  store.setPref('favoritesOnly', !store.prefs.favoritesOnly);
});

$('#settingsModal').addEventListener('click', (event) => {
  if (event.target.dataset.close) settingsView.close();
});
$('#rescanBtn').addEventListener('click', async () => {
  notify('再スキャン中…');
  try {
    const payload = await api.rescan();
    store.load(payload);
    notify(`${payload.stats.fileCount} 件を読み込みました`);
  } catch (error) {
    notify(error.message);
  }
});

const onHomeSearch = debounce(() => {
  store.query = dom.homeSearch.value;
  homeView.render();
}, 60);
dom.homeSearch.addEventListener('input', onHomeSearch);

const onTreeSearch = debounce(() => {
  store.treeQuery = dom.treeSearch.value;
  treeView.render();
}, 60);
dom.treeSearch.addEventListener('input', onTreeSearch);

window.addEventListener('hashchange', applyRoute);

// サイドバー幅のドラッグ調整
(() => {
  let dragging = false;
  dom.resizer.addEventListener('pointerdown', (event) => {
    dragging = true;
    dom.resizer.classList.add('is-dragging');
    dom.resizer.setPointerCapture(event.pointerId);
  });
  dom.resizer.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const width = Math.min(560, Math.max(180, event.clientX));
    app.style.setProperty('--sidebar-w', `${width}px`);
  });
  const stop = () => {
    if (!dragging) return;
    dragging = false;
    dom.resizer.classList.remove('is-dragging');
    const width = parseInt(app.style.getPropertyValue('--sidebar-w'), 10);
    if (Number.isFinite(width)) store.setPref('sidebarWidth', width);
    treeView.refresh();
  };
  dom.resizer.addEventListener('pointerup', stop);
  dom.resizer.addEventListener('pointercancel', stop);
})();

// キーボードショートカット
document.addEventListener('keydown', (event) => {
  const typing = isTypingTarget(event.target);
  const meta = event.metaKey || event.ctrlKey;

  if (meta && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    focusSearch();
    return;
  }
  if (event.key === 'Escape') {
    if (settingsView.isOpen) return settingsView.close();
    if (typing) {
      event.target.blur();
      return;
    }
    if (app.dataset.view === 'preview') navigateHome();
    return;
  }
  if (typing) return;

  switch (event.key) {
    case '/':
      event.preventDefault();
      focusSearch();
      break;
    case ',':
      event.preventDefault();
      settingsView.open(store.index ? store.index.roots : []);
      break;
    case 'ArrowDown':
    case 'ArrowUp': {
      if (app.dataset.view !== 'preview') return;
      event.preventDefault();
      const next = treeView.move(event.key === 'ArrowDown' ? 1 : -1);
      if (next) navigateToFile(next.id);
      break;
    }
    case 'r':
      if (app.dataset.view === 'preview') previewView.reload();
      break;
    case 'u':
      if (app.dataset.view === 'preview') previewView.toggleSource();
      break;
    case 'l':
      if (app.dataset.view === 'preview') previewView.toggleLog();
      break;
    case 'f': {
      const file = previewView.current;
      if (app.dataset.view === 'preview' && file) toggleFavorite(file);
      break;
    }
    case '[':
      store.setPref('sidebarVisible', !store.prefs.sidebarVisible);
      break;
    default:
      break;
  }
});

function focusSearch() {
  const input = app.dataset.view === 'preview' ? dom.treeSearch : dom.homeSearch;
  input.focus();
  input.select();
}

// デバッグ用ハンドル（DevTools から状態を確認できるようにしておく）。
window.hph = { store, api, views: { home: homeView, tree: treeView, preview: previewView } };

// ---------------------------------------------------------------------------
// 起動
// ---------------------------------------------------------------------------
(async function boot() {
  renderChrome();
  await sync();
  if (!location.hash) {
    const last = storage.get('hph.prefs.v1', {}).lastFileId;
    location.hash = last && store.file(last) ? `#/f/${encodeURIComponent(last)}` : '#/';
  }
  applyRoute();
  watchForever();
})();
