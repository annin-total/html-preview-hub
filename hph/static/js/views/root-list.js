/** 設定の「対象フォルダ」節: 選択画面からの追加、アプリ内の一覧、札ごとの削除と除外条件。 */

import { el, errorReason } from "../util.js";
import { createExcludeEditor } from "./exclude-editor.js";
import { folderBrowser, manualEntry, removeConfirm } from "./root-parts.js";

const NOTE = "一覧に表示するフォルダです。中のフォルダも含めて探します。";
const NOTE_PICKING =
  "開いた選択画面でフォルダを選んでください。選ばずに閉じた場合は何も変わりません。";

const rulesSummary = (count) =>
  `このフォルダだけの除外条件（${count ? `${count} 件` : "なし"}）`;

/** 節を描く部品を作る。reload は設定全体の読み直し、persist は即時保存の共通処理。 */
export function createRootList({
  api,
  onNotify,
  onChanged,
  reload,
  persist,
  editorState,
}) {
  let roots = [];
  let section = null;
  let picking = false;
  let browser = null;
  let confirming = null;
  let manualOpen = false;
  const openRules = new Set();
  const counts = new Map();

  function render(nextRoots) {
    roots = nextRoots;
    counts.clear();
    section = el(
      "section",
      { class: "settings-section", "aria-labelledby": "secRoots" },
      [
        el("div", { class: "section-head" }, [
          el("h3", {
            class: "section-title",
            id: "secRoots",
            text: "対象フォルダ",
          }),
          el("button", {
            class: "pill pill--solid",
            type: "button",
            disabled: picking,
            text: picking ? "選択画面を開いています…" : "フォルダを追加",
            onclick: pick,
          }),
        ]),
        el("p", {
          class: "section-note",
          "aria-live": "polite",
          text: picking ? NOTE_PICKING : NOTE,
        }),
        el(
          "div",
          { class: "root-list" },
          roots.length
            ? roots.map(rootRow)
            : el("div", {
                class: "root-row",
                text: "まだ登録されていません。「フォルダを追加」から選んでください。",
              }),
        ),
        browser
          ? el(
              "div",
              { style: "margin-bottom:var(--sp-3)" },
              folderBrowser({
                browser,
                onNavigate: openBrowser,
                onCancel: () => {
                  browser = null;
                  redraw();
                  focusAddButton();
                },
                onAdd: () => addRoot(browser.path),
              }),
            )
          : null,
        manualEntry({
          open: manualOpen,
          onToggle: (open) => {
            manualOpen = open;
          },
          onSubmit: addRoot,
        }),
      ],
    );
    return section;
  }

  function redraw() {
    const previous = section;
    previous.replaceWith(render(roots));
  }

  const focusIn = (selector) => section.querySelector(selector)?.focus();
  const focusAddButton = () => focusIn(".section-head .pill");
  const focusRemove = (id) => focusIn(`[data-root-id="${id}"] > .chip`);

  function rootRow(root) {
    const count = el("span", {
      class: "root-row__count",
      text: `${root.fileCount} 件`,
    });
    counts.set(root.id, count);
    const isConfirming = confirming === root.id;
    return el(
      "div",
      {
        class: `root-row${root.exists ? "" : " is-missing"}`,
        dataset: { rootId: root.id },
      },
      [
        el("div", { class: "root-row__body" }, [
          el("div", {
            class: "root-row__name",
            text: root.name + (root.exists ? "" : "（見つかりません）"),
          }),
          el("div", {
            class: "root-row__path",
            text: root.path,
            title: root.path,
          }),
        ]),
        count,
        isConfirming
          ? confirmBox(root)
          : el("button", {
              class: "chip chip--sm",
              type: "button",
              text: "削除",
              "aria-label": `${root.name} を対象から削除`,
              onclick: () => {
                confirming = root.id;
                redraw();
                focusIn(".root-row__confirm .chip");
              },
            }),
        rootRules(root),
      ],
    );
  }

  function confirmBox(root) {
    const cancel = () => {
      confirming = null;
      redraw();
      focusRemove(root.id);
    };
    const confirm = async () => {
      try {
        await api.removeRoot(root.id);
      } catch (error) {
        onNotify(`削除できません: ${errorReason(error)}`);
        return cancel();
      }
      confirming = null;
      onNotify(`${root.name} を削除しました`);
      await onChanged();
      await reload();
      focusAddButton();
    };
    return removeConfirm({
      name: root.name,
      onCancel: cancel,
      onConfirm: confirm,
    });
  }

  function rootRules(root) {
    const summary = el("summary", { text: rulesSummary(root.exclude.length) });
    const details = el(
      "details",
      { class: "disclosure root-row__rules", open: openRules.has(root.id) },
      [
        summary,
        el(
          "div",
          { class: "disclosure__body" },
          createExcludeEditor({
            rules: root.exclude,
            label: `${root.name} の除外条件を追加`,
            emptyText: "除外条件はありません",
            state: editorState(root.id),
            onChange: (exclude) =>
              persist(async () => {
                await api.updateRoot(root.id, { exclude });
                summary.textContent = rulesSummary(exclude.length);
              }),
          }),
        ),
      ],
    );
    details.addEventListener("toggle", () => {
      if (details.open) openRules.add(root.id);
      else openRules.delete(root.id);
    });
    return details;
  }

  async function pick() {
    picking = true;
    redraw();
    let result;
    try {
      result = await api.pickFolder();
    } catch (error) {
      result =
        error.status === 403
          ? { status: "unavailable" }
          : { status: "", error };
    }
    picking = false;
    if (result.status === "selected" && (await addRoot(result.path))) return;
    if (result.status === "unavailable") return openBrowser();
    if (result.error)
      onNotify(
        result.error.status === 409
          ? "フォルダの選択画面はすでに開いています"
          : `追加できません: ${errorReason(result.error)}`,
      );
    redraw();
    focusAddButton();
  }

  /** 追加して設定を読み直す。失敗したら通知して false を返す（表示はそのまま）。 */
  async function addRoot(path) {
    try {
      const result = await api.addRoot(path);
      onNotify(`${result.root.name} を追加しました`);
    } catch (error) {
      onNotify(`追加できません: ${errorReason(error)}`);
      return false;
    }
    browser = null;
    await onChanged();
    await reload();
    focusAddButton();
    return true;
  }

  async function openBrowser(path) {
    try {
      browser = await api.browse(path);
    } catch (error) {
      onNotify(errorReason(error));
    }
    redraw();
    focusIn(browser ? "button.browser__item" : ".section-head .pill");
  }

  return {
    render,
    /** 再描画せずに件数だけ差し替える（入力中のフォーカスを奪わないため）。 */
    updateCounts(nextRoots) {
      for (const root of nextRoots) {
        const count = counts.get(root.id);
        if (count) count.textContent = `${root.fileCount} 件`;
      }
    },
    reset() {
      browser = null;
      confirming = null;
    },
  };
}
