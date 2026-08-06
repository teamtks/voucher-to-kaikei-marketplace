"""このスキルをマーケットプレイス経由でインストールしている環境で、内部キャッシュを
最新化する。

背景: Claude Desktopの「プラグイン」画面の「同期」ボタンは、内部に持っている
マーケットプレイスのgit clone(~/.claude/plugins/marketplaces/<name>)を
実際には更新しないことがある(実機で確認済みの不具合)。この状態だと、
アンインストール→インストールし直しても古い内容のままになってしまう。

このスクリプトは、その内部cloneに対して安全な"git fetch + 早送りマージ"のみを
行い(強制上書きはしない)、更新があれば、実際に読み込まれるキャッシュフォルダ
(~/.claude/plugins/cache/<marketplace>/voucher-to-yayoi/<version>/skills/
voucher-to-yayoi)の中身を最新の内容で置き換える。Claude Desktopアプリ自身が
管理する状態ファイル(installed_plugins.json 等)には一切触れない
(表示上の「最終更新日」は更新されないが、実際にスキルが使う内容は最新化される)。

利用者がClaude Desktopの設定画面を操作する必要は無く、このスキルを使う作業の
最初に毎回自動で実行することを想定している。ネットワーク接続が無い場合や、
マーケットプレイス経由でインストールされていない環境(スキルフォルダを直接
使っている場合)では、何もせず終了する。

使い方:
    python refresh_marketplace_cache.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

MARKETPLACE_NAME = "voucher-to-yayoi-marketplace"
PLUGIN_NAME = "voucher-to-yayoi"

HOME = Path.home()
MARKETPLACE_DIR = HOME / ".claude" / "plugins" / "marketplaces" / MARKETPLACE_NAME
CACHE_ROOT = HOME / ".claude" / "plugins" / "cache" / MARKETPLACE_NAME / PLUGIN_NAME

# Pythonの実行環境(venv)はキャッシュフォルダの中に作られるため、更新のたびに
# 一緒に消えてしまう。作り直すには数分かかるうえネットワーク接続も要るので、
# 更新の前後で退避・復元する。
VENV_RELPATH = Path("scripts") / ".venv"
VENV_STASH_NAME = ".venv-keep"


def _run(args: list[str], cwd: Path):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _read_requirements(skill_dir: Path) -> "str | None":
    try:
        return (skill_dir / "requirements.txt").read_text(encoding="utf-8")
    except OSError:
        return None


def _replace_skill_dir(src: Path, dest: Path) -> None:
    """dest(キャッシュ内のスキルフォルダ)の中身をsrcの内容で置き換える。

    dest配下のvenvは消さずに引き継ぐ。ただし、更新でrequirements.txtが変わって
    いた場合は、そのvenvは中身が古いため、その旨を表示して作り直しを促す。
    """
    old_requirements = _read_requirements(dest)

    venv_dir = dest / VENV_RELPATH
    # 退避先はdestの外(バージョンフォルダ直下)に置く。同じドライブなので、
    # コピーではなく一瞬で終わる移動になる。
    stash_dir = dest.parent.parent / VENV_STASH_NAME
    stashed = False
    if venv_dir.is_dir():
        if stash_dir.exists():
            shutil.rmtree(stash_dir)
        venv_dir.rename(stash_dir)
        stashed = True

    try:
        shutil.rmtree(dest)
        shutil.copytree(src, dest)
    finally:
        if stashed:
            restored = dest / VENV_RELPATH
            restored.parent.mkdir(parents=True, exist_ok=True)
            if restored.exists():
                shutil.rmtree(restored)
            stash_dir.rename(restored)

    if stashed and _read_requirements(dest) != old_requirements:
        print(
            "  ※ 必要なライブラリの一覧(requirements.txt)が変わっています。"
            "既存のPython実行環境(scripts/.venv)に対して、"
            "`.venv\\Scripts\\pip install -r ../requirements.txt` を実行し直してください。"
        )


def main() -> None:
    if not (MARKETPLACE_DIR / ".git").is_dir():
        print("マーケットプレイス経由のインストールではないため、確認をスキップします。")
        return

    before = _run(["git", "rev-parse", "HEAD"], MARKETPLACE_DIR).stdout.strip()

    fetch = _run(["git", "fetch", "origin"], MARKETPLACE_DIR)
    if fetch.returncode != 0:
        print("最新情報の取得に失敗しました(ネットワーク未接続の可能性があります)。オフラインのまま続行します。")
        return

    merge = _run(["git", "merge", "--ff-only", "origin/main"], MARKETPLACE_DIR)
    if merge.returncode != 0:
        print("内部クローンの状態が想定外のため、自動更新をスキップしました。")
        return

    after = _run(["git", "rev-parse", "HEAD"], MARKETPLACE_DIR).stdout.strip()

    if before == after:
        print("スキルは既に最新の状態です。")
        return

    print(f"新しいバージョンを検出しました({before[:7]} → {after[:7]})。内容を最新化します。")

    src = MARKETPLACE_DIR / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME
    if not src.is_dir() or not CACHE_ROOT.is_dir():
        print("キャッシュフォルダがまだ無いため、内容のコピーはスキップしました。")
        return

    running_python = Path(sys.executable).resolve()

    updated_any = False
    for version_dir in CACHE_ROOT.iterdir():
        if not version_dir.is_dir():
            continue
        dest = version_dir / "skills" / PLUGIN_NAME
        if not dest.is_dir():
            shutil.copytree(src, dest)
            print(f"最新化しました: {dest}")
            updated_any = True
            continue

        # 入れ替える対象の中にあるPythonでこのスクリプト自身が動いていると、
        # 使用中のファイルを消せずに失敗する。その場合は手を付けずに知らせる。
        if running_python.is_relative_to(dest.resolve()):
            print(
                f"更新をスキップしました: {dest}\n"
                "  このスクリプトを、入れ替え対象のフォルダ内にあるPythonで実行しているためです。"
                "  システムのPython(`python scripts\\refresh_marketplace_cache.py`)で実行し直してください。"
            )
            continue

        _replace_skill_dir(src, dest)
        print(f"最新化しました: {dest}")
        updated_any = True

    if not updated_any:
        print("インストール済みのキャッシュが見つからなかったため、内容のコピーは行いませんでした。")


if __name__ == "__main__":
    main()
