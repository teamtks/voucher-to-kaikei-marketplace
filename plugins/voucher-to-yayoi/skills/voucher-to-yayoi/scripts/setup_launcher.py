"""ランチャー(launcher.pyw)を起動するためのデスクトップショートカットを作成する。

初回セットアップの一環としてClaude自身が実行することを想定している。
既にショートカットが存在する場合は上書きする(パスが変わった場合に追従するため)。

使い方:
    python setup_launcher.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.desktop_shortcut import create_shortcut, desktop_dir

SHORTCUT_NAME = "仕訳.TeamTKS.lnk"
_OLD_SHORTCUT_NAMES = ("証憑仕訳処理.lnk",)  # 旧名称。残っていれば整理する。


def find_pythonw() -> Path:
    """ランチャーを起動するpythonw.exe。スキルのフォルダの外にあるものを優先する。

    ランチャーは作業を始めるたびにスキルを最新化する。スキルの中のPython(.venv)で
    ランチャーが動いていると、そのフォルダが使用中になり、入れ替えに失敗する。
    """
    skill_dir = Path(__file__).resolve().parent.parent
    candidates = []
    found = shutil.which("pythonw")
    if found:
        candidates.append(Path(found))
    candidates.append(Path(sys.executable).parent / "pythonw.exe")
    for c in candidates:
        try:
            c = c.resolve()
            if c.is_file() and not c.is_relative_to(skill_dir):
                return c
        except (OSError, ValueError):
            continue
    # 外に見つからなければ、従来どおり手元のものを使う(起動できないよりはよい)
    venv_pythonw = Path(sys.executable).parent / "pythonw.exe"
    return venv_pythonw if venv_pythonw.is_file() else Path(sys.executable)


def create_desktop_shortcut() -> Path:
    skill_dir = Path(__file__).resolve().parent
    launcher_path = skill_dir / "launcher.pyw"
    if not launcher_path.is_file():
        raise FileNotFoundError(f"launcher.pywが見つかりません: {launcher_path}")

    pythonw = find_pythonw()
    return create_shortcut(
        desktop_dir() / SHORTCUT_NAME,
        pythonw,
        arguments=f'"{launcher_path}"',
        working_directory=skill_dir,
        icon_path=skill_dir / "app_icon.ico",
        description="仕訳.TeamTKS(証憑仕訳処理ツール)",
    )


def find_old_shortcuts() -> "list[Path]":
    """旧名称のショートカットを探す(削除はしない。利用者の許可なく削除しない
    運用ルールのため、見つけて知らせるだけにとどめる)。"""
    desktop = Path.home() / "Desktop"
    return [desktop / name for name in _OLD_SHORTCUT_NAMES if (desktop / name).is_file()]


def main() -> None:
    shortcut_path = create_desktop_shortcut()
    print(f"デスクトップにショートカットを作成しました: {shortcut_path}")

    old_shortcuts = find_old_shortcuts()
    if old_shortcuts:
        names = "、".join(p.name for p in old_shortcuts)
        print(
            f"旧名称のショートカット({names})がデスクトップに残っています。"
            "不要であれば、利用者ご自身で削除してください(無断では削除しません)。"
        )


if __name__ == "__main__":
    main()
