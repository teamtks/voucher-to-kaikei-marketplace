"""インポート用ファイルの出力先を決める共通処理。

出力先を指定しなかった場合の既定はデスクトップ。利用者が案件フォルダを辿らずに
すぐ取り込めるようにするため(案件フォルダ内に出すと、インポート時にファイルを
探すのに手間がかかる)。案件ごとに別の場所へ出したい場合は、案件フォルダの
CLAUDE.mdにその指示を書いておき、Claudeが出力先を明示的に指定する。

既定のファイル名には日付を入れる(例: 仕訳インポート_20260729.txt)。同じ日に
複数回作った場合は、既にあるファイルを上書きせず「(2)」「(3)」と番号を付ける
(利用者の許可なくファイルを失わせないため)。
"""
from datetime import date
from pathlib import Path

DEFAULT_BASENAME = "仕訳インポート"


class OutputPathError(RuntimeError):
    """出力先を決められなかった場合。"""


def desktop_dir() -> Path:
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        raise OutputPathError(f"デスクトップフォルダが見つかりません: {desktop}")
    return desktop


def avoid_overwrite(path: Path) -> Path:
    """既に同名ファイルがある場合、「(2)」「(3)」…を付けた未使用のパスを返す。"""
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem}({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise OutputPathError(f"出力先の候補が多すぎます: {path}")


def resolve_output_path(
    specified: "str | None",
    suffix: str,
    *,
    today: "date | None" = None,
) -> Path:
    """出力先を決める。

    specified が指定されていればそれを使う(案件のCLAUDE.mdで生成先が指定されて
    いる場合など)。フォルダを指しているときは、その中に既定のファイル名で出す。
    指定が無ければデスクトップに出す。いずれの場合も既存ファイルは上書きしない。
    """
    stamp = (today or date.today()).strftime("%Y%m%d")
    default_name = f"{DEFAULT_BASENAME}_{stamp}{suffix}"

    if specified:
        path = Path(specified)
        # 既存のフォルダ、または末尾が区切り文字/拡張子なしならフォルダ扱いにする
        if path.is_dir() or not path.suffix:
            path = path / default_name
    else:
        path = desktop_dir() / default_name

    return avoid_overwrite(path)
