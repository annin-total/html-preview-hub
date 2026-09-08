r"""LaTeX ファイルの解析と PDF へのコンパイル。

- エンジンはプリアンブルとマジックコメントから推定する（設定で固定も可能）。
- 生成物はソース内容のハッシュをキーにキャッシュし、同じ内容なら再コンパイルしない。
- `\\write18`（シェルエスケープ）は常に無効で実行する。
"""

from __future__ import annotations

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

_MAGIC_RE = re.compile(
    r"^\s*%+\s*!\s*TE?X\s+(?:TS-)?program\s*=\s*([A-Za-z0-9_+-]+)", re.IGNORECASE | re.MULTILINE
)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_DOCUMENTCLASS_RE = re.compile(r"^\s*\\document(class|style)", re.MULTILINE)


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


def compile_tex(path: Path, config: Config, *, force: bool = False) -> CompileResult:
    r"""`.tex` を PDF へコンパイルする（ブロッキング。呼び出し側でスレッドに逃がす）。"""
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
    if pdf_path.is_file() and not force:
        os.utime(out_dir, None)  # LRU 用にアクセス時刻を更新する
        return CompileResult(
            status="ok",
            engine=engine.name,
            pdf_path=pdf_path,
            cached=True,
            duration_ms=(time.perf_counter() - started) * 1000,
            fingerprint=fingerprint,
        )

    if force:
        # latexmk は前回の .fdb_latexmk を見て「更新不要」と判断するため、作り直す。
        shutil.rmtree(out_dir, ignore_errors=True)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CompileResult(status="error", message=f"キャッシュディレクトリを作れません: {exc}")

    log_parts: list[str] = []
    failed = False
    for command in _build_commands(engine, path, out_dir, config):
        completed = _run(command, cwd=path.parent, timeout=config.tex_timeout_seconds)
        if completed is None:
            _discard_pdf(pdf_path)
            return CompileResult(
                status="error",
                engine=engine.name,
                message=f"コンパイルが {config.tex_timeout_seconds:.0f} 秒で終わりませんでした",
                log="\n".join(log_parts)[-8000:],
                duration_ms=(time.perf_counter() - started) * 1000,
                fingerprint=fingerprint,
            )
        returncode, output = completed
        log_parts.append(output)
        if returncode != 0:
            # エンジンが異常終了した場合、書きかけの壊れた PDF が残ることがある。
            failed = True
            break

    log = _read_log(out_dir / f"{path.stem}.log") or "\n".join(log_parts)
    duration = (time.perf_counter() - started) * 1000
    if failed or not pdf_path.is_file():
        _discard_pdf(pdf_path)
        return CompileResult(
            status="error",
            engine=engine.name,
            message="PDF を生成できませんでした（コンパイルが失敗しました）",
            log=_tail(log),
            duration_ms=duration,
            fingerprint=fingerprint,
        )

    _prune_cache(cache_root(config), config.tex_cache_limit)
    return CompileResult(
        status="ok",
        engine=engine.name,
        pdf_path=pdf_path,
        log=_tail(log) if _has_warnings(log) else "",
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


def _build_commands(engine: Engine, tex: Path, out_dir: Path, config: Config) -> list[list[str]]:
    """実行するコマンド列を組み立てる。"""
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


def _discard_pdf(pdf_path: Path) -> None:
    """失敗時に残った不完全な PDF を消す（次回それをキャッシュとして返さないため）。"""
    try:
        pdf_path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - 消せなくても致命的ではない
        pass


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
