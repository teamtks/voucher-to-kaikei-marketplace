"""確定済み仕訳データ(JSON)の共通読み込み処理。

generate_yayoi.py・generate_kaikei_taisho.py など、出力形式が異なる
複数のジェネレータから共通で使う。入力JSONの形式は各ジェネレータのdocstring
(または SKILL.md)を参照。
"""
from datetime import date

from .models import AccountEntry, LegRow


def account_entry_from_dict(d: dict) -> AccountEntry:
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
                debit=account_entry_from_dict(leg["debit"]),
                credit=account_entry_from_dict(leg["credit"]),
                closing_flag=leg.get("closing_flag", ""),
                description=leg.get("description", ""),
                memo=leg.get("memo", ""),
                split_side=leg.get("split_side"),
            )
        )
    return legs
