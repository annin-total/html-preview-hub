/**
 * 設定モーダル: 対象ルートフォルダの追加・削除、スキャン条件、ショートカット一覧。
 */

import { el } from '../util.js';

const SHORTCUTS = [
  ['/ または Ctrl/⌘ + K', '検索にフォーカス'],
  ['↑ / ↓', 'ファイルを移動'],
  ['Enter', '開く'],
  ['Esc', '一覧へ戻る / 検索解除'],
  ['r', 'プレビューを再読み込み'],
  ['u', 'ソース表示の切り替え'],
  ['f', 'お気に入り切り替え'],
  ['[', 'サイドバーの表示切り替え'],
  [', (カンマ)', '設定を開く'],
  ['カード右クリック', 'フォルダの非表示切り替え'],
];

export function createSettingsView({ dom, api, onChanged, onNotify }) {
  let config = null;
  let browserState = null;
  let lastRoots = [];

  async function refresh() {
    const payload = await api.config();
    config = payload.config;
    dom.configPathHint.textContent = payload.configPath;
    render();
  }

  function rootRows(indexRoots) {
    return indexRoots.map((root) =>
      el('div', { class: `root-row${root.exists ? '' : ' is-missing'}` }, [
        el('div', { class: 'root-row__body' }, [
          el('div', { class: 'root-row__name', text: root.name + (root.exists ? '' : '（見つかりません）') }),
          el('div', { class: 'root-row__path', text: root.path }),
        ]),
        el('span', { class: 'root-row__count', text: `${root.fileCount} 件` }),
        el('button', {
          class: 'chip chip--sm',
          type: 'button',
          text: '削除',
          onclick: async () => {
            await api.removeRoot(root.id);
            onNotify(`${root.name} を削除しました`);
            await onChanged();
            refresh();
          },
        }),
      ]),
    );
  }

  function addForm() {
    const input = el('input', {
      type: 'text',
      placeholder: '/path/to/html （フルパスを入力、または「参照」から選択）',
      spellcheck: 'false',
    });
    const submit = async () => {
      const value = input.value.trim();
      if (!value) return;
      try {
        const result = await api.addRoot(value);
        onNotify(`${result.root.name} を追加しました`);
        input.value = '';
        browserState = null;
        await onChanged();
        refresh();
      } catch (error) {
        onNotify(`追加できません: ${error.message}`);
      }
    };
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') submit();
    });
    return el('div', {}, [
      el('div', { class: 'field' }, [
        input,
        el('button', {
          class: 'chip',
          type: 'button',
          text: '参照',
          onclick: async () => {
            browserState = await api.browse(input.value.trim() || undefined).catch(() => null);
            render();
          },
        }),
        el('button', { class: 'pill pill--solid', type: 'button', text: '追加', onclick: submit }),
      ]),
      browserState ? browserPanel(input) : null,
    ]);
  }

  function browserPanel(input) {
    const go = async (path) => {
      try {
        browserState = await api.browse(path);
        input.value = browserState.path;
        render();
      } catch (error) {
        onNotify(error.message);
      }
    };
    return el('div', { class: 'browser' }, [
      el('div', { class: 'browser__path', text: browserState.path }),
      el('div', { class: 'browser__list' }, [
        browserState.parent
          ? el('button', {
              class: 'browser__item',
              type: 'button',
              text: '.. （上へ）',
              onclick: () => go(browserState.parent),
            })
          : null,
        ...browserState.entries.map((entry) =>
          el('button', {
            class: 'browser__item',
            type: 'button',
            text: `📁 ${entry.name}`,
            onclick: () => go(entry.path),
          }),
        ),
        browserState.entries.length === 0
          ? el('div', { class: 'browser__item', text: 'サブフォルダはありません' })
          : null,
      ]),
    ]);
  }

  function scanSettings() {
    const fields = [
      ['include_extensions', '対象拡張子（カンマ区切り）', (v) => v.join(', '), (v) => v.split(',').map((s) => s.trim()).filter(Boolean)],
      ['ignore_dirs', '除外フォルダ名（カンマ区切り）', (v) => v.join(', '), (v) => v.split(',').map((s) => s.trim()).filter(Boolean)],
      ['max_depth', '最大階層', String, (v) => Number(v)],
      ['watch_interval_seconds', '自動再スキャン間隔（秒 / 0 で無効）', String, (v) => Number(v)],
    ];
    const inputs = new Map();
    const rows = fields.map(([key, label, format]) => {
      const input = el('input', { type: 'text', value: format(config[key]) });
      inputs.set(key, input);
      return el('div', { class: 'field', style: 'margin-bottom:8px' }, [
        el('span', { style: 'flex:0 0 210px;font-size:12px;color:var(--text-dim)', text: label }),
        input,
      ]);
    });
    return el('div', {}, [
      ...rows,
      el('div', { class: 'field' }, [
        el('button', {
          class: 'pill',
          type: 'button',
          text: 'スキャン設定を保存',
          onclick: async () => {
            const patch = {};
            for (const [key, , , parse] of fields) patch[key] = parse(inputs.get(key).value);
            try {
              await api.updateConfig(patch);
              onNotify('設定を保存しました');
              await onChanged();
              refresh();
            } catch (error) {
              onNotify(`保存できません: ${error.message}`);
            }
          },
        }),
      ]),
    ]);
  }

  function render(indexRoots = []) {
    if (!config) return;
    const roots = indexRoots.length ? indexRoots : lastRoots;
    dom.body.replaceChildren(
      el('div', { class: 'root-list' }, roots.length ? rootRows(roots) : [
        el('div', { class: 'root-row', text: 'まだ登録されていません' }),
      ]),
      addForm(),
      el('div', { class: 'section-title', text: 'スキャン設定' }),
      scanSettings(),
      el('div', { class: 'section-title', text: 'ショートカット' }),
      el(
        'div',
        { class: 'shortcut-list' },
        SHORTCUTS.map(([keys, desc]) =>
          el('div', {}, [el('kbd', { text: keys }), ' ', desc]),
        ),
      ),
    );
  }

  return {
    async open(indexRoots) {
      lastRoots = indexRoots;
      dom.modal.hidden = false;
      await refresh();
      render(indexRoots);
    },
    close() {
      dom.modal.hidden = true;
      browserState = null;
    },
    setRoots(indexRoots) {
      lastRoots = indexRoots;
    },
    get isOpen() {
      return !dom.modal.hidden;
    },
  };
}
