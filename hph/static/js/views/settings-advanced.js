/** 設定の「詳細設定」: スキャン設定・LaTeX・ショートカット一覧（保存ボタンで保存する）。 */

import { el } from "../util.js";

const SHORTCUTS = [
  ["/ または Ctrl/⌘ + K", "検索にフォーカス"],
  ["↑ / ↓", "ファイルを移動"],
  ["Enter", "開く"],
  ["Esc", "一覧へ戻る / 検索解除"],
  ["r", "プレビューを再読み込み"],
  ["u", "ソース表示の切り替え"],
  ["l", "コンパイルログの切り替え"],
  ["f", "お気に入り切り替え"],
  ["t", "表示名の切り替え（タイトル / ファイル名）"],
  ["[", "サイドバーの表示切り替え"],
  [", (カンマ)", "設定を開く"],
  ["カード右クリック", "フォルダの非表示切り替え"],
];
const LABEL_STYLE = "flex:0 0 210px;font-size:12px;color:var(--text-dim)";

// 空欄は送らない（undefined は JSON から落ちるので、今の値が保たれる）
const parseNumber = (value) =>
  value.trim() === "" ? undefined : Number(value);

function fieldRow(label, control) {
  return el("div", { class: "field", style: "margin-bottom:8px" }, [
    el("label", { for: control.id, style: LABEL_STYLE, text: label }),
    control,
  ]);
}

/** 入力欄の行と、全欄をまとめて保存するボタンを作る。 */
function fieldForm(config, fields, buttonText, save) {
  const inputs = new Map();
  const rows = fields.map(([key, label, format]) => {
    const input = el("input", {
      type: "text",
      id: `setting-${key}`,
      value: format(config[key]),
    });
    inputs.set(key, input);
    return fieldRow(label, input);
  });
  const button = el("div", { class: "field" }, [
    el("button", {
      class: "pill",
      type: "button",
      text: buttonText,
      onclick: () => {
        const patch = {};
        for (const [key, , , parse] of fields)
          patch[key] = parse(inputs.get(key).value);
        save(patch);
      },
    }),
  ]);
  return { rows, button };
}

function scanSettings(config, save) {
  const fields = [
    ["max_depth", "最大階層", String, parseNumber],
    [
      "watch_interval_seconds",
      "自動再スキャン間隔（秒 / 0 で無効）",
      String,
      parseNumber,
    ],
  ];
  const { rows, button } = fieldForm(
    config,
    fields,
    "スキャン設定を保存",
    save,
  );
  return [...rows, button];
}

/** LaTeX 設定と、検出されたエンジンの表示。 */
function texSettings(config, texStatus, save) {
  const fields = [
    [
      "tex_engine",
      "エンジン（auto で自動判定）",
      String,
      (v) => v.trim() || "auto",
    ],
    [
      "tex_timeout_seconds",
      "コンパイルのタイムアウト（秒）",
      String,
      parseNumber,
    ],
    [
      "tex_max_passes",
      "コンパイル回数（latexmk 未使用時）",
      String,
      parseNumber,
    ],
  ];
  const { rows, button } = fieldForm(config, fields, "LaTeX 設定を保存", save);
  const detected = texStatus
    ? texStatus.engines.length
      ? `検出: ${texStatus.engines.join(", ")}${texStatus.latexmk ? " / latexmk" : ""}`
      : "検出されたエンジンはありません（pdflatex / xelatex / lualatex / tectonic のいずれかを導入してください）"
    : "";
  return [
    fieldRow(
      "PDF プレビュー",
      el("button", {
        class: "chip",
        type: "button",
        id: "setting-tex_enabled",
        "aria-pressed": String(Boolean(config.tex_enabled)),
        text: config.tex_enabled ? "有効" : "無効",
        onclick: () => save({ tex_enabled: !config.tex_enabled }),
      }),
    ),
    ...rows,
    el("div", {
      style: "font-size:11px;color:var(--text-faint);margin:4px 0 10px",
      text: detected,
    }),
    button,
  ];
}

/** 開閉式の詳細設定。state.open で開閉を再描画をまたいで保つ。 */
export function advancedSettings({ config, texStatus, save, state }) {
  const details = el(
    "details",
    { class: "disclosure settings-section", open: state.open },
    [
      el("summary", { text: "詳細設定（スキャン・LaTeX・ショートカット）" }),
      el("div", { class: "disclosure__body" }, [
        el("h3", { class: "section-title", text: "スキャン設定" }),
        ...scanSettings(config, save),
        el("h3", { class: "section-title", text: "LaTeX" }),
        ...texSettings(config, texStatus, save),
        el("h3", { class: "section-title", text: "ショートカット" }),
        el(
          "div",
          { class: "shortcut-list" },
          SHORTCUTS.map(([keys, desc]) =>
            el("div", {}, [el("kbd", { text: keys }), " ", desc]),
          ),
        ),
      ]),
    ],
  );
  details.addEventListener("toggle", () => {
    state.open = details.open;
  });
  return details;
}
