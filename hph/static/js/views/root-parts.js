/** 対象フォルダ節の、状態を持たない表示部品（フォルダ一覧・場所の入力・削除の確認）。 */

import { el } from "../util.js";

/** 選択画面が使えないときのフォルダ一覧。browser は /api/browse の応答。 */
export function folderBrowser({ browser, onNavigate, onCancel, onAdd }) {
  const item = (text, path) =>
    el("button", {
      class: "browser__item",
      type: "button",
      text,
      onclick: () => onNavigate(path),
    });
  return el(
    "div",
    { class: "browser", role: "region", "aria-label": "フォルダの一覧" },
    [
      el("div", {
        class: "browser__note",
        text: "この環境ではフォルダの選択画面を開けません。下の一覧から選んでください。",
      }),
      el("div", { class: "browser__path", text: browser.path }),
      el("div", { class: "browser__list" }, [
        browser.parent ? item(".. （上へ）", browser.parent) : null,
        ...browser.entries.map((entry) => item(`📁 ${entry.name}`, entry.path)),
        browser.entries.length === 0
          ? el("div", {
              class: "browser__item",
              text: "サブフォルダはありません",
            })
          : null,
      ]),
      el("div", { class: "browser__foot" }, [
        el("button", {
          class: "chip",
          type: "button",
          text: "キャンセル",
          onclick: onCancel,
        }),
        el("button", {
          class: "pill pill--solid",
          type: "button",
          text: "このフォルダを追加",
          onclick: onAdd,
        }),
      ]),
    ],
  );
}

/** 開閉式の「場所を入力して追加」。Enter でも追加する。 */
export function manualEntry({ open, onToggle, onSubmit }) {
  const input = el("input", {
    type: "text",
    "aria-label": "フォルダの場所",
    placeholder: "例: /Users/name/Documents/reports",
    spellcheck: "false",
  });
  const submit = () => {
    const value = input.value.trim();
    if (value) onSubmit(value);
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) submit();
  });
  const details = el("details", { class: "disclosure", open }, [
    el("summary", { text: "場所を入力して追加" }),
    el("div", { class: "disclosure__body field" }, [
      input,
      el("button", {
        class: "pill",
        type: "button",
        text: "追加",
        onclick: submit,
      }),
    ]),
  ]);
  details.addEventListener("toggle", () => onToggle(details.open));
  return details;
}

/** 札の中で削除を確かめる行。フォルダの中身は消えないことを必ず書く。 */
export function removeConfirm({ name, onCancel, onConfirm }) {
  return el(
    "div",
    {
      class: "root-row__confirm",
      role: "group",
      "aria-label": `${name} の削除の確認`,
    },
    [
      el("span", {
        class: "root-row__confirm-text",
        text: "対象から削除しますか？ このフォルダだけの除外条件も消えます（フォルダの中身は消えません）。",
      }),
      el("button", {
        class: "chip chip--sm",
        type: "button",
        text: "やめる",
        onclick: onCancel,
      }),
      el("button", {
        class: "chip chip--sm chip--danger",
        type: "button",
        text: "削除する",
        onclick: onConfirm,
      }),
    ],
  );
}
