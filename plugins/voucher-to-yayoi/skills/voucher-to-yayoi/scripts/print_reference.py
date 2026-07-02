"""案件の勘定科目一覧・キーワード対応表(Excel)を、Claudeが参照しやすい
プレーンテキストの一覧として表示する。

使い方:
    python print_reference.py <勘定科目一覧.xlsx> [キーワード対応表.xlsx]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.reference_schema import ReferenceDataError, load_accounts, load_keyword_rules


def main():
    if len(sys.argv) < 2:
        print("使い方: python print_reference.py <勘定科目一覧.xlsx> [キーワード対応表.xlsx]")
        raise SystemExit(1)

    try:
        accounts = load_accounts(sys.argv[1])
    except ReferenceDataError as e:
        print("勘定科目一覧の読み込みに失敗しました:")
        for err in e.errors:
            print(f"  - {err}")
        raise SystemExit(1)

    print("=== 勘定科目一覧 ===")
    print("勘定科目\t補助科目\t既定税区分\t区分")
    for a in accounts:
        print(f"{a.account}\t{a.sub_account}\t{a.default_tax_category}\t{a.category}")

    if len(sys.argv) >= 3:
        try:
            rules = load_keyword_rules(sys.argv[2])
        except ReferenceDataError as e:
            print("\nキーワード対応表の読み込みに失敗しました:")
            for err in e.errors:
                print(f"  - {err}")
            raise SystemExit(1)

        print("\n=== キーワード対応表 ===")
        print("キーワード\t勘定科目\t補助科目\t税区分\t摘要テンプレート\t優先度")
        for r in rules:
            print(f"{r.keyword}\t{r.account}\t{r.sub_account}\t{r.tax_category}\t{r.description_template}\t{r.priority}")


if __name__ == "__main__":
    main()
