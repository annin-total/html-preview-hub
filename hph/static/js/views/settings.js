/**
 * 設定モーダル: 対象フォルダ、共通の除外条件、対象ファイルの種類、詳細設定、ショートカット一覧。
 */

import { el, errorReason } from "../util.js";
import { createExcludeEditor } from "./exclude-editor.js";
import { createRootList } from "./root-list.js";
import { advancedSettings, shortcutSection } from "./settings-advanced.js";

const HTML_EXTS = [".html", ".htm", ".xhtml"];
const TEX_EXT = ".tex";

export function createSettingsView({ dom, api, onChanged, onNotify }) {
  let config = null;
  let lastRoots = [];
  let texStatus = null;
  let typesNode = null;
  const editorStates = new Map();
  const advancedState = { open: false };

  const editorState = (key) => {
    if (!editorStates.has(key)) editorStates.set(key, {});
    return editorStates.get(key);
  };

  /** 即時保存の共通処理。失敗は通知してから投げ直し、呼び出し側に表示を戻させる。 */
  async function persist(request) {
    try {
      await request();
    } catch (error) {
      onNotify(`保存できなかったため元に戻しました: ${errorReason(error)}`);
      throw error;
    }
    await onChanged();
  }

  const rootList = createRootList({
    api,
    onNotify,
    onChanged,
    reload: () => refresh(),
    persist,
    editorState,
  });

  async function refresh() {
    try {
      const payload = await api.config();
      config = payload.config;
      dom.configPathHint.textContent = payload.configPath;
    } catch (error) {
      onNotify(`設定を読み込めません: ${error.message}`);
      return;
    }
    texStatus = await api.texStatus().catch(() => null);
    render();
  }

  function excludeSection() {
    return el(
      "section",
      { class: "settings-section", "aria-labelledby": "secExclude" },
      [
        el("div", { class: "section-head" }, [
          el("h3", {
            class: "section-title",
            id: "secExclude",
            text: "共通の除外条件",
          }),
        ]),
        el("p", {
          class: "section-note",
          text: "すべての対象フォルダに適用します。名前の大文字と小文字は区別しません。",
        }),
        createExcludeEditor({
          rules: config.exclude,
          label: "共通の除外条件を追加",
          emptyText:
            "除外条件はありません。一覧に出したくないフォルダやファイルがあれば、下の行で名前を指定してください。",
          state: editorState("global"),
          onChange: (exclude) =>
            persist(async () => {
              await api.updateConfig({ exclude });
              config.exclude = exclude;
            }),
        }),
      ],
    );
  }

  function typesSection() {
    const exts = config.include_extensions;
    const html = HTML_EXTS.every((ext) => exts.includes(ext));
    const tex = exts.includes(TEX_EXT);
    // HTML の拡張子が一部だけのときは、隠さず「その他」に出す
    const others = exts.filter(
      (ext) => ext !== TEX_EXT && !(html && HTML_EXTS.includes(ext)),
    );
    // 「その他」があればすべてオフにはならないので、HTML・LaTeX の両方を外せる
    const lastOne = !others.length && Number(html) + Number(tex) === 1;
    const check = (label, meta, on, next) =>
      el("label", { class: "check" }, [
        el("input", {
          type: "checkbox",
          checked: on,
          disabled: on && lastOne,
          "aria-describedby": on && lastOne ? "typesHint" : null,
          onchange: (event) => saveTypes(next, event.target),
        }),
        label,
        el("span", { class: "check__meta", text: meta }),
      ]);
    const without = (removed) => exts.filter((ext) => !removed.includes(ext));
    const hintStyle = "margin:var(--sp-2) 0 0";
    return el(
      "section",
      { class: "settings-section", "aria-labelledby": "secTypes" },
      [
        el("div", { class: "section-head" }, [
          el("h3", {
            class: "section-title",
            id: "secTypes",
            text: "対象ファイルの種類",
          }),
        ]),
        el(
          "div",
          { class: "chips", role: "group", "aria-labelledby": "secTypes" },
          [
            check(
              "HTML",
              HTML_EXTS.join(" "),
              html,
              html ? without(HTML_EXTS) : [...without(HTML_EXTS), ...HTML_EXTS],
            ),
            check(
              "LaTeX",
              TEX_EXT,
              tex,
              tex ? without([TEX_EXT]) : [...exts, TEX_EXT],
            ),
          ],
        ),
        others.length
          ? el("p", {
              class: "section-note",
              style: hintStyle,
              text: `その他: ${others.join(" ")}（設定ファイルで指定されています）`,
            })
          : null,
        lastOne
          ? el("p", {
              class: "section-note",
              id: "typesHint",
              style: hintStyle,
              text: "少なくとも 1 つは選んでください。",
            })
          : null,
      ],
    );
  }

  /** 保存中は全チェックを止める（続けて押すと古い一覧から計算した保存で上書きするため）。 */
  async function saveTypes(next, input) {
    const boxes = [...typesNode.querySelectorAll("input")];
    const index = boxes.indexOf(input);
    for (const box of boxes) box.disabled = true;
    try {
      await persist(async () => {
        await api.updateConfig({ include_extensions: next });
        config.include_extensions = next;
      });
    } catch {
      // persist が通知済み。config は保存前のままなので、下の描き直しでチェックも戻る
    }
    const fresh = typesSection();
    typesNode.replaceWith(fresh);
    typesNode = fresh;
    typesNode.querySelectorAll("input")[index].focus();
  }

  async function save(patch) {
    try {
      await api.updateConfig(patch);
      onNotify("設定を保存しました");
      await onChanged();
      refresh();
    } catch (error) {
      onNotify(`保存できません: ${error.message}`);
    }
  }

  function render() {
    if (!config) return;
    typesNode = typesSection();
    dom.body.replaceChildren(
      rootList.render(lastRoots),
      excludeSection(),
      typesNode,
      advancedSettings({ config, texStatus, save, state: advancedState }),
      shortcutSection(),
    );
  }

  return {
    async open(indexRoots) {
      lastRoots = indexRoots;
      dom.modal.hidden = false;
      await refresh();
    },
    close() {
      dom.modal.hidden = true;
      rootList.reset();
    },
    setRoots(indexRoots) {
      lastRoots = indexRoots;
      rootList.setRoots(indexRoots);
    },
    get isOpen() {
      return !dom.modal.hidden;
    },
  };
}
