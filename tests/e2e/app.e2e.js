/**
 * ブラウザ操作の E2E テスト（任意実行）。
 *
 *   1) 別ターミナルでアプリを起動:  python -m hph ./sample-docs --port 8899 --no-browser
 *   2) npm install playwright
 *   3) node tests/e2e/app.e2e.js
 *
 * BASE_URL 環境変数で対象 URL を、CHROMIUM_PATH で Chromium の実行パスを差し替えられる。
 */
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "http://127.0.0.1:8899";
const assert = require("assert");
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const page = await browser.newPage({
    viewport: { width: 1400, height: 900 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  // 0. 前回の実行で残った状態をリセット（テストを冪等にする）
  const base = `${BASE}`;
  const state = (await (await page.request.get(base + "/api/index")).json())
    .userState;
  for (const id of state.favorites)
    await page.request.post(base + "/api/user/favorites", {
      data: { fileId: id },
    });
  for (const id of state.hiddenFolders)
    await page.request.post(base + "/api/user/hidden", {
      data: { folderId: id },
    });

  await page.goto(`${BASE}/#/`, { waitUntil: "load" });
  await page.waitForSelector(".card");

  // 1. お気に入り: プレビューを開いて f
  await page.click(".card .card__file");
  await page.locator("#stage iframe:visible").first().waitFor();
  await page.click(".crumbs"); // フォーカスをアプリ側へ（iframe 内に入れない）
  await page.keyboard.press("f");
  await page.waitForTimeout(1200);
  const favLabel = await page.textContent("#favoritesLabel");
  assert(
    favLabel.includes("(1)"),
    "favorite count should be 1, got " + favLabel,
  );

  // 2. Esc でホームへ戻る
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  assert.equal(await page.getAttribute("#app", "data-view"), "home");

  // 3. お気に入り絞り込み
  await page.click("#favoritesToggle");
  await page.waitForTimeout(300);
  assert.equal(
    await page.locator(".card").count(),
    1,
    "favorites filter should show one card",
  );
  await page.click("#favoritesToggle");
  await page.waitForTimeout(200);

  // 4. 右クリックでフォルダ非表示
  const before = await page.locator(".card").count();
  await page.locator(".card").first().click({ button: "right" });
  await page.waitForTimeout(400);
  const after = await page.locator(".card").count();
  assert.equal(
    after,
    before - 1,
    `hidden folder should disappear (${before} -> ${after})`,
  );
  const hiddenChip = await page.textContent("#hiddenChip");
  assert(
    hiddenChip.includes("(1)"),
    "hidden chip should count 1: " + hiddenChip,
  );
  await page.click("#hiddenChip");
  await page.waitForTimeout(300);
  assert.equal(
    await page.locator(".card").count(),
    1,
    "hidden view shows only hidden folders",
  );
  await page.locator(".card").first().click({ button: "right" }); // 元に戻す
  await page.waitForTimeout(500);
  // 非表示が 0 件になったら自動で通常表示へ戻る
  assert.equal(
    await page.locator("#hiddenChip").isVisible(),
    false,
    "hidden chip should auto-hide",
  );
  assert.equal(
    await page.locator(".card").count(),
    before,
    "all folders visible again",
  );

  // 5. 壊れた HTML でもクラッシュしない
  await page.fill("#homeSearch", "broken.html");
  await page.waitForTimeout(300);
  await page.click(".card .card__file");
  await page.waitForTimeout(800);
  assert.equal(
    await page.locator("#previewError").isVisible(),
    false,
    "broken html should still preview",
  );

  // 6. 存在しないファイル ID → エラー表示にならずホームへ
  await page.goto(`${BASE}/#/f/nonexistent%3Afile.html`, { waitUntil: "load" });
  await page.waitForTimeout(700);
  assert.equal(await page.getAttribute("#app", "data-view"), "home");

  // 7. ソース表示
  await page.click(".card .card__file");
  await page.locator("#stage iframe:visible").first().waitFor();
  await page.click("#sourceBtn");
  await page.waitForTimeout(500);
  assert(
    await page.locator("#previewSource").isVisible(),
    "source view should open",
  );
  const src = await page.textContent("#previewSource");
  assert(src.includes("<"), "source should contain markup");

  // 8. LaTeX: 断片ファイルはコンパイルせずソース表示へ回す
  await page.goto(`${BASE}/#/`, { waitUntil: "load" });
  await page.fill("#homeSearch", "macros");
  await page.waitForTimeout(400);
  if (await page.locator(".card .card__file").count()) {
    await page.click(".card .card__file");
    await page.waitForTimeout(1500);
    assert(
      await page.locator("#previewError").isVisible(),
      "fragment should show a notice",
    );
    await page.click("#previewError .box__actions .chip:last-child");
    await page.waitForTimeout(600);
    assert(
      await page.locator("#previewSource").isVisible(),
      "source should open from the notice",
    );
  }

  // 9. LaTeX: エンジンがある環境では PDF がプレビューされる
  const texStatus = await (
    await page.request.get(base + "/api/tex/status")
  ).json();
  if (texStatus.engines.length > 0) {
    await page.goto(`${BASE}/#/`, { waitUntil: "load" });
    await page.fill("#homeSearch", "Bilinear");
    await page.waitForTimeout(400);
    await page.click(".card .card__file");
    await page
      .locator('#stage iframe[src*="/api/tex/pdf"]:visible')
      .first()
      .waitFor({ timeout: 60000 });
    assert.equal(
      await page.locator("#previewError").isVisible(),
      false,
      "tex preview should not error",
    );
    assert.equal(await page.textContent("#reloadBtn"), "再コンパイル");
  } else {
    console.log("（LaTeX エンジンが無いため PDF プレビューの検証はスキップ）");
  }

  // 10. 表示名の切り替え（タイトル ⇔ ファイル名）
  await page.goto(`${BASE}/#/`, { waitUntil: "load" });
  await page.fill("#homeSearch", "components");
  await page.waitForTimeout(400);
  assert.equal(
    await page.textContent("#labelModeLabel"),
    "タイトル",
    "既定はタイトル表示",
  );
  const asTitle = await page.textContent(".card .card__file span");
  await page.click("#labelModeToggle");
  await page.waitForTimeout(300);
  assert.equal(await page.textContent("#labelModeLabel"), "ファイル名");
  const asName = await page.textContent(".card .card__file span");
  assert.equal(
    asName,
    "components.html",
    "カードがファイル名になる: " + asName,
  );
  assert.notEqual(asName, asTitle, "タイトルとファイル名で表示が変わる");
  // サイドバーにも同じ設定が効く
  await page.click(".card .card__file");
  await page.locator("#stage iframe:visible").first().waitFor();
  assert.equal(
    await page.textContent(".tree__row.is-active .tree__label"),
    asName,
    "サイドバーもファイル名",
  );
  await page.click("#labelModeToggle");
  await page.waitForTimeout(300);
  assert.equal(
    await page.textContent(".tree__row.is-active .tree__label"),
    asTitle,
    "サイドバーもタイトルへ戻る",
  );
  // ショートカット `t` でも切り替わる
  await page.click(".crumbs"); // フォーカスをアプリ側へ
  await page.keyboard.press("t");
  await page.waitForTimeout(300);
  assert.equal(
    await page.textContent("#labelModeLabel"),
    "ファイル名",
    "t キーで切り替わる",
  );
  await page.keyboard.press("t");
  await page.waitForTimeout(300);
  assert.equal(
    await page.textContent("#labelModeLabel"),
    "タイトル",
    "t キーで戻る",
  );

  console.log("E2E OK / console errors:", errors);
  await browser.close();
})().catch((e) => {
  console.error("E2E FAILED:", e.message);
  process.exit(1);
});
