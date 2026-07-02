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

使い方:
    python generate_yayoi.py <入力JSON> <出力先.txt>
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.models import AccountEntry, LegRow
from lib.validators import ValidationError, validate_output_rows
from lib.voucher_builder import VoucherBuildError, build_all_vouchers
from lib.yayoi_writer import write_yayoi_file


def _account_entry(d: dict) -> AccountEntry:
    return AccountEntry(
        account=d["account"],
        sub_account=d.get("sub_account", ""),
        department=d.get("department", ""),
        tax_category=d.get("tax_category", ""),
        amount=int(d["amount"]),
        tax_amount=int(d.get("tax_amount", 0)),
    )


def load_legs(data: dict) -> list[LegRow]:
    legs = []
    for i, leg in enumerate(data["legs"]):
        legs.append(
            LegRow(
                voucher_id=leg["voucher_id"],
                leg_no=leg.get("leg_no", i + 1),
                transaction_date=date.fromisoformat(leg["transaction_date"]),
                debit=_account_entry(leg["debit"]),
                credit=_account_entry(leg["credit"]),
                closing_flag=leg.get("closing_flag", ""),
                description=leg.get("description", ""),
                memo=leg.get("memo", ""),
                split_side=leg.get("split_side"),
            )
        )
    return legs


def main():
    if len(sys.argv) != 3:
        print("使い方: python generate_yayoi.py <入力JSON> <出力先.txt>")
        raise SystemExit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yayoi_file(rows, str(output_path))
    print(f"弥生会計インポート用ファイルを出力しました: {output_path}")
    print(f"出力行数: {len(rows)} (伝票数: {len(set(r.denpyo_no for r in rows))})")


if __name__ == "__main__":
    main()
