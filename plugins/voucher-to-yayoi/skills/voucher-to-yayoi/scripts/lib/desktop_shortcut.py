"""Windowsのデスクトップショートカット(.lnk)を作成する共通処理。

ランチャー用(setup_launcher.py)と仕訳チェック資料用(generate_review_html.py)で
同じ手順を使うため、ここにまとめている。作成にはWScript.Shell(PowerShell経由)を
使う。既に同名のショートカットがある場合は上書きする(参照先が変わった場合に
追従させるため)。
"""
import subprocess
import tempfile
from pathlib import Path

from .windows_paths import desktop_dir as resolve_desktop_dir


class ShortcutError(RuntimeError):
    """ショートカットの作成に失敗した場合。"""


def desktop_dir() -> Path:
    """デスクトップフォルダのパス。見つからない場合はShortcutError。

    OneDriveへの移動や日本語フォルダ名に対応するため、Windows自身に問い合わせる
    (詳細は windows_paths.desktop_dir のdocstringを参照)。
    """
    desktop = resolve_desktop_dir()
    if desktop is None:
        raise ShortcutError("デスクトップフォルダの場所を特定できませんでした")
    return desktop


def _ps_quote(value: str) -> str:
    """PowerShellのシングルクォート文字列として安全に埋め込める形にする。

    パスに ' が含まれる場合は '' にエスケープする(シングルクォート文字列内では
    $ や ` が展開されないため、コマンドインジェクションの心配も無くなる)。
    """
    return "'" + str(value).replace("'", "''") + "'"


def create_shortcut(
    shortcut_path: "str | Path",
    target: "str | Path",
    *,
    arguments: str = "",
    working_directory: "str | Path | None" = None,
    icon_path: "str | Path | None" = None,
    description: str = "",
) -> Path:
    """ショートカットを作成(または上書き)して、そのパスを返す。

    icon_path に存在しないファイルを渡した場合は、アイコン指定を省略して
    既定のアイコン(ターゲットの種類に応じたもの)になる。
    """
    shortcut_path = Path(shortcut_path)
    target = Path(target)

    lines = [
        "$WshShell = New-Object -ComObject WScript.Shell",
        f"$Shortcut = $WshShell.CreateShortcut({_ps_quote(shortcut_path)})",
        f"$Shortcut.TargetPath = {_ps_quote(target)}",
    ]
    if arguments:
        lines.append(f"$Shortcut.Arguments = {_ps_quote(arguments)}")
    if working_directory:
        lines.append(f"$Shortcut.WorkingDirectory = {_ps_quote(working_directory)}")
    if icon_path and Path(icon_path).is_file():
        lines.append(f"$Shortcut.IconLocation = {_ps_quote(f'{icon_path},0')}")
    if description:
        lines.append(f"$Shortcut.Description = {_ps_quote(description)}")
    lines.append("$Shortcut.Save()")

    # -Command で直接渡すと、コマンド文字列がコンソールの文字コード(日本語環境では
    # cp932)に変換される過程で、cp932に無い文字が "?" に化けてしまう。UTF-8(BOM付き)の
    # 一時スクリプトに書き出して -File で実行すれば、PowerShellがBOMからUTF-8と
    # 判断するため、パス等をそのまま渡せる。
    #
    # なお description(ショートカットの説明・ツールチップ)については、この経路とは
    # 別に WScript.Shell 側がcp932を経由して書き込むため、cp932に無い文字(全角
    # ダッシュ "—" U+2014 など)は "?" になる。説明文にはcp932の範囲の文字だけを使うこと。
    script_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False
        ) as f:
            f.write("\n".join(lines))
            script_path = Path(f.name)
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script_path),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        if script_path is not None:
            script_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise ShortcutError(f"ショートカット作成に失敗しました: {result.stderr.strip()}")
    if not shortcut_path.is_file():
        raise ShortcutError(f"ショートカットが作成されませんでした: {shortcut_path}")
    return shortcut_path
