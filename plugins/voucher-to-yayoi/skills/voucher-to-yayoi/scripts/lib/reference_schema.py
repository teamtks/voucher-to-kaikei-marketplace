"""参考データ(勘定科目一覧表・キーワード対応表)の読み込みと検証。

案件(法人・個人)ごとに異なるExcelファイルへ差し替えて実行することを前提とする。
"""
from dataclasses import dataclass

import pandas as pd


class ReferenceDataError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class Account:
    account: str
    sub_account: str = ""
    default_tax_category: str = ""
    category: str = ""


@dataclass
class KeywordRule:
    keyword: str
    account: str
    sub_account: str = ""
    tax_category: str = ""
    description_template: str = ""
    priority: int = 0


def _read_sheet(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0, dtype=str)
    return df.fillna("")


def load_accounts(path: str) -> list[Account]:
    df = _read_sheet(path)
    if "勘定科目" not in df.columns or "既定税区分" not in df.columns:
        raise ReferenceDataError(
            [f"{path}: 必須列(勘定科目・既定税区分)が見つかりません。列: {list(df.columns)}"]
        )
    accounts = []
    for _, row in df.iterrows():
        account = row["勘定科目"].strip()
        if not account:
            continue
        accounts.append(
            Account(
                account=account,
                sub_account=row.get("補助科目", "").strip(),
                default_tax_category=row["既定税区分"].strip(),
                category=row.get("区分", "").strip(),
            )
        )
    errors = validate_accounts(accounts)
    if errors:
        raise ReferenceDataError(errors)
    return accounts


def validate_accounts(accounts: list[Account]) -> list[str]:
    errors = []
    if not accounts:
        errors.append("勘定科目一覧表にデータが1件もありません")
    seen = set()
    for a in accounts:
        key = (a.account, a.sub_account)
        if key in seen:
            errors.append(f"勘定科目一覧表に重複行があります: {a.account}/{a.sub_account}")
        seen.add(key)
        if not a.default_tax_category:
            errors.append(f"勘定科目一覧表: {a.account} の既定税区分が空欄です")
    return errors


def load_keyword_rules(path: str) -> list[KeywordRule]:
    df = _read_sheet(path)
    required = {"キーワード", "勘定科目"}
    if not required.issubset(df.columns):
        raise ReferenceDataError(
            [f"{path}: 必須列(キーワード・勘定科目)が見つかりません。列: {list(df.columns)}"]
        )
    rules = []
    for _, row in df.iterrows():
        keyword = row["キーワード"].strip()
        if not keyword:
            continue
        priority_raw = row.get("優先度", "").strip()
        priority = int(priority_raw) if priority_raw else 0
        rules.append(
            KeywordRule(
                keyword=keyword,
                account=row["勘定科目"].strip(),
                sub_account=row.get("補助科目", "").strip(),
                tax_category=row.get("税区分", "").strip(),
                description_template=row.get("摘要テンプレート", "").strip(),
                priority=priority,
            )
        )
    if not rules:
        raise ReferenceDataError([f"{path}: キーワード対応表にデータが1件もありません"])
    # 優先度が高い順、同点はキーワードが長い(より具体的な)ものを優先
    rules.sort(key=lambda r: (-r.priority, -len(r.keyword)))
    return rules


def account_names(accounts: list[Account]) -> list[str]:
    """Excelのデータ入力規則(ドロップダウン)に使う勘定科目名の一覧(重複除去・順序維持)。"""
    seen = []
    for a in accounts:
        if a.account not in seen:
            seen.append(a.account)
    return seen


def tax_category_names(accounts: list[Account]) -> list[str]:
    """Excelのデータ入力規則に使う税区分の一覧(重複除去)。"""
    seen = []
    for a in accounts:
        if a.default_tax_category not in seen:
            seen.append(a.default_tax_category)
    return seen
