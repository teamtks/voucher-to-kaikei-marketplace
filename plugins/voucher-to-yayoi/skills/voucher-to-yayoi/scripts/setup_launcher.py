"""ランチャー(launcher.pyw)を起動するためのデスクトップショートカットを作成する。

初回セットアップの一環としてClaude自身が実行することを想定している。
既にショートカットが存在する場合は上書きする(パスが変わった場合に追従するため)。

使い方:
    python setup_launcher.py
"""
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "証憑仕訳処理.lnk"


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

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{pythonw}"
$Shortcut.Arguments = '"{launcher_path}"'
$Shortcut.WorkingDirectory = "{skill_dir}"
$Shortcut.IconLocation = "{pythonw},0"
$Shortcut.Description = "証憑仕訳処理ツールを開く"
$Shortcut.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ショートカット作成に失敗しました: {result.stderr}")
    return shortcut_path


def main() -> None:
    shortcut_path = create_desktop_shortcut()
    print(f"デスクトップにショートカットを作成しました: {shortcut_path}")


if __name__ == "__main__":
    main()
