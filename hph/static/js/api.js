/** バックエンド API クライアント。すべて JSON、失敗時は Error を投げる。 */

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { error: text.slice(0, 500) };
    }
  }
  if (!response.ok) {
    throw new Error((payload && payload.error) || `${response.status} ${response.statusText}`);
  }
  return payload;
}

const post = (url, body) => request(url, { method: 'POST', body: JSON.stringify(body ?? {}) });

export const api = {
  index: () => request('/api/index'),
  /** リビジョンが進むまでサーバー側で待機するロングポーリング。 */
  watch: (revision, signal) => request(`/api/index/watch?revision=${revision}`, { signal }),
  rescan: () => post('/api/rescan'),
  config: () => request('/api/config'),
  updateConfig: (patch) => request('/api/config', { method: 'PUT', body: JSON.stringify(patch) }),
  addRoot: (path, name) => post('/api/roots', { path, name }),
  removeRoot: (rootId) => request(`/api/roots/${encodeURIComponent(rootId)}`, { method: 'DELETE' }),
  browse: (path) => request(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  toggleFavorite: (fileId) => post('/api/user/favorites', { fileId }),
  toggleHidden: (folderId) => post('/api/user/hidden', { folderId }),
  touchRecent: (fileId) => post('/api/user/recents', { fileId }),
  source: (fileId) => request(`/api/source?fileId=${encodeURIComponent(fileId)}`),
  texStatus: () => request('/api/tex/status'),
  texCompile: (fileId, force = false) => post('/api/tex/compile', { fileId, force }),
  openExternally: (fileId) => post('/api/open', { fileId }),
};

/** プレビュー用 URL。更新時刻をクエリに載せてキャッシュを無効化する。 */
export function rawUrl(file) {
  const path = file.relPath.split('/').map(encodeURIComponent).join('/');
  return `/raw/${encodeURIComponent(file.rootId)}/${path}?v=${Math.round(file.updatedAt)}`;
}
