"""このセッションで作業すべき案件フォルダを決める。

なぜ必要か:
  ランチャーは案件フォルダを指定してClaude Desktopを開くが、利用先のPCによっては
  最初の送信のときにフォルダが外れ、セッションが「フォルダなし」(一時作業領域)に
  なる。こちらでは再現できず、アプリ側の挙動なので防げない。その状態でも、移動も
  確認もせずに正しい案件で作業を続けるために、本来の案件フォルダを割り出す。

  判定を指示文(SKILL.md)に任せないのは、取り違えると別の顧問先の仕訳を作って
  しまうため。優先順位と取り違えの防ぎ方を、ここで固定してテストする。

優先順位:
  1. 作業ディレクトリ自体が案件フォルダなら、それ(通常はこれ)
  2. 最初の依頼の中に、ランチャーが入れた【案件: 名前】があれば、その案件
     (セッションごとの文章に残るので、案件を続けて開いても取り違えない)
  3. ランチャーの控え(最後に開いた案件)。ただし、案件を続けて開くと後のもので
     上書きされ、別の案件を指しうる。**必ず利用者に確認してから使う**
  4. どれも無ければ、分からない

使い方:
    python resolve_case.py [--name "案件名"]
結果はJSONで1行出力する。
    {"case": "<案件フォルダの絶対パス>" | null, "how": "cwd|marker|record|none",
     "confirm": true|false, "reason": "..."}
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

VOUCHER_SUBFOLDER = "証憑書類"
REFERENCE_SUBFOLDER = "参考資料ファイル"

LAUNCHER_CONFIG = Path(os.environ.get("APPDATA", str(Path.home()))) / "voucher-to-yayoi-launcher" / "config.json"
LAST_OPEN_RECORD = Path.home() / ".claude" / "voucher-to-yayoi-last-open.json"

# 控えは「今開いたもの」を指しているときだけ候補にする。古い控えは、昨日の別の
# 案件を指していることがあり、使えば取り違えにつながる。
RECORD_FRESH_FOR = timedelta(minutes=30)


def is_case_folder(folder: Path) -> bool:
    """ランチャーの作る案件フォルダの形をしているか。"""
    return folder.is_dir() and (
        (folder / VOUCHER_SUBFOLDER).is_dir() or (folder / "CLAUDE.md").is_file()
    )


def launcher_root() -> "Path | None":
    try:
        root = json.loads(LAUNCHER_CONFIG.read_text(encoding="utf-8")).get("root_folder")
    except (OSError, ValueError):
        return None
    return Path(root) if root else None


def read_record() -> "tuple[Path, datetime] | None":
    try:
        data = json.loads(LAST_OPEN_RECORD.read_text(encoding="utf-8"))
        return Path(data["project"]), datetime.fromisoformat(data["opened_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def resolve(cwd: Path, name: "str | None", now: "datetime | None" = None) -> dict:
    now = now or datetime.now()

    if is_case_folder(cwd):
        return {"case": str(cwd), "how": "cwd", "confirm": False,
                "reason": "作業ディレクトリが案件フォルダです"}

    record = read_record()

    if name:
        name = name.strip()
        # 控えが同じ名前を指していれば、その絶対パスを使う(置き場所を変えていても正しい)
        if record and record[0].name == name and is_case_folder(record[0]):
            return {"case": str(record[0]), "how": "marker", "confirm": False,
                    "reason": f"依頼の中の【案件: {name}】から判断しました"}
        root = launcher_root()
        if root and is_case_folder(root / name):
            return {"case": str(root / name), "how": "marker", "confirm": False,
                    "reason": f"依頼の中の【案件: {name}】から判断しました"}
        # 名前はあるのに見つからない。控えで代用すると、別の案件を指しうるので使わない
        return {"case": None, "how": "none", "confirm": False,
                "reason": f"【案件: {name}】の案件フォルダが見つかりません"}

    if record:
        project, opened_at = record
        if now - opened_at <= RECORD_FRESH_FOR and is_case_folder(project):
            return {"case": str(project), "how": "record", "confirm": True,
                    "reason": "ランチャーが最後に開いた案件です(続けて開いた場合は別の案件の"
                              "可能性があるため、利用者に確認が必要です)"}

    return {"case": None, "how": "none", "confirm": False,
            "reason": "作業すべき案件フォルダを判断できません"}


def main() -> int:
    parser = argparse.ArgumentParser(description="作業すべき案件フォルダを決める")
    parser.add_argument("--name", help="依頼の中の【案件: 名前】の名前部分")
    args = parser.parse_args()
    print(json.dumps(resolve(Path.cwd(), args.name), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
