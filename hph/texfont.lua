-- 手元に無いフォントを、TeX Live 同梱の代替フォントへ読み替える（LuaTeX 専用）。
--
-- luaotfload が「解決できなかった」ときだけ介入するので、フォントが実在する環境では
-- 何もしない。html-preview-hub は、フォント未検出でコンパイルが失敗したときにだけ
-- このファイルを読み込んで再試行する。

--- 代替表: 正規化した要求名 → TeX Live に同梱されているフォント名。
local SUBSTITUTES = {
  ["noto serif cjk jp"] = "HaranoAjiMincho-Regular",
  ["noto serif cjk jp bold"] = "HaranoAjiMincho-Bold",
  ["noto serif cjk jp black"] = "HaranoAjiMincho-Heavy",
  ["noto serif cjk jp light"] = "HaranoAjiMincho-Light",
  ["noto sans cjk jp"] = "HaranoAjiGothic-Regular",
  ["noto sans cjk jp bold"] = "HaranoAjiGothic-Bold",
  ["noto sans cjk jp medium"] = "HaranoAjiGothic-Medium",
  ["noto sans cjk jp light"] = "HaranoAjiGothic-Light",
  ["noto sans mono cjk jp"] = "HaranoAjiGothic-Regular",
  ["noto sans cjk sc"] = "HaranoAjiGothic-Regular",
  ["noto sans cjk tc"] = "HaranoAjiGothic-Regular",
  ["noto sans cjk kr"] = "HaranoAjiGothic-Regular",
  ["noto serif jp"] = "HaranoAjiMincho-Regular",
  ["noto sans jp"] = "HaranoAjiGothic-Regular",
  ["ipamincho"] = "HaranoAjiMincho-Regular",
  ["ipaexmincho"] = "HaranoAjiMincho-Regular",
  ["ipagothic"] = "HaranoAjiGothic-Regular",
  ["ipaexgothic"] = "HaranoAjiGothic-Regular",
  ["hiragino mincho pron"] = "HaranoAjiMincho-Regular",
  ["hiragino kaku gothic pron"] = "HaranoAjiGothic-Regular",
  ["yu mincho"] = "HaranoAjiMincho-Regular",
  ["yu gothic"] = "HaranoAjiGothic-Regular",
  ["ms mincho"] = "HaranoAjiMincho-Regular",
  ["ms gothic"] = "HaranoAjiGothic-Regular",
  -- 欧文でよく使われるが TeX Live に無いもの
  ["poppins"] = "TeX Gyre Heros",
  ["inter"] = "TeX Gyre Heros",
  ["roboto"] = "TeX Gyre Heros",
  ["lato"] = "TeX Gyre Heros",
  ["open sans"] = "TeX Gyre Heros",
  ["source han serif jp"] = "HaranoAjiMincho-Regular",
  ["source han sans jp"] = "HaranoAjiGothic-Regular",
}

--- 同じ内容を何度も出さないための記録。
local reported = {}

--- 置き換えた内容をログとターミナルへ 1 度だけ書く。
local function note(format, ...)
  local message = string.format(format, ...)
  if not reported[message] then
    reported[message] = true
    texio.write_nl("term and log", "[hph-font] " .. message)
  end
end

--- フォント名を比較用に正規化する（拡張子・記号・大小を落とす）。
local function normalise(name)
  local text = tostring(name or ""):lower():gsub("%.%w+$", "")
  text = text:gsub("[-_]+", " "):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
  return text
end

--- 末尾の語を落としながら代替表を引く（"poppins medium" が無ければ "poppins"）。
local function find_substitute(name)
  local key = normalise(name)
  while #key > 0 do
    if SUBSTITUTES[key] then
      return SUBSTITUTES[key]
    end
    local shorter = key:match("^(.*) %S+$")
    if not shorter then
      return nil
    end
    key = shorter
  end
end

--- パス指定からファイル名だけを取り出す。
local function basename(value)
  return (tostring(value or ""):gsub(".*[/\\]", ""))
end

local resolve_by_name = luaotfload.resolvers.name

--- 要求名を差し替えて、本来の名前解決をやり直す。
local function retry_with(spec, wanted)
  local original = spec.name
  spec.name = wanted
  local a, b, c = resolve_by_name(spec)
  if not a then
    spec.name = original
  end
  return a, b, c
end

-- 名前で指定された場合: 解決できなかったときだけ代替表を見る。
luaotfload.resolvers.name = function(spec)
  local a, b, c = resolve_by_name(spec)
  if a then
    return a, b, c
  end
  local wanted = find_substitute(spec.name) or find_substitute(basename(spec.name))
  if not wanted then
    note("見つかりません: %s（代替なし）", tostring(spec.name))
    return
  end
  note("代替: %s -> %s", tostring(spec.name), wanted)
  return retry_with(spec, wanted)
end

-- パス／ファイル名で指定された場合: 実在しない絶対パス（他 OS 前提の決め打ちなど）を
-- ファイル名だけで引き直す。
for _, key in ipairs({ "path", "file" }) do
  local original = luaotfload.resolvers[key]
  luaotfload.resolvers[key] = function(spec)
    local a, b, c = original(spec)
    if a then
      return a, b, c
    end
    local base = basename(spec.name)
    local wanted = find_substitute(base) or base
    note("代替(%s 指定): %s -> %s", key, tostring(spec.name), wanted)
    return retry_with(spec, (wanted:gsub("%.%w+$", "")))
  end
end

-- luaotfload が既に取り込んだ解決関数を捨てて、上で差し替えたものを使わせる。
for _, key in ipairs({ "name", "path", "file", "anon" }) do
  fonts.definers.resolvers[key] = nil
end
