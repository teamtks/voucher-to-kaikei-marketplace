"""職員のPCを、最新のスキルが確実に読まれる形に移す(移行ツール・単体で動く)。

なぜ必要か:
  Claude Desktopは、プラグインとして入れたスキルを自分の管理する場所
  (%LOCALAPPDATA%\\Claude-Data\\...\\rpm\\...)に置き、そこから読む。そこは自動更新が
  一度も触れていない場所で、職員のClaudeは7月16日のSKILL.mdで動き続けていた。
  デスクトップのショートカットも、そこにある7月16日のランチャーを起動していた。
  自動更新と確認ツールはどちらも別の場所(.claude\\plugins\\cache)を見ており、
  「最新」と表示していたため、長く気づけなかった。

  正しく動いている開発用PCは、スキルを ~/.claude/skills/voucher-to-yayoi に置き、
  ショートカットもそこを指している。職員のPCを同じ形にする。

行うこと:
  1. GitHub上の最新版を取得する(内部の複製があればそれを最新にして使う。無ければ
     GitHubから直接ダウンロードする)
  2. ~/.claude/skills/voucher-to-yayoi に置く(Python実行環境(.venv)は残す)
     移行済みの印のファイルを置き、以後は自動更新がこの場所も最新に保つ
  3. デスクトップの「仕訳.TeamTKS」を、ここのランチャーを起動するように作り直す
     (スキルの外のPythonで起動する。中のPythonだと、自動更新がスキルを入れ替え
      られないため)
  4. アプリ管理の場所に残っている古いスキルを探して知らせる(消さない)

  開発用PCのように、手作業で置いたスキルが既にある場合は、上書きせずに止まる。
  職員のPCで置き換えてよい場合は --replace を付ける(元のスキルは消さずに
  ~/.claude/削除済み へ移す)。

使い方:
    python スキル移行.py             移行する
    python スキル移行.py --replace   手作業で置かれたスキルがあれば、退避して置き換える
    python スキル移行.py --check     調べるだけ(何も変更しない)

移行の後は、プラグインの画面で古い「Voucher to yayoi」を無効にし、ランチャーを
起動し直すこと(手順は最後に表示する)。
"""
import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

PLUGIN_NAME = "voucher-to-yayoi"
HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
TARGET = CLAUDE_DIR / "skills" / PLUGIN_NAME
MARK = ".teamtks-managed"
SHORTCUT_NAME = "仕訳.TeamTKS.lnk"
ZIP_URL = "https://codeload.github.com/teamtks/voucher-to-kaikei-marketplace/zip/refs/heads/main"
APP_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local"))) / "Claude-Data"
VENV_STASH = CLAUDE_DIR / ".venv-keep-migrate"
BACKUP_ROOT = CLAUDE_DIR / "削除済み"


def say(tag: str, message: str) -> None:
    print(f"  [{tag}] {message}")


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
    except OSError:
        return "(読めません)"


def find_marketplace_dir() -> "Path | None":
    """内部の複製を、名前ではなく中身で探す(登録の仕方で名前が変わるため)。"""
    root = CLAUDE_DIR / "plugins" / "marketplaces"
    if not root.is_dir():
        return None
    for d in sorted(root.iterdir()):
        if (d / ".git").is_dir() and (d / "plugins" / PLUGIN_NAME).is_dir():
            return d
    return None


def find_app_managed_copies() -> "list[Path]":
    """アプリが自分で管理している場所にある、このスキルのSKILL.mdを探す。"""
    if not APP_DATA_ROOT.is_dir():
        return []
    return sorted(p for p in APP_DATA_ROOT.rglob(f"skills/{PLUGIN_NAME}/SKILL.md") if p.is_file())


def latest_source(workdir: Path) -> "tuple[Path, str]":
    """最新版のスキルのフォルダと、その版を表す文字列を返す。取れなければSystemExit。"""
    mp = find_marketplace_dir()
    if mp is not None:
        if run(["git", "fetch", "origin"], cwd=mp).returncode != 0:
            raise SystemExit("  [中止] GitHubから取得できませんでした。ネットワークを確認してください。")
        # この複製は取得専用の写しで、利用者が編集する場所ではない。早送りできない
        # 状態でも確実に揃えるため、GitHub上の内容に合わせる。
        reset = run(["git", "reset", "--hard", "origin/main"], cwd=mp)
        if reset.returncode != 0:
            raise SystemExit(f"  [中止] 内部の複製を最新にできませんでした: {reset.stderr.strip()[:200]}")
        head = run(["git", "rev-parse", "HEAD"], cwd=mp).stdout.strip()
        src = mp / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME
        say("取得", f"内部の複製を最新にしました({head[:7]})")
        return src, head

    # 内部の複製が無いPC(アプリ管理の場所だけにスキルがあった場合など)
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=60) as r:
            data = r.read()
    except Exception as e:
        raise SystemExit(f"  [中止] GitHubからダウンロードできませんでした: {e}")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(workdir)
    found = list(workdir.glob(f"*/plugins/{PLUGIN_NAME}/skills/{PLUGIN_NAME}"))
    if not found:
        raise SystemExit("  [中止] ダウンロードした中にスキルが見つかりません。")
    say("取得", "GitHubから直接ダウンロードしました(このPCには内部の複製がありません)")
    # 版の印は「複製なし」。自動更新は内部の複製を元に動くため、このPCでは働かない
    return found[0], "zip"


def install(src: Path, head: str, replace_hand_placed: bool = False) -> None:
    """TARGETに最新版を置く。.venvは残す。

    手作業で置かれたスキル(移行の印が無いもの)があれば、既定では止まる。開発用
    PCではそれが作業中の本体だからである。職員のPCで置き換えてよい場合だけ
    replace_hand_placed を指定する。その場合も消さずに「削除済み」へ移して残す
    (利用者の運用ルール:削除せず「削除済み」フォルダへ移す)。
    """
    hand_placed = TARGET.exists() and not (TARGET / MARK).is_file()
    if hand_placed and not replace_hand_placed:
        raise SystemExit(
            f"  [中止] {TARGET} に、手作業で置かれたスキルがあります。上書きしません。\n"
            "         開発用のPCではこの状態が正常です。\n"
            "         職員のPCで置き換えてよい場合は、--replace を付けて実行し直してください\n"
            f"         (元のスキルは {BACKUP_ROOT} に移して残します)。"
        )

    venv = TARGET / "scripts" / ".venv"
    stashed = False
    if venv.is_dir():
        if VENV_STASH.exists():
            shutil.rmtree(VENV_STASH)
        venv.rename(VENV_STASH)
        stashed = True
    try:
        if TARGET.exists():
            if hand_placed:
                backup = BACKUP_ROOT / f"{PLUGIN_NAME}_{datetime.now():%Y%m%d_%H%M%S}"
                backup.parent.mkdir(parents=True, exist_ok=True)
                TARGET.rename(backup)
                say("退避", f"手作業で置かれていたスキルを移しました(消していません): {backup}")
            else:
                shutil.rmtree(TARGET)  # 以前この道具が置いた版(印あり)なので、入れ替えてよい
        shutil.copytree(src, TARGET, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    finally:
        if stashed:
            (TARGET / "scripts").mkdir(parents=True, exist_ok=True)
            VENV_STASH.rename(venv)
    (TARGET / MARK).write_text(head + "\n", encoding="utf-8")
    say("完了", f"最新版を置きました: {TARGET}")
    if stashed:
        say("完了", "Pythonの実行環境(.venv)はそのまま残しました")


def outside_pythonw() -> Path:
    """スキルの外にある pythonw.exe を探す。

    ランチャーをスキルの中のPython(.venv)で動かすと、自動更新がスキルを入れ替える
    とき、使用中のフォルダを動かせずに失敗する。
    """
    def usable(p: Path) -> bool:
        try:
            p = p.resolve()
            return p.is_file() and not p.is_relative_to(CLAUDE_DIR.resolve()) \
                and not (APP_DATA_ROOT.exists() and p.is_relative_to(APP_DATA_ROOT.resolve()))
        except (OSError, ValueError):
            return False

    candidates = [Path(sys.executable).with_name("pythonw.exe")]
    found = shutil.which("pythonw")
    if found:
        candidates.append(Path(found))
    for c in candidates:
        if usable(c):
            return c.resolve()
    raise SystemExit("  [中止] スキルの外にある pythonw.exe が見つかりません。")


def recreate_shortcut() -> Path:
    sys.path.insert(0, str(TARGET / "scripts"))
    from lib.desktop_shortcut import create_shortcut, desktop_dir  # 置いたばかりのスキルの部品

    scripts = TARGET / "scripts"
    path = create_shortcut(
        desktop_dir() / SHORTCUT_NAME,
        outside_pythonw(),
        arguments=f'"{scripts / "launcher.pyw"}"',
        working_directory=scripts,
        icon_path=scripts / "app_icon.ico",
        description="仕訳.TeamTKS(証憑仕訳処理ツール)",
    )
    say("完了", f"デスクトップの「仕訳.TeamTKS」を作り直しました: {path}")
    return path


def report_app_managed(reference: "str | None") -> "list[Path]":
    copies = find_app_managed_copies()
    if not copies:
        return []
    print()
    print("  アプリが管理している場所に、このスキルが残っています:")
    for p in copies:
        state = "最新" if reference and digest(p) == reference else "古い"
        print(f"    [{state}] {p.parent}")
    return copies


def main() -> int:
    parser = argparse.ArgumentParser(description="最新のスキルが確実に読まれる形に移す")
    parser.add_argument("--check", action="store_true", help="調べるだけ(何も変更しない)")
    parser.add_argument("--replace", action="store_true",
                        help="手作業で置かれたスキルがあれば、削除済みへ移して置き換える")
    args = parser.parse_args()

    print("=" * 68)
    print("仕訳.TeamTKS 移行ツール")
    print("=" * 68)

    if args.check:
        state = "移行済み" if (TARGET / MARK).is_file() else ("手作業で置かれたもの" if TARGET.exists() else "未移行")
        say("状態", f"{TARGET}: {state}")
        md = TARGET / "SKILL.md"
        if md.is_file():
            # 置き換えてよいかの判断材料。案件の判定(resolve_case)は9月末に入った処理
            when = datetime.fromtimestamp(md.stat().st_mtime).strftime("%Y-%m-%d")
            recent = "あり" if "resolve_case" in md.read_text(encoding="utf-8", errors="replace") else "なし(9月末より前の版)"
            say("版", f"SKILL.mdの更新日 {when} / 案件の判定の処理: {recent}")
        report_app_managed(digest(md) if md.is_file() else None)
        print()
        print("  ※ 調べただけで、何も変更していません。")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        src, head = latest_source(Path(tmp))
        install(src, head, replace_hand_placed=args.replace)
    recreate_shortcut()
    old = report_app_managed(digest(TARGET / "SKILL.md"))

    print()
    print("=" * 68)
    print("あと2つ、画面での操作をお願いします")
    print("=" * 68)
    if old:
        print("  1. 設定 ▸ カスタマイズ ▸ プラグイン ▸ 「Voucher to yayoi」を開き、")
        print("     右上のスイッチを切って無効にする")
        print("     (同じ名前のスキルが2つあると、Claudeが古い方を読むおそれがあるため)")
    else:
        print("  1. (古いスキルは見つからなかったので、この操作は不要です)")
    print("  2. ランチャーを閉じて、デスクトップの「仕訳.TeamTKS」から起動し直す")
    if head == "zip":
        print()
        print("  ※ このPCには内部の複製が無いため、今後の自動更新は働きません。")
        print("    更新のたびに、このツールをもう一度実行してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
