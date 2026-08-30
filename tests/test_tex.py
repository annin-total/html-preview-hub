"""LaTeX のエンジン選択とコンパイル。

実際の TeX を必要としないよう、PDF とログを書くだけのスタブエンジンを PATH に置いて検証する。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hph.config import Config
from hph.tex import ENGINES, choose_engine, compile_tex


@pytest.fixture()
def tex_config(tmp_path: Path, install_tex_stub) -> Config:
    """スタブエンジンが最優先で見つかる設定。"""
    install_tex_stub()
    config = Config.from_dict({"tex_cache_dir": str(tmp_path / "cache")})
    config.tex_use_latexmk = False
    config.tex_max_passes = 1
    return config


def _write_tex(path: Path, body: str = "\\documentclass{article}\\begin{document}x\\end{document}") -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# エンジン選択
# ----------------------------------------------------------------------
def test_magic_comment_wins() -> None:
    available = {"pdflatex": "/x", "lualatex": "/y"}
    engine = choose_engine("% !TEX program = lualatex\n\\documentclass{article}", available)
    assert engine is ENGINES["lualatex"]


def test_magic_comment_falls_back_when_engine_missing() -> None:
    engine = choose_engine("% !TEX program = xelatex\n", {"pdflatex": "/x"})
    assert engine is ENGINES["pdflatex"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("\\documentclass{ltjsarticle}", "lualatex"),
        ("\\usepackage{luatexja}", "lualatex"),
        ("\\usepackage{xeCJK}", "xelatex"),
        ("\\usepackage{fontspec}", "xelatex"),
        ("\\documentclass[uplatex]{jsarticle}", "uplatex"),
        ("\\documentclass{article}", "pdflatex"),
    ],
)
def test_preamble_hints(source: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hph.tex.has_dvipdfmx", lambda: True)
    available = dict.fromkeys(("pdflatex", "xelatex", "lualatex", "uplatex"), "/x")
    assert choose_engine(source, available).name == expected


def test_cjk_without_japanese_package_prefers_unicode_engine() -> None:
    engine = choose_engine("\\documentclass{article}\n日本語の本文", {"pdflatex": "/x", "lualatex": "/y"})
    assert engine is ENGINES["lualatex"]


def test_uplatex_is_skipped_without_dvipdfmx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hph.tex.has_dvipdfmx", lambda: False)
    engine = choose_engine("\\documentclass{jsarticle}", {"uplatex": "/x", "pdflatex": "/y"})
    assert engine is ENGINES["pdflatex"]


def test_configured_engine_is_respected() -> None:
    assert choose_engine("", {"pdflatex": "/x"}, "pdflatex") is ENGINES["pdflatex"]
    assert choose_engine("", {"pdflatex": "/x"}, "xelatex") is None


# ----------------------------------------------------------------------
# コンパイル
# ----------------------------------------------------------------------
def test_compile_creates_pdf_and_caches(tmp_path: Path, tex_config: Config) -> None:
    tex = _write_tex(tmp_path / "doc.tex")
    first = compile_tex(tex, tex_config)
    assert first.status == "ok"
    assert first.pdf_path is not None and first.pdf_path.is_file()
    assert first.cached is False

    second = compile_tex(tex, tex_config)
    assert second.status == "ok"
    assert second.cached is True
    assert second.fingerprint == first.fingerprint


def test_force_recompiles(tmp_path: Path, tex_config: Config) -> None:
    tex = _write_tex(tmp_path / "doc.tex")
    compile_tex(tex, tex_config)
    forced = compile_tex(tex, tex_config, force=True)
    assert forced.status == "ok"
    assert forced.cached is False


def test_changed_source_gets_new_fingerprint(tmp_path: Path, tex_config: Config) -> None:
    tex = _write_tex(tmp_path / "doc.tex")
    first = compile_tex(tex, tex_config)
    _write_tex(tex, "\\documentclass{article}\\begin{document}updated\\end{document}")
    second = compile_tex(tex, tex_config)
    assert second.fingerprint != first.fingerprint
    assert second.cached is False


def test_compile_failure_returns_log(tmp_path: Path, install_tex_stub) -> None:
    install_tex_stub(body="exit 1", log="./doc.tex:3: Undefined control sequence.\\n")
    config = Config.from_dict({"tex_cache_dir": str(tmp_path / "cache")})
    config.tex_use_latexmk = False
    config.tex_max_passes = 1
    result = compile_tex(_write_tex(tmp_path / "doc.tex"), config)
    assert result.status == "error"
    assert "Undefined control sequence" in result.log


def test_fragment_is_reported_without_running_engine(tmp_path: Path, tex_config: Config) -> None:
    fragment = _write_tex(tmp_path / "part.tex", "\\section{断片}\n本文だけのファイル\n")
    result = compile_tex(fragment, tex_config)
    assert result.status == "fragment"
    assert result.pdf_path is None


def test_documentclass_in_comment_is_not_counted(tmp_path: Path, tex_config: Config) -> None:
    fragment = _write_tex(
        tmp_path / "part.tex", "% \\documentclass{article} と書いてあるだけ\n\\section{x}\n"
    )
    assert compile_tex(fragment, tex_config).status == "fragment"


def test_unavailable_without_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    config = Config.from_dict({"tex_cache_dir": str(tmp_path / "cache")})
    result = compile_tex(_write_tex(tmp_path / "doc.tex"), config)
    assert result.status == "unavailable"
    assert "LaTeX エンジン" in result.message


def test_disabled_by_config(tmp_path: Path, tex_config: Config) -> None:
    tex_config.tex_enabled = False
    assert compile_tex(_write_tex(tmp_path / "doc.tex"), tex_config).status == "unavailable"


def test_sibling_pdf_is_used_when_newer(tmp_path: Path, tex_config: Config) -> None:
    tex = _write_tex(tmp_path / "doc.tex")
    sibling = tmp_path / "doc.pdf"
    sibling.write_bytes(b"%PDF-1.4\n")
    os.utime(sibling, (tex.stat().st_mtime + 10, tex.stat().st_mtime + 10))
    result = compile_tex(tex, tex_config)
    assert result.status == "ok"
    assert result.pdf_path == sibling
    assert result.fingerprint.startswith("sibling-")


def test_sibling_pdf_ignored_when_disabled(tmp_path: Path, tex_config: Config) -> None:
    tex = _write_tex(tmp_path / "doc.tex")
    sibling = tmp_path / "doc.pdf"
    sibling.write_bytes(b"%PDF-1.4\n")
    os.utime(sibling, (tex.stat().st_mtime + 10, tex.stat().st_mtime + 10))
    tex_config.tex_use_sibling_pdf = False
    result = compile_tex(tex, tex_config)
    assert result.pdf_path != sibling


def test_timeout_is_reported(tmp_path: Path, install_tex_stub) -> None:
    install_tex_stub(body="sleep 5")
    config = Config.from_dict({"tex_cache_dir": str(tmp_path / "cache")})
    config.tex_use_latexmk = False
    config.tex_timeout_seconds = 0.5
    result = compile_tex(_write_tex(tmp_path / "doc.tex"), config)
    assert result.status == "error"
    assert "秒" in result.message


def test_cache_is_pruned(tmp_path: Path, tex_config: Config) -> None:
    tex_config.tex_cache_limit = 2
    for index in range(4):
        tex = _write_tex(
            tmp_path / "doc.tex", f"\\documentclass{{article}}\\begin{{document}}{index}\\end{{document}}"
        )
        compile_tex(tex, tex_config)
    cached = list((Path(tex_config.tex_cache_dir)).iterdir())
    assert len(cached) <= 2
