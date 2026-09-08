"""スキャナとタイトル抽出の検証。"""

from __future__ import annotations

from pathlib import Path

from hph.config import Config
from hph.scanner import TitleCache, extract_tex_title, extract_title, kind_of, scan


def test_scan_collects_html_and_skips_ignored(config: Config) -> None:
    result = scan(config)
    rel_paths = {file.rel_path for file in result.files}
    assert rel_paths == {
        "alpha/index.html",
        "alpha/no-title.html",
        "beta/broken.html",
        "beta/paper.tex",
        "beta/fragment.tex",
    }
    assert {folder.rel_path for folder in result.folders} == {"alpha", "beta"}
    assert result.errors == []


def test_titles_fall_back_to_h1_then_filename(config: Config) -> None:
    titles = {file.rel_path: file.title for file in scan(config).files}
    assert titles["alpha/index.html"] == "アルファの概要"
    assert titles["alpha/no-title.html"] == "H1 から拾うタイトル"
    # 閉じタグが無い壊れたファイルでも例外にならず、何らかの表示名になる。
    assert titles["beta/broken.html"]


def test_extract_title_handles_unreadable_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.html"
    assert extract_title(missing, limit=1024, fallback="fallback") == "fallback"


def test_extract_title_honours_meta_charset(tmp_path: Path) -> None:
    path = tmp_path / "sjis.html"
    body = '<html><head><meta charset="shift_jis"><title>日本語タイトル</title></head></html>'
    path.write_bytes(body.encode("shift_jis"))
    assert extract_title(path, limit=4096, fallback="x") == "日本語タイトル"


def test_cache_avoids_rereading_unchanged_files(config: Config, tree: Path) -> None:
    cache = TitleCache()
    scan(config, cache)
    assert len(cache) == 5
    target = tree / "alpha" / "index.html"
    target.write_text("<title>更新後のタイトル</title>", encoding="utf-8")
    titles = {f.rel_path: f.title for f in scan(config, cache).files}
    assert titles["alpha/index.html"] == "更新後のタイトル"


def test_tex_titles_and_kinds(config: Config) -> None:
    files = {file.rel_path: file for file in scan(config).files}
    assert files["beta/paper.tex"].title == "テスト論文"
    assert files["beta/paper.tex"].kind == "tex"
    assert files["beta/fragment.tex"].title == "断片"
    assert files["alpha/index.html"].kind == "html"


def test_extract_tex_title_variants() -> None:
    assert extract_tex_title(r"\title{入れ子の {中身} も拾う}") == "入れ子の 中身 も拾う"
    assert extract_tex_title(r"\documentclass{article}\section*{節タイトル}") == "節タイトル"
    assert extract_tex_title("% 先頭コメントを使う\n\\documentclass{article}") == "先頭コメントを使う"
    assert extract_tex_title(r"\title{数式 $E=mc^2$ と \textbf{装飾}}") == "数式 E=mc^2 と 装飾"
    # タイトル系コマンドがコメント内にある場合は、コメント本文を見出しとして扱う。
    assert extract_tex_title(r"% \title{コメント内は無視する}") == "コメント内は無視する"


def test_kind_of() -> None:
    assert kind_of("a/b.TEX") == "tex"
    assert kind_of("a/b.html") == "html"
    assert kind_of("a/b.md") == "other"


def test_max_files_truncates(config: Config) -> None:
    config.max_files = 1
    result = scan(config)
    assert result.truncated is True
    assert len(result.files) == 1
