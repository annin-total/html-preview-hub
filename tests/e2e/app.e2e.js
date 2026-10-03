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
// 並び順は環境（ファイルの作成時刻）で変わるため、開くカードはタイトルで指定する
const HTML_CARD = ".card .card__file >> text=コンポーネントカタログ";
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
  await page.click(HTML_CARD);
  await page.locator("#stage iframe:visible").first().waitFor();
  await page.click(".crumbs"); // フォーカスをアプリ側へ（iframe 内に入れない）
  await page.keyboard.press("f");
  await page.waitForTimeout(1200);
  const favLabel = await page.textContent("#favoritesLabel");
  assert(
    favLabel.includes("(1)"),
    "favorite count should be 1, got " + favLabel,
  );
  // 修飾キー付き（ブラウザのショートカット）では反応しない
  await page.keyboard.press("Control+f");
  await page.waitForTimeout(1200);
  assert(
    (await page.textContent("#favoritesLabel")).includes("(1)"),
    "Ctrl/⌘ + f must not toggle favorite",
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

  // 11. 設定: 共通の除外条件の追加・削除でカードが増減する
  const folderCard = (name) =>
    page.locator(`.card[data-folder-id$=":${name}"]`);
  await page.goto(`${BASE}/#/`, { waitUntil: "load" });
  await page.fill("#homeSearch", "");
  await folderCard("scratch").waitFor();
  await page.click("#settingsBtn");
  const excludeSection = page.locator('section[aria-labelledby="secExclude"]');
  await excludeSection.locator('input[aria-label="名前"]').fill("scratch");
  await excludeSection.locator(".rule-form .pill").click();
  await folderCard("scratch").waitFor({ state: "detached" });
  await excludeSection
    .locator(
      '.rule__remove[aria-label="「フォルダ名が「scratch」と一致する」を削除"]',
    )
    .click();
  await folderCard("scratch").waitFor();
  await excludeSection.locator(".rule-empty").waitFor();

  // 12. 設定: 種類のチェックでカードが増減し、最後の 1 つは外せない
  const latex = page.locator('label.check:has-text("LaTeX") input');
  const html = page.locator('label.check:has-text("HTML") input');
  await latex.uncheck();
  await folderCard("tex").waitFor({ state: "detached" });
  assert(await html.isDisabled(), "最後の 1 つ（HTML）は外せない");
  await latex.check();
  await folderCard("tex").waitFor();
  assert(!(await html.isDisabled()), "2 つともオンなら外せる");

  // 13. 設定: 選択画面で選んだフォルダが追加される（API は差し替える）
  const pickWith = async (status, body) => {
    await page.unroute("**/api/pick-folder");
    await page.route("**/api/pick-folder", (route) =>
      route.fulfill({ status, json: body }),
    );
  };
  const addFolderBtn = page.locator(
    'section[aria-labelledby="secRoots"] .section-head .pill',
  );
  await pickWith(200, { status: "selected", path: __dirname });
  await addFolderBtn.click();
  const e2eRow = page.locator(".root-row", {
    has: page.locator(".root-row__name", { hasText: /^e2e$/ }),
  });
  await e2eRow.waitFor();
  assert.equal(await e2eRow.locator(".root-row__count").textContent(), "0 件");
  await e2eRow.locator('button[aria-label="e2e を対象から削除"]').click();
  await e2eRow.locator(".root-row__confirm .chip--danger").click();
  await e2eRow.waitFor({ state: "detached" });

  // 14. 設定: 選択画面が使えないとき・403 のときはアプリ内の一覧に切り替わる
  for (const [status, body] of [
    [200, { status: "unavailable", message: "x" }],
    [403, { error: "x" }],
  ]) {
    await pickWith(status, body);
    await addFolderBtn.click();
    await page.locator(".browser .browser__note").waitFor();
    assert(
      await page.evaluate(() =>
        document.activeElement.classList.contains("browser__item"),
      ),
      "一覧の最初の行にフォーカスが移る",
    );
    await page.click(".browser__foot .chip");
    await page.locator(".browser").waitFor({ state: "detached" });
  }
  await page.unroute("**/api/pick-folder");
  await page.keyboard.press("Escape");

  console.log("E2E OK / console errors:", errors);
  await browser.close();
})().catch((e) => {
  console.error("E2E FAILED:", e.message);
  process.exit(1);
});
