"""ユーザーが確認・確定した仕訳データ(JSON)から、弥生会計インポート形式の
テキストファイルを生成する。

入力JSONの形式:
{
  "start_denpyo_no": 1,
  "legs": [
    {
      "voucher_id": "任意の一意な文字列(同じ値をまとめて1伝票にする)",
      "leg_no": 1,
      "transaction_date": "2026-07-02",
      "closing_flag": "",
      "debit":  {"account": "...", "sub_account": "", "department": "", "tax_category": "...", "amount": 1000, "tax_amount": 0},
      "credit": {"account": "...", "sub_account": "", "department": "", "tax_category": "...", "amount": 1000, "tax_amount": 0},
      "description": "摘要",
      "memo": "",
      "split_side": null
    }
  ]
}

出力先を省略するとデスクトップに「仕訳インポート_YYYYMMDD.txt」として出力する
(案件フォルダを辿らずにすぐ取り込めるようにするため)。案件ごとに別の場所へ
出したい場合は、案件フォルダのCLAUDE.mdにその指示を書き、出力先を明示して渡す。

使い方:
    python generate_yayoi.py <入力JSON> [出力先]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.output_path import OutputPathError, resolve_output_path
from lib.validators import ValidationError, validate_output_rows
from lib.voucher_builder import VoucherBuildError, build_all_vouchers
from lib.voucher_input import load_legs
from lib.yayoi_writer import write_yayoi_file


def main():
    parser = argparse.ArgumentParser(
        description="確定した仕訳データ(JSON)から弥生会計インポート形式のファイルを作る"
    )
    parser.add_argument("input", help="入力JSON")
    parser.add_argument(
        "output",
        nargs="?",
        help="出力先(ファイルまたはフォルダ)。省略時はデスクトップ",
    )
    args = parser.parse_args()

    input_path = Path(args.input)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    legs = load_legs(data)
    if not legs:
        print("入力JSONにlegsが1件もありません。")
        raise SystemExit(1)

    start_no = int(data.get("start_denpyo_no", 1))

    try:
        rows = build_all_vouchers(legs, start_denpyo_no=start_no)
    except VoucherBuildError as e:
        print(f"仕訳の組み立てに失敗しました: {e}")
        raise SystemExit(1)

    errors = validate_output_rows(rows)
    if errors:
        print("検証エラーのため出力を中止しました:")
        for err in errors:
            print(f"  - {err}")
        raise SystemExit(1)

    try:
        output_path = resolve_output_path(args.output, ".txt")
    except OutputPathError as e:
        print(f"出力先を決められませんでした: {e}")
        raise SystemExit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yayoi_file(rows, str(output_path))
    print(f"弥生会計インポート用ファイルを出力しました: {output_path}")
    print(f"出力行数: {len(rows)} (伝票数: {len(set(r.denpyo_no for r in rows))})")


if __name__ == "__main__":
    main()
