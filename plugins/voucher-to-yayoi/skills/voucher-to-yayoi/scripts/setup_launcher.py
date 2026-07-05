"""ランチャー(launcher.pyw)を起動するためのデスクトップショートカットを作成する。

初回セットアップの一環としてClaude自身が実行することを想定している。
既にショートカットが存在する場合は上書きする(パスが変わった場合に追従するため)。

使い方:
    python setup_launcher.py
"""
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "仕訳.TeamTKS.lnk"
_OLD_SHORTCUT_NAMES = ("証憑仕訳処理.lnk",)  # 旧名称。残っていれば整理する。


def find_pythonw() -> Path:
    venv_pythonw = Path(sys.executable).parent / "pythonw.exe"
    if venv_pythonw.is_file():
        return venv_pythonw
    return Path(sys.executable)


def create_desktop_shortcut() -> Path:
    skill_dir = Path(__file__).resolve().parent
    launcher_path = skill_dir / "launcher.pyw"
    if not launcher_path.is_file():
        raise FileNotFoundError(f"launcher.pywが見つかりません: {launcher_path}")

    pythonw = find_pythonw()
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        raise FileNotFoundError(f"デスクトップフォルダが見つかりません: {desktop}")
    shortcut_path = desktop / SHORTCUT_NAME

    icon_path = skill_dir / "app_icon.ico"
    icon_location = f"{icon_path},0" if icon_path.is_file() else f"{pythonw},0"

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{pythonw}"
$Shortcut.Arguments = '"{launcher_path}"'
$Shortcut.WorkingDirectory = "{skill_dir}"
$Shortcut.IconLocation = "{icon_location}"
$Shortcut.Description = "仕訳.TeamTKS — 証憑仕訳処理ツール"
$Shortcut.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ショートカット作成に失敗しました: {result.stderr}")
    return shortcut_path


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
