/** 対象フォルダを追加する流れ: OS の選択画面、アプリ内の一覧、場所の入力。 */

import { errorReason } from "../util.js";

/** 待機中・一覧の状態を持ち、変わるたびに onUpdate(focus) で再描画を頼む（focus は "add" | "browser" | null）。 */
export function createRootAdder({ api, onNotify, onAdded, onUpdate, hasRoot }) {
  let picking = false;
  let browser = null;

  async function pick() {
    picking = true;
    onUpdate(null);
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
    if (result.status === "selected" && (await add(result.path))) return;
    if (result.status === "unavailable") return openBrowser();
    if (result.error)
      onNotify(
        result.error.status === 409
          ? "フォルダの選択画面はすでに開いています"
          : `追加できません: ${errorReason(result.error)}`,
      );
    onUpdate("add");
  }

  /** 追加する。失敗したら通知して false を返す（表示はそのまま）。 */
  async function add(path) {
    try {
      const result = await api.addRoot(path);
      onNotify(
        hasRoot(result.root.id)
          ? `${result.root.name} はすでに登録されています`
          : `${result.root.name} を追加しました`,
      );
    } catch (error) {
      onNotify(`追加できません: ${errorReason(error)}`);
      return false;
    }
    browser = null;
    await onAdded();
    return true;
  }

  async function openBrowser(path) {
    try {
      browser = await api.browse(path);
    } catch (error) {
      onNotify(errorReason(error));
    }
    onUpdate(browser ? "browser" : "add");
  }

  return {
    get picking() {
      return picking;
    },
    get browser() {
      return browser;
    },
    pick,
    add,
    openBrowser,
    closeBrowser() {
      browser = null;
      onUpdate("add");
    },
    reset() {
      browser = null;
    },
  };
}
