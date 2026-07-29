"""ユーザーが確認・確定した仕訳データ(JSON)から、会計大将のCSV取込形式の
ファイルを生成する。入力JSONは generate_yayoi.py と同じ形式(SKILL.md参照)。

弥生会計と異なり、会計大将は勘定科目を数値コードで管理しており、そのコード
体系は案件(顧問先)ごとに異なる。そのため、このスクリプトはもう1つ、
「勘定科目名 → 会計大将の科目コード」の対応表(JSON)を追加の入力として
必要とする。書式は lib/kaikei_taisho_accounts.py のdocstringを参照。

現時点の制限(SKILL.md参照):
- 1伝票1明細の単純仕訳のみ対応(複合仕訳は非対応)。
- 補助科目は非対応(指定されているとエラーになる)。
- 対応している税区分は lib/kaikei_taisho_writer.py の _TAX_RULES を参照。

出力先を省略するとデスクトップに「仕訳インポート_YYYYMMDD.csv」として出力する
(案件フォルダを辿らずにすぐ取り込めるようにするため)。案件ごとに別の場所へ
出したい場合は、案件フォルダのCLAUDE.mdにその指示を書き、出力先を明示して渡す。

使い方:
    python generate_kaikei_taisho.py <入力JSON> <科目コード表.json> [出力先]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.kaikei_taisho_accounts import AccountCodeError, load_account_code_table
from lib.kaikei_taisho_writer import KaikeiTaishoBuildError, write_kaikei_taisho_file
from lib.output_path import OutputPathError, resolve_output_path
from lib.voucher_builder import group_legs_by_voucher
from lib.voucher_input import load_legs


def main():
    parser = argparse.ArgumentParser(
        description="確定した仕訳データ(JSON)から会計大将CSV取込形式のファイルを作る"
    )
    parser.add_argument("input", help="入力JSON")
    parser.add_argument("accounts", help="科目コード表.json")
    parser.add_argument(
        "output",
        nargs="?",
        help="出力先(ファイルまたはフォルダ)。省略時はデスクトップ",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    accounts_path = Path(args.accounts)

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
        output_path = resolve_output_path(args.output, ".csv")
    except OutputPathError as e:
        print(f"出力先を決められませんでした: {e}")
        raise SystemExit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_kaikei_taisho_file(legs, accounts, str(output_path))
    except (KaikeiTaishoBuildError, AccountCodeError) as e:
        print(f"会計大将CSVの組み立てに失敗しました: {e}")
        raise SystemExit(1)

    print(f"会計大将インポート用CSVを出力しました: {output_path}")
    print(f"出力行数: {len(legs)}")


if __name__ == "__main__":
    main()
