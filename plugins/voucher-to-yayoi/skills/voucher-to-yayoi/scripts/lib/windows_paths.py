"""Windowsの「本当の」特別フォルダ(デスクトップ等)を求める。

`Path.home() / "Desktop"` と決め打ちしてはいけない。OneDriveのバックアップ
(Known Folder Move)が有効なPCでは、実際のデスクトップは
`C:\\Users\\<user>\\OneDrive\\デスクトップ` のようにOneDrive配下へ移動しており、
かつ日本語環境ではフォルダ名が「デスクトップ」になっている。さらに厄介なことに、
移動後も `C:\\Users\\<user>\\Desktop` が空のまま残っていることがあり、決め打ちだと
「作成には成功するが利用者からは見えない場所」にファイルを置いてしまう
(実際に、他のPCで仕訳チェック資料のアイコンが見当たらない事象が起きた)。

そのためWindows自身に現在のデスクトップの場所を問い合わせる。
"""
import os
from pathlib import Path

# SHGetKnownFolderPath に渡す FOLDERID_Desktop の GUID
_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def _desktop_from_known_folder_api() -> "Path | None":
    """WindowsのSHGetKnownFolderPathで現在のデスクトップの場所を取得する。

    OneDriveへの移動やフォルダ名のローカライズを含め、Windowsが認識している
    実際の場所が返るため、これが最も信頼できる。
    """
    try:
        import ctypes
        from ctypes import windll, wintypes
    except (ImportError, AttributeError):
        return None

    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        guid = GUID()
        if windll.ole32.CLSIDFromString(_FOLDERID_DESKTOP, ctypes.byref(guid)) != 0:
            return None

        path_ptr = ctypes.c_wchar_p()
        # 第2引数0 = 既定の動作、第3引数None = 現在のユーザー
        if windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        ) != 0:
            return None
        try:
            return Path(path_ptr.value) if path_ptr.value else None
        finally:
            windll.ole32.CoTaskMemFree(path_ptr)
    except Exception:
        return None


def _desktop_from_registry() -> "Path | None":
    """レジストリの User Shell Folders から取得する(APIが使えない場合の予備)。"""
    try:
        import winreg
    except ImportError:
        return None
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            raw, _ = winreg.QueryValueEx(key, "Desktop")
        # 値には %USERPROFILE% 等の環境変数が入っていることがある
        return Path(os.path.expandvars(raw))
    except OSError:
        return None


def desktop_dir() -> "Path | None":
    """現在のデスクトップフォルダ。見つからない場合はNone。

    呼び出し側で「デスクトップが使えない」場合の扱いを決められるよう、
    例外ではなくNoneを返す。
    """
    for candidate in (
        _desktop_from_known_folder_api(),
        _desktop_from_registry(),
        Path.home() / "Desktop",
    ):
        if candidate is not None and candidate.is_dir():
            return candidate
    return None
