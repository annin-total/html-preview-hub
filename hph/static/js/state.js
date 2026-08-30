/**
 * アプリの状態管理。
 *
 * - サーバーから受け取ったインデックスを、描画に使いやすい形へ 1 度だけ整形する。
 * - 検索用の文字列（haystack）もリビジョンごとに 1 度だけ構築し、入力のたびの
 *   走査コストを最小化する（数千件でもインクリメンタルサーチが止まらない）。
 */

import { storage } from './util.js';

const PREF_KEY = 'hph.prefs.v1';

export const SORTS = [
  { id: 'created-desc', label: '作成日が新しい順', compare: (a, b) => b.createdAt - a.createdAt },
  { id: 'created-asc', label: '作成日が古い順', compare: (a, b) => a.createdAt - b.createdAt },
  { id: 'updated-desc', label: '更新が新しい順', compare: (a, b) => b.updatedAt - a.updatedAt },
  { id: 'name-asc', label: '名前順', compare: (a, b) => a.name.localeCompare(b.name, 'ja') },
];

const DEFAULT_PREFS = {
  sort: SORTS[0].id,
  showHidden: false,
  favoritesOnly: false,
  sidebarWidth: 288,
  sidebarVisible: true,
  isolation: 'strict',
  lastFileId: null,
};

export class Store {
  constructor() {
    this.prefs = { ...DEFAULT_PREFS, ...storage.get(PREF_KEY, {}) };
    this.index = null;
    this.filesById = new Map();
    this.foldersById = new Map();
    this.folders = [];
    this.favorites = new Set();
    this.hidden = new Set();
    this.recents = [];
    this.query = '';
    this.treeQuery = '';
    this.collapsed = new Set();
    this.activeFileId = null;
    this.listeners = new Set();
    // お気に入り等をユーザーが更新した回数。取得中に更新が入ったかの判定に使う。
    this.userMutations = 0;
  }

  // ----------------------------------------------------------------
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(reason) {
    for (const listener of this.listeners) listener(reason, this);
  }

  setPref(key, value) {
    if (this.prefs[key] === value) return;
    this.prefs[key] = value;
    storage.set(PREF_KEY, this.prefs);
    this.emit('prefs');
  }

  // ----------------------------------------------------------------
  /**
   * サーバーのインデックスを取り込み、派生データを構築する。
   *
   * `preserveUserState` は、取得中にユーザーがお気に入り等を更新した場合に使う。
   * 取得開始より前のスナップショットでローカルの操作を打ち消さないための保護。
   */
  load(payload, { preserveUserState = false } = {}) {
    this.index = payload;
    this.filesById = new Map();
    for (const file of payload.files) {
      file.haystack = `${file.relPath}\n${file.title}`.toLowerCase();
      this.filesById.set(file.id, file);
    }
    if (!preserveUserState) {
      this.favorites = new Set(payload.userState.favorites);
      this.hidden = new Set(payload.userState.hiddenFolders);
      this.recents = payload.userState.recents.slice();
    }

    this.foldersById = new Map();
    this.folders = payload.folders.map((folder) => {
      const files = folder.fileIds.map((id) => this.filesById.get(id)).filter(Boolean);
      files.sort((a, b) => b.updatedAt - a.updatedAt);
      const enriched = {
        ...folder,
        files,
        displayPath: folder.relPath ? `${folder.rootName}/${folder.relPath}` : folder.rootName,
      };
      enriched.haystack = `${enriched.displayPath}\n${files.map((f) => f.haystack).join('\n')}`.toLowerCase();
      this.foldersById.set(folder.id, enriched);
      return enriched;
    });
    this.emit('index');
  }

  applyUserState(patch) {
    this.userMutations += 1;
    if (patch.favorites) this.favorites = new Set(patch.favorites);
    if (patch.hiddenFolders) this.hidden = new Set(patch.hiddenFolders);
    if (patch.recents) this.recents = patch.recents.slice();
    this.emit('user');
  }

  // ----------------------------------------------------------------
  get terms() {
    return this.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  }

  get treeTerms() {
    return this.treeQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
  }

  get sort() {
    return SORTS.find((s) => s.id === this.prefs.sort) || SORTS[0];
  }

  file(fileId) {
    return this.filesById.get(fileId) || null;
  }

  folderOfFile(file) {
    return file ? this.foldersById.get(`${file.rootId}:${file.dir}`) || null : null;
  }

  isFavorite(fileId) {
    return this.favorites.has(fileId);
  }

  isHidden(folderId) {
    return this.hidden.has(folderId);
  }

  /** ホーム画面に出すフォルダ（検索・非表示・お気に入り絞り込み・並び替えを適用）。 */
  visibleFolders() {
    const terms = this.terms;
    const { showHidden, favoritesOnly } = this.prefs;
    const result = [];
    for (const folder of this.folders) {
      const hidden = this.hidden.has(folder.id);
      // 「非表示フォルダ」チップは、非表示にしたフォルダだけを見るモード。
      if (showHidden !== hidden) continue;
      let files = folder.files;
      if (favoritesOnly) {
        files = files.filter((f) => this.favorites.has(f.id));
        if (files.length === 0) continue;
      }
      if (terms.length) {
        const folderMatches = terms.every((t) => folder.displayPath.toLowerCase().includes(t));
        const matched = files.filter((f) => terms.every((t) => f.haystack.includes(t)));
        if (!folderMatches && matched.length === 0) continue;
        if (matched.length) {
          const rest = files.filter((f) => !matched.includes(f));
          files = matched.concat(rest);
        }
      }
      result.push({ ...folder, files, hidden });
    }
    result.sort(this.sort.compare);
    return result;
  }

  /** サイドバー用のフラットな行リスト（仮想スクロールに渡す）。 */
  treeRows() {
    const terms = this.treeTerms;
    const rows = [];
    const folders = this.folders
      .filter((folder) => !this.hidden.has(folder.id) || this.prefs.showHidden)
      .slice()
      .sort((a, b) => a.displayPath.localeCompare(b.displayPath, 'ja'));
    for (const folder of folders) {
      const folderMatches = terms.length
        ? terms.every((t) => folder.displayPath.toLowerCase().includes(t))
        : true;
      const files = terms.length && !folderMatches
        ? folder.files.filter((f) => terms.every((t) => f.haystack.includes(t)))
        : folder.files;
      if (files.length === 0 && !folderMatches) continue;
      const collapsed = this.collapsed.has(folder.id) && terms.length === 0;
      rows.push({ type: 'folder', id: folder.id, folder, collapsed, count: folder.files.length });
      if (collapsed) continue;
      for (const file of files) rows.push({ type: 'file', id: file.id, file, folder });
    }
    return rows;
  }

  /** ヘッダー表示用の統計値。 */
  stats() {
    if (!this.index) return { folders: 0, files: 0, hidden: 0, roots: 0, truncated: false };
    const hidden = this.folders.filter((f) => this.hidden.has(f.id)).length;
    return {
      folders: this.folders.length - hidden,
      files: this.filesById.size,
      hidden,
      roots: this.index.roots.length,
      truncated: this.index.truncated,
    };
  }
}
