"""黒塗りしていない証憑を読み取らせない安全装置(PreToolUseフック)。

なぜ指示文ではなく仕組みで止めるのか:
  「証憑はローカルで黒塗りしてから読む」というルールはSKILL.mdとCLAUDE.mdの両方に
  書いてあるが、実際に破られた。通帳6件が、別のスキル(bank-ledger-to-yayoi)経由で
  黒塗りされないまま読み取られた。指示文は、そのスキルが選ばれた時点で効かない。
  読み取りそのものを拒否すれば、どのスキルが動いていても止まる。

判定:
  「証憑書類」フォルダの中にある画像・PDFの読み取りは拒否する。ただし
  `*_masked_page*.png`(黒塗り済み)だけは許可する。
  `*_original_page*.png`は黒塗り前のページ画像なので、置き場所を問わず拒否する。

参考資料ファイルは対象にしない。こちらは科目やルールの判断材料であり、宛名の
黒塗りを前提とした運用ではないため、止めると通常の作業が回らなくなる。

異常時は通す(その旨を利用者に表示する)。安全装置の不具合で作業全体が止まる方が
被害が大きいため、黙って落ちるのではなく気づけるようにする。

標準入力にPreToolUseのJSONを受け取り、拒否する場合だけ判断を標準出力に返す。
"""
import json
import sys
from pathlib import PurePath

VOUCHER_FOLDER = "証憑書類"
MASKED_MARK = "_masked_page"
UNMASKED_MARK = "_original_page"
IMAGE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

REASON = """黒塗りしていない証憑の読み取りを止めました。

  対象: {name}

証憑には自社名・住所・口座番号などが写っています。そのまま読み取らせない、という
のがこの案件の取り決めです。先に黒塗りしてから、その結果だけを読んでください。

  <スキルフォルダ>\\scripts\\.venv\\Scripts\\python.exe <スキルフォルダ>\\scripts\\mask_addressee.py "{path}" "<作業用フォルダ>"

作られた `*_masked_page*.png` を読み取ってください。黒塗り前の
`*_original_page*.png` は読み取ってはいけません(証憑と見比べる必要があるときは、
利用者自身が画像を開いて確認します)。"""


def decide(file_path: str) -> "str | None":
    """拒否する理由を返す。読み取ってよい場合はNone。"""
    if not file_path:
        return None
    path = PurePath(file_path)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        return None

    name = path.name
    if MASKED_MARK in name:
        return None  # 黒塗り済み。これだけが読み取ってよいもの
    if UNMASKED_MARK in name:
        return REASON.format(name=name, path=file_path)
    if VOUCHER_FOLDER in path.parts:
        return REASON.format(name=name, path=file_path)
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        # 読めない入力を黙って通すと、安全装置が働いていないことに誰も気づけない。
        # 通しはするが、必ず知らせる(受け渡しの形式が変わった場合にも気づける)。
        print(json.dumps({
            "systemMessage": (
                "！ 黒塗りの安全装置に、読み取れない入力が渡されました"
                f"({type(e).__name__})。この読み取りは止めていません。"
                "証憑を黒塗りしてから読んでいるか、目視で確認してください。"
            )
        }, ensure_ascii=False))
        return

    try:
        file_path = (payload.get("tool_input") or {}).get("file_path") or ""
        reason = decide(str(file_path))
    except Exception as e:
        print(json.dumps({
            "systemMessage": (
                "！ 黒塗りの安全装置が正しく動きませんでした"
                f"({type(e).__name__})。証憑を黒塗りしてから読み取っているか、"
                "目視で確認してください。"
            )
        }, ensure_ascii=False))
        return

    if reason is None:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
