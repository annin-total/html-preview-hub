/** 除外条件の部品: 文として読める札の並びと、[対象][名前][条件][追加] の追加行。 */

import { el } from "../util.js";

const TARGETS = { folder: "フォルダ名", file: "ファイル名" };
const MATCHES = {
  equals: "と一致する",
  contains: "を含む",
  prefix: "で始まる",
  suffix: "で終わる",
};
const PLACEHOLDERS = { folder: "例: draft", file: "例: .bak" };
const VISIBLE_RULES = 6;
const MAX_RULES = 100;
const MESSAGES = {
  separator:
    "/ や \\ は使えません。フォルダやファイルの名前だけを入力してください。",
  duplicate: "同じ条件がすでにあります。",
  limit: `除外条件は ${MAX_RULES} 件までです。不要な条件を削除してから追加してください。`,
};

let errorSeq = 0;

const sentence = (rule) =>
  `${TARGETS[rule.target]}が「${rule.value}」${MATCHES[rule.match]}`;

// サーバーは casefold で比べる。画面の判定は目安で、最終判断はサーバー
const sameRule = (a, b) =>
  a.target === b.target &&
  a.match === b.match &&
  a.value.toLowerCase() === b.value.toLowerCase();

/** 除外条件の部品を作る。onChange が reject したら保存前の表示に戻す。state は開閉を再描画をまたいで保つ。 */
export function createExcludeEditor({
  rules,
  onChange,
  label,
  emptyText,
  state = {},
}) {
  let items = rules.map((rule) => ({ rule, pending: false }));
  let busy = false;
  let inputError = "";
  const errorId = `exclude-error-${++errorSeq}`;

  const target = el(
    "select",
    { "aria-label": "除外する対象" },
    Object.entries(TARGETS).map(([key, text]) =>
      el("option", { value: key, text: `${text}が` }),
    ),
  );
  const value = el("input", {
    type: "text",
    "aria-label": "名前",
    placeholder: PLACEHOLDERS.folder,
    maxlength: "200",
    spellcheck: "false",
    autocomplete: "off",
  });
  const match = el(
    "select",
    { "aria-label": "条件" },
    Object.entries(MATCHES).map(([key, text]) =>
      el("option", { value: key, text }),
    ),
  );
  const addButton = el("button", {
    class: "pill",
    type: "button",
    text: "追加",
    onclick: submit,
  });
  const errorLine = el("p", { class: "field-error", id: errorId });

  target.addEventListener("change", () => {
    value.placeholder = PLACEHOLDERS[target.value];
  });
  value.addEventListener("input", () => {
    inputError = "";
    syncForm();
  });
  value.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    submit();
  });

  let listNode = renderList();
  const root = el("div", {}, [
    listNode,
    el("div", {}, [
      el(
        "div",
        { class: "field rule-form", role: "group", "aria-label": label },
        [target, value, match, addButton],
      ),
      errorLine,
    ]),
  ]);
  syncForm();
  return root;

  function renderList() {
    if (!items.length) return el("p", { class: "rule-empty", text: emptyText });
    const shown = state.expanded ? items : items.slice(0, VISIBLE_RULES);
    const rest = items.length - VISIBLE_RULES;
    return el("ul", { class: "rule-list" }, [
      ...shown.map(ruleItem),
      rest > 0
        ? el(
            "li",
            {},
            el("button", {
              class: "rule-more",
              type: "button",
              "aria-expanded": String(Boolean(state.expanded)),
              text: state.expanded ? "折りたたむ" : `ほか ${rest} 件を表示`,
              onclick: toggleMore,
            }),
          )
        : null,
    ]);
  }

  function ruleItem(item) {
    const { rule } = item;
    return el("li", { class: `rule${item.pending ? " is-pending" : ""}` }, [
      el("span", { class: "rule__text" }, [
        `${TARGETS[rule.target]}が「`,
        el("span", { class: "rule__value", text: rule.value }),
        `」${MATCHES[rule.match]}`,
      ]),
      el("button", {
        class: "rule__remove",
        type: "button",
        "aria-label": `「${sentence(rule)}」を削除`,
        text: "✕",
        disabled: item.pending || busy,
        onclick: () => remove(item),
      }),
    ]);
  }

  function redraw() {
    const next = renderList();
    listNode.replaceWith(next);
    listNode = next;
    syncForm();
  }

  function syncForm() {
    const full = items.length >= MAX_RULES;
    for (const control of [target, value, match]) control.disabled = full;
    addButton.disabled = full || busy || !value.value.trim();
    const message = full ? MESSAGES.limit : inputError;
    errorLine.textContent = message;
    errorLine.hidden = !message;
    if (inputError && !full) value.setAttribute("aria-invalid", "true");
    else value.removeAttribute("aria-invalid");
    if (message) value.setAttribute("aria-describedby", errorId);
    else value.removeAttribute("aria-describedby");
  }

  /** 表示中の items を保存する。失敗したら before に戻して false を返す。 */
  async function commit(before) {
    busy = true;
    redraw();
    const kept = items.filter((item) => !item.removing);
    try {
      await onChange(kept.map((item) => item.rule));
      items = kept.map((item) => ({ rule: item.rule, pending: false }));
      return true;
    } catch {
      items = before;
      return false;
    } finally {
      busy = false;
      redraw();
    }
  }

  async function submit() {
    const text = value.value.trim();
    if (!text || busy || items.length >= MAX_RULES) return;
    const rule = { target: target.value, match: match.value, value: text };
    if (/[/\\]/.test(text)) inputError = MESSAGES.separator;
    else if (items.some((item) => sameRule(item.rule, rule)))
      inputError = MESSAGES.duplicate;
    if (inputError) return syncForm();
    const before = items;
    items = [...items, { rule, pending: true }];
    if (items.length > VISIBLE_RULES) state.expanded = true;
    if (await commit(before)) value.value = "";
    syncForm();
    value.focus();
  }

  async function remove(item) {
    if (busy) return;
    const index = items.indexOf(item);
    const before = items;
    items = items.map((other) =>
      other === item ? { ...other, pending: true, removing: true } : other,
    );
    const saved = await commit(before);
    const buttons = listNode.querySelectorAll(".rule__remove");
    const next = saved ? Math.min(index, buttons.length - 1) : index;
    (buttons[next] || target).focus();
  }

  function toggleMore() {
    state.expanded = !state.expanded;
    redraw();
    listNode.querySelector(".rule-more").focus();
  }
}
