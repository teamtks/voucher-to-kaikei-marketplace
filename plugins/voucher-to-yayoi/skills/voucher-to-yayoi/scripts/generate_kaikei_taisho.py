"""ユーザーが確認・確定した仕訳データ(JSON)から、会計大将のCSV取込形式の
ファイルを生成する。入力JSONは generate_yayoi.py と同じ形式(SKILL.md参照)。

弥生会計と異なり、会計大将は勘定科目を数値コードで管理しており、そのコード
体系は案件(顧問先)ごとに異なる。そのため、このスクリプトはもう1つ、
「勘定科目名 → 会計大将の科目コード」の対応表(JSON)を追加の入力として
必要とする。書式は lib/kaikei_taisho_accounts.py のdocstringを参照。

現時点の制限(SKILL.md参照):
- 1伝票1明細の単純仕訳のみ対応(複合仕訳は非対応)。
- 税区分は「課対仕入込10%適格」のみ対応。

使い方:
    python generate_kaikei_taisho.py <入力JSON> <科目コード表.json> <出力先.csv>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.kaikei_taisho_accounts import AccountCodeError, load_account_code_table
from lib.kaikei_taisho_writer import KaikeiTaishoBuildError, write_kaikei_taisho_file
from lib.voucher_builder import group_legs_by_voucher
from lib.voucher_input import load_legs


def main():
    if len(sys.argv) != 4:
        print("使い方: python generate_kaikei_taisho.py <入力JSON> <科目コード表.json> <出力先.csv>")
        raise SystemExit(1)

    input_path = Path(sys.argv[1])
    accounts_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])

    data = json.loads(input_path.read_text(encoding="utf-8"))
    legs = load_legs(data)
    if not legs:
        print("入力JSONにlegsが1件もありません。")
        raise SystemExit(1)

    groups = group_legs_by_voucher(legs)
    multi_leg_vouchers = [vid for vid, group in groups.items() if len(group) > 1]
    if multi_leg_vouchers:
        print("会計大将CSV出力は現時点で単純仕訳(1伝票1明細)のみ対応しています。")
        print(f"複数明細の伝票が見つかりました: {', '.join(multi_leg_vouchers)}")
        print("複合仕訳が必要な場合は generate_yayoi.py (弥生形式) をご利用ください。")
        raise SystemExit(1)

    try:
        accounts = load_account_code_table(str(accounts_path))
    except AccountCodeError as e:
        print("科目コード表の読み込みに失敗しました:")
        for err in e.errors:
            print(f"  - {err}")
        raise SystemExit(1)

    try:
        write_kaikei_taisho_file(legs, accounts, str(output_path))
    except (KaikeiTaishoBuildError, AccountCodeError) as e:
        print(f"会計大将CSVの組み立てに失敗しました: {e}")
        raise SystemExit(1)

    print(f"会計大将インポート用CSVを出力しました: {output_path}")
    print(f"出力行数: {len(legs)}")


if __name__ == "__main__":
    main()
