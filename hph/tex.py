r"""LaTeX ファイルの解析と PDF へのコンパイル。

- エンジンはプリアンブルとマジックコメントから推定する（設定で固定も可能）。
- 生成物はソース内容のハッシュをキーにキャッシュし、同じ内容なら再コンパイルしない。
- `\\write18`（シェルエスケープ）は常に無効で実行する。
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config

#: プリアンブル判定のために読み込む先頭バイト数。
PREAMBLE_BYTES = 8192
#: エラー時に返すログの末尾行数。
LOG_TAIL_LINES = 80
#: PDF の終端マーカーを探す末尾バイト数。
PDF_TRAILER_BYTES = 2048
#: フォント未検出時に読み込ませる代替定義（LuaTeX 専用）。
FONT_FALLBACK_LUA = Path(__file__).parent / "texfont.lua"

_MAGIC_RE = re.compile(
    r"^\s*%+\s*!\s*TE?X\s+(?:TS-)?program\s*=\s*([A-Za-z0-9_+-]+)", re.IGNORECASE | re.MULTILINE
)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_DOCUMENTCLASS_RE = re.compile(r"^\s*\\document(class|style)", re.MULTILINE)
#: fontspec が「そのフォントが見つからない」と言っているか。
# ログは 80 桁で折り返され、途中に "(fontspec)" の字下げが挟まる。
_FONT_MISSING_RE = re.compile(r"Package fontspec Error:.{0,400}?cannot be.{0,60}?found", re.DOTALL)
#: 外部コマンドの実行（shell-escape）が無いために失敗しているか。
_SHELL_ESCAPE_RE = re.compile(r"is unavailable or disabled|--?shell-escape", re.IGNORECASE)
#: `\input{...}` にそのまま埋め込んでも安全なファイル名。
_TEX_SAFE_NAME_RE = re.compile(r"^[^\\{}$&#^_~%\s\"]+$")


@dataclass(frozen=True)
class Engine:
    """LaTeX エンジンの定義。"""

    name: str
    command: str
    #: latexmk に渡すモードフラグ（latexmk が使えるときに利用する）。
    latexmk_flag: str | None = None
    #: True の場合、DVI を経由するので dvipdfmx が別途必要。
    via_dvi: bool = False


ENGINES: dict[str, Engine] = {
    "pdflatex": Engine("pdflatex", "pdflatex", "-pdf"),
    "xelatex": Engine("xelatex", "xelatex", "-pdfxe"),
    "lualatex": Engine("lualatex", "lualatex", "-pdflua"),
    "uplatex": Engine("uplatex", "uplatex", None, via_dvi=True),
    "platex": Engine("platex", "platex", None, via_dvi=True),
    "tectonic": Engine("tectonic", "tectonic"),
}

#: ヒントが無いときに試す順番。
FALLBACK_ORDER = ("pdflatex", "lualatex", "xelatex", "tectonic", "uplatex", "platex")

#: プリアンブルのキーワード → 優先エンジン。上から順に判定する。
PREAMBLE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\\usepackage(\[[^\]]*\])?\{luatexja", re.IGNORECASE), "lualatex"),
    (re.compile(r"\\documentclass(\[[^\]]*\])?\{ltj", re.IGNORECASE), "lualatex"),
    (re.compile(r"\\usepackage(\[[^\]]*\])?\{(xeCJK|zxjatype)", re.IGNORECASE), "xelatex"),
    (re.compile(r"\\usepackage(\[[^\]]*\])?\{fontspec", re.IGNORECASE), "xelatex"),
    (re.compile(r"\\documentclass(\[[^\]]*\])?\{u?(js|j|t)(article|book|report)", re.IGNORECASE), "uplatex"),
    (re.compile(r"\\usepackage(\[[^\]]*\])?\{(pxjahyper|otf|zxjafont)", re.IGNORECASE), "uplatex"),
)


@dataclass
class CompileResult:
    """コンパイル結果。`status` は ok / error / unavailable のいずれか。"""

    status: str
    message: str = ""
    engine: str | None = None
    pdf_path: Path | None = None
    log: str = ""
    cached: bool = False
    duration_ms: float = 0.0
    fingerprint: str = ""

    def to_json(self) -> dict[str, object]:
        """API レスポンス用の辞書へ変換する。"""
        return {
            "status": self.status,
            "message": self.message,
            "engine": self.engine,
            "log": self.log,
            "cached": self.cached,
            "durationMs": round(self.duration_ms, 1),
            "fingerprint": self.fingerprint,
        }


# ----------------------------------------------------------------------
# エンジンの検出と選択
# ----------------------------------------------------------------------
def available_engines() -> dict[str, str]:
    """PATH 上で見つかった LaTeX エンジン名 → 実行ファイルパス。"""
    found: dict[str, str] = {}
    for name, engine in ENGINES.items():
        path = shutil.which(engine.command)
        if path:
            found[name] = path
    return found


def has_latexmk() -> bool:
    """latexmk が使えるか。"""
    return shutil.which("latexmk") is not None


def has_dvipdfmx() -> bool:
    """dvipdfmx が使えるか（platex / uplatex に必要）。"""
    return shutil.which("dvipdfmx") is not None


def _strip_comments(text: str) -> str:
    r"""行コメントを取り除く（`\%` はコメントではない）。"""
    return re.sub(r"(?<!\\)%.*", "", text)


def read_preamble(path: Path, limit: int = PREAMBLE_BYTES) -> str:
    """先頭部分をテキストとして読む（判定用なので厳密なデコードは行わない）。"""
    try:
        with path.open("rb") as fh:
            return fh.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def choose_engine(source_head: str, available: dict[str, str], configured: str = "auto") -> Engine | None:
    """マジックコメント → プリアンブル → 既定順の優先度でエンジンを選ぶ。"""
    if configured and configured != "auto":
        engine = ENGINES.get(configured)
        if engine and configured in available:
            return engine
        return None

    magic = _MAGIC_RE.search(source_head)
    if magic:
        wanted = magic.group(1).lower()
        if wanted in available:
            return ENGINES[wanted]

    for pattern, name in PREAMBLE_HINTS:
        if pattern.search(source_head) and name in available:
            engine = ENGINES[name]
            if engine.via_dvi and not has_dvipdfmx():
                continue
            return engine

    # CJK を含むのに日本語向けパッケージが無い場合は、UTF-8 をそのまま扱える方を優先する。
    if _CJK_RE.search(source_head):
        for name in ("lualatex", "xelatex"):
            if name in available:
                return ENGINES[name]

    for name in FALLBACK_ORDER:
        if name in available:
            engine = ENGINES[name]
            if engine.via_dvi and not has_dvipdfmx():
                continue
            return engine
    return None


# ----------------------------------------------------------------------
# コンパイル
# ----------------------------------------------------------------------
def fingerprint_for(source: bytes, engine_name: str) -> str:
    """ソース内容とエンジンからキャッシュキーを作る。"""
    digest = hashlib.sha256()
    digest.update(engine_name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(source)
    return digest.hexdigest()[:16]


def cache_root(config: Config) -> Path:
    """PDF キャッシュのルートディレクトリ。"""
    return Path(config.tex_cache_dir).expanduser()


def compile_tex(
    path: Path, config: Config, *, force: bool = False, font_fallback: bool = False
) -> CompileResult:
    r"""`.tex` を PDF へコンパイルする（ブロッキング。呼び出し側でスレッドに逃がす）。

    `font_fallback` は内部用。フォント未検出で失敗したときの再試行で立てる。
    """
    started = time.perf_counter()
    if not config.tex_enabled:
        return CompileResult(status="unavailable", message="TeX プレビューは設定で無効になっています")

    try:
        source = path.read_bytes()
    except OSError as exc:
        return CompileResult(status="error", message=f"ファイルを読み取れません: {exc}")

    sibling = _sibling_pdf(path, config)
    if sibling is not None:
        return CompileResult(
            status="ok",
            message="同じ場所にある PDF を表示しています",
            pdf_path=sibling,
            cached=True,
            duration_ms=(time.perf_counter() - started) * 1000,
            fingerprint=f"sibling-{int(sibling.stat().st_mtime)}",
        )

    head_text = source[:PREAMBLE_BYTES].decode("utf-8", errors="replace")
    if not _DOCUMENTCLASS_RE.search(_strip_comments(head_text)):
        # \input で読み込まれる断片は単体ではコンパイルできない。ソース表示へ回す。
        return CompileResult(
            status="fragment",
            message=(
                "\\documentclass が無いため、単体ではコンパイルできません"
                "（他の .tex から読み込まれる断片と判断しました）"
            ),
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    available = available_engines()
    if not available:
        return CompileResult(
            status="unavailable",
            message=(
                "LaTeX エンジンが見つかりません。pdflatex / xelatex / lualatex / tectonic の"
                "いずれかを導入すると PDF プレビューが有効になります"
            ),
        )
    engine = choose_engine(head_text, available, config.tex_engine)
    if engine is None:
        return CompileResult(
            status="unavailable",
            message=(
                f"指定されたエンジン '{config.tex_engine}' が見つかりません"
                f"（利用可能: {', '.join(sorted(available))}）"
            ),
        )

    fingerprint = fingerprint_for(source, engine.name)
    out_dir = cache_root(config) / fingerprint
    pdf_path = out_dir / f"{path.stem}.pdf"
    # 過去に壊れた PDF が残っていることがあるので、完全なものだけキャッシュとして使う。
    if not force and _is_complete_pdf(pdf_path):
        os.utime(out_dir, None)  # LRU 用にアクセス時刻を更新する
        return CompileResult(
            status="ok",
            engine=engine.name,
            pdf_path=pdf_path,
            cached=True,
            duration_ms=(time.perf_counter() - started) * 1000,
            fingerprint=fingerprint,
        )

    # 前回の生成物が残っているか。失敗したときに「やり直す価値があるか」の判断に使う。
    had_previous_output = out_dir.is_dir() and any(out_dir.iterdir())
    if force:
        # latexmk は前回の .fdb_latexmk を見て「更新不要」と判断するため、作り直す。
        shutil.rmtree(out_dir, ignore_errors=True)
        had_previous_output = False
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CompileResult(status="error", message=f"キャッシュディレクトリを作れません: {exc}")

    log_parts: list[str] = []
    exit_code = 0
    for command in _build_commands(engine, path, out_dir, config, font_fallback=font_fallback):
        completed = _run(command, cwd=path.parent, timeout=config.tex_timeout_seconds)
        if completed is None:
            # 途中で打ち切られた生成物を残すと、次回それを読み込んで壊れる。
            _discard_output(out_dir)
            return CompileResult(
                status="error",
                engine=engine.name,
                message=f"コンパイルが {config.tex_timeout_seconds:.0f} 秒で終わりませんでした",
                log="\n".join(log_parts)[-8000:],
                duration_ms=(time.perf_counter() - started) * 1000,
                fingerprint=fingerprint,
            )
        exit_code, output = completed
        log_parts.append(output)
        if exit_code != 0:
            break

    log = _read_log(out_dir / f"{path.stem}.log") or "\n".join(log_parts)
    duration = (time.perf_counter() - started) * 1000
    # 終了コードだけでは判断しない。makeindex / bibtex など補助ツールの失敗で
    # latexmk が非ゼロを返しても、PDF 自体は完成していることがある。
    if not _is_complete_pdf(pdf_path):
        _discard_output(out_dir)
        if had_previous_output:
            # 前回の中断で壊れた .aux などが残っていた可能性がある。
            # 生成物を捨てたうえで、クリーンな状態から一度だけやり直す。
            return compile_tex(path, config, force=True)
        if (
            not font_fallback
            and _FONT_MISSING_RE.search(log)
            and _can_use_font_fallback(engine, path, config)
        ):
            # 手元に無いフォントを要求している。代替フォントへ読み替えて一度だけやり直す。
            retried = compile_tex(path, config, force=True, font_fallback=True)
            if retried.status == "ok":
                retried.message = (
                    "この環境に無いフォントを、代替フォントに置き換えて表示しています"
                    "（見た目が元の指定と異なります）"
                )
            return retried
        message = "PDF を生成できませんでした（コンパイルが失敗しました）"
        if _SHELL_ESCAPE_RE.search(log):
            message = (
                "外部コマンドの実行を必要とするパッケージ（minted など）が使われています。"
                "安全のためシェルエスケープを禁止しているため、このファイルはコンパイルできません"
            )
        elif pdf_path.name in log and "Fatal error occurred" not in log and exit_code != 0:
            message = "PDF を最後まで書き出せませんでした（コンパイルが中断された可能性があります）"
        return CompileResult(
            status="error",
            engine=engine.name,
            message=message,
            log=_tail(log),
            duration_ms=duration,
            fingerprint=fingerprint,
        )

    _prune_cache(cache_root(config), config.tex_cache_limit)
    incomplete = exit_code != 0
    return CompileResult(
        status="ok",
        engine=engine.name,
        message=(
            "PDF は生成できましたが、索引や参考文献などの補助処理が完了していません"
            "（相互参照が古いままの可能性があります）"
            if incomplete
            else ""
        ),
        pdf_path=pdf_path,
        log=_tail(log) if incomplete or _has_warnings(log) else "",
        duration_ms=duration,
        fingerprint=fingerprint,
    )


def cached_pdf(path: Path, config: Config, fingerprint: str) -> Path | None:
    """フィンガープリントからキャッシュ済み PDF を引く。"""
    if fingerprint.startswith("sibling-"):
        sibling = path.with_suffix(".pdf")
        return sibling if sibling.is_file() else None
    if not re.fullmatch(r"[0-9a-f]{4,64}", fingerprint):
        return None
    candidate = cache_root(config) / fingerprint / f"{path.stem}.pdf"
    return candidate if candidate.is_file() else None


# ----------------------------------------------------------------------
# 内部ヘルパー
# ----------------------------------------------------------------------
def _sibling_pdf(path: Path, config: Config) -> Path | None:
    """`.tex` と同じ場所にある、より新しい PDF があればそれを使う。"""
    if not config.tex_use_sibling_pdf:
        return None
    sibling = path.with_suffix(".pdf")
    try:
        if sibling.is_file() and sibling.stat().st_mtime >= path.stat().st_mtime:
            return sibling
    except OSError:
        return None
    return None


def _build_commands(
    engine: Engine, tex: Path, out_dir: Path, config: Config, *, font_fallback: bool = False
) -> list[list[str]]:
    """実行するコマンド列を組み立てる。

    `font_fallback` が真なら、代替フォント定義を読み込ませてから対象を処理する。
    このときは latexmk を経由しない（latexmk 経由では Lua のフックが効かないため）。
    """
    name = tex.name
    out = str(out_dir)
    if engine.name == "tectonic":
        return [[engine.command, "--outdir", out, "--keep-logs", "--print", name]]

    common = [
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",  # \write18 は常に禁止
        f"-output-directory={out}",
    ]
    if font_fallback:
        argument = f"{_font_fallback_directive()}\\input{{{name}}}"
        return [
            [engine.command, *common, f"-jobname={tex.stem}", argument]
            for _ in range(config.tex_max_passes)
        ]

    if engine.via_dvi:
        passes = [[engine.command, *common, name] for _ in range(config.tex_max_passes)]
        dvi = str(out_dir / f"{tex.stem}.dvi")
        passes.append(["dvipdfmx", "-o", str(out_dir / f"{tex.stem}.pdf"), dvi])
        return passes

    if config.tex_use_latexmk and has_latexmk() and engine.latexmk_flag:
        runner = f"{engine.command} -no-shell-escape -interaction=nonstopmode -file-line-error %O %S"
        return [
            [
                "latexmk",
                engine.latexmk_flag,
                f"-{engine.command}={runner}",
                "-halt-on-error",
                f"-outdir={out}",
                name,
            ]
        ]
    return [[engine.command, *common, name] for _ in range(config.tex_max_passes)]


def _run(command: list[str], *, cwd: Path, timeout: float) -> tuple[int, str] | None:
    """コマンドを実行し、(終了コード, 標準出力＋標準エラー) を返す。タイムアウト時は None。"""
    # 対象ディレクトリの外へ書き出さない／シェルエスケープを使わせない。
    env = {**os.environ, "openout_any": "p", "shell_escape": "f"}
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        return 1, f"{command[0]}: {exc}"
    return completed.returncode, (completed.stdout + completed.stderr).decode("utf-8", errors="replace")


def _font_fallback_directive() -> str:
    """代替フォント定義を読み込ませる TeX コード。"""
    return f"\\directlua{{dofile[[{FONT_FALLBACK_LUA}]]}}"


def _can_use_font_fallback(engine: Engine, tex: Path, config: Config) -> bool:
    """フォント代替を注入できる条件がそろっているか。

    LuaTeX 専用で、ファイル名とスクリプトのパスを TeX コードへ安全に埋め込める
    ときだけ有効にする（埋め込めない名前なら手を出さない）。
    """
    if not config.tex_font_fallback or engine.name != "lualatex":
        return False
    if not FONT_FALLBACK_LUA.is_file() or "]]" in str(FONT_FALLBACK_LUA):
        return False
    return bool(_TEX_SAFE_NAME_RE.fullmatch(tex.name))


def _is_complete_pdf(pdf_path: Path) -> bool:
    """PDF が最後まで書き出されているか（`%PDF` で始まり `%%EOF` で終わるか）。

    LuaTeX などは異常終了時にも書きかけの PDF を残す。終了コードだけを見ると、
    補助ツールが失敗しただけで PDF は完成しているケースまで失敗扱いになるため、
    ファイル自体の完全性で判定する。
    """
    try:
        with pdf_path.open("rb") as fh:
            if fh.read(5) != b"%PDF-":
                return False
            fh.seek(max(0, pdf_path.stat().st_size - PDF_TRAILER_BYTES))
            return b"%%EOF" in fh.read()
    except OSError:
        return False


def _discard_output(out_dir: Path) -> None:
    """失敗時に生成物をまとめて捨てる。

    書きかけの `.aux` / `.toc` が残ると、次回のコンパイルがそれを読み込んで
    `Runaway argument?` などで失敗し続けるため、ディレクトリごと作り直す。
    """
    with contextlib.suppress(OSError):  # pragma: no cover - 消せなくても致命的ではない
        shutil.rmtree(out_dir, ignore_errors=True)


def _read_log(log_path: Path) -> str:
    """LaTeX のログファイルを読む（無ければ空文字）。"""
    try:
        return log_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _tail(text: str, lines: int = LOG_TAIL_LINES) -> str:
    """ログの末尾だけを返す。エラー行があればその周辺を優先する。"""
    rows = text.splitlines()
    for index, row in enumerate(rows):
        if row.startswith("!") or "Fatal error occurred" in row or re.match(r"^.+\.[A-Za-z]+:\d+:", row):
            return "\n".join(rows[max(0, index - 5) : index + lines])
    return "\n".join(rows[-lines:])


def _has_warnings(log: str) -> bool:
    """未定義参照など、利用者に伝える価値がある警告を含むか。"""
    return "LaTeX Warning" in log or "Overfull" in log or "Underfull" in log


def _prune_cache(root: Path, limit: int) -> None:
    """キャッシュディレクトリを新しい順に `limit` 件だけ残す。"""
    try:
        entries = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return
    if len(entries) <= limit:
        return
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in entries[limit:]:
        shutil.rmtree(stale, ignore_errors=True)
