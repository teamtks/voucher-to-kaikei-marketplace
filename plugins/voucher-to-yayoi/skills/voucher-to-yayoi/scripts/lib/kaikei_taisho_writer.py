"""LegRow のリストから、会計大将のCSV取込形式を生成する。

弥生会計とは異なり会計大将のCSV仕様は公開されていないため、この実装は
実際の顧問先(会計大将利用)からエクスポートされたCSVの実データを解析して
判明した規則に基づく(2026-07時点、㈱美BORN案件で確認)。

確認済みの規則:
- 文字コード: CP932、改行: CRLF。ヘッダ行は無い。1行=44列(カンマ区切り)。
- 空文字列の列でも、列によって `""` (ダブルクォート2つ)で埋めるか、
  何も書かない(バコンマとコンマの間が空)かが固定で決まっている
  (どちらでも取込は通ると思われるが、実データに合わせて再現している)。
- 列1(0始まり): 「月度コード」。会計年度の期首月を1か月目とする四半期番号を
  10の位、その四半期内の月番号(1-3)を1の位にした値
  (期首月,+1,+2月→1,2,3 / +3,+4,+5月→11,12,13 / +6,+7,+8月→21,22,23 /
  +9,+10,+11月→31,32,33)。実データから機械的に確認済み。
- 列6=借方科目コード、列17=貸方科目コード。
- 列28=金額、列29=消費税額、列30・列31=税区分に応じた固定コード。
- 列33・列34: 現金・預金などの「資金科目」が絡む行にだけ値が入る
  (資金科目でない科目同士の行は両方とも"0")。値は資金科目ごとに個別に
  割り当てられた内部コードで、科目コードから機械的に導出できないため、
  kaikei_taisho_accounts.AccountCode の fund_type_code / fund_ledger_id を
  そのまま使う。

未対応(今後の拡張課題。呼び出し側でエラーにする):
- 1伝票内の明細が複数行になる仕訳(split_side指定のある複合仕訳)。
- 税区分「課対仕入込10%適格」以外(軽減税率8%・非課税・売上側の税区分等)。
  実データ上それらしき値は見つかっているが、確証が持てるだけの実例が
  無いため、確証が得られるまでは意図的にサポートしない。
"""
import math
from datetime import date

from .kaikei_taisho_accounts import AccountCode, AccountCodeTable
from .models import LegRow

# 税区分ごとの (消費税率区分コード, 課税コード, 税率の分子, 分母)。
# 実データ(旅費交通費など課税仕入10%の科目)で確認済みの組み合わせのみ登録する。
_TAX_RULES = {
    "課対仕入込10%適格": ("10", "4", 10, 110),
}

_SUPPORTED_TAX_CATEGORIES = ", ".join(_TAX_RULES)


class KaikeiTaishoBuildError(Exception):
    """会計大将CSVの組み立てに失敗した場合の例外。"""


def fiscal_period_code(d: date, fiscal_start_month: int) -> str:
    fiscal_month_index = (d.month - fiscal_start_month) % 12  # 0-11
    quarter = fiscal_month_index // 3       # 0-3
    month_in_quarter = fiscal_month_index % 3 + 1  # 1-3
    return str(quarter * 10 + month_in_quarter)


def _tax_amount(amount: int, tax_category: str, voucher_id: str) -> tuple[str, str, int]:
    try:
        rate_code, type_code, num, den = _TAX_RULES[tax_category]
    except KeyError:
        raise KaikeiTaishoBuildError(
            f"伝票 {voucher_id}: 税区分「{tax_category}」は会計大将CSV出力では未対応です"
            f"(対応済み: {_SUPPORTED_TAX_CATEGORIES})"
        )
    tax_amount = math.floor(amount * num / den)
    return rate_code, type_code, tax_amount


def _fund_flags(debit_code: AccountCode, credit_code: AccountCode) -> tuple[str, str]:
    # 実データはいずれも「借方=経費科目(資金科目でない)・貸方=資金科目」の
    # 支払仕訳のみのため、資金科目フラグは貸方側のものを採用する。
    # 借方側が資金科目になるケース(入金など)は未検証のため対象外。
    if credit_code.fund_type_code != "0" or credit_code.fund_ledger_id != "0":
        return credit_code.fund_type_code, credit_code.fund_ledger_id
    return "0", "0"


def _q(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def build_row(leg: LegRow, accounts: AccountCodeTable) -> str:
    if leg.split_side is not None:
        raise KaikeiTaishoBuildError(
            f"伝票 {leg.voucher_id}: 会計大将CSV出力は現時点で単純仕訳"
            "(1伝票1明細、split_side指定なし)のみ対応しています"
        )
    if leg.debit.amount != leg.credit.amount:
        raise KaikeiTaishoBuildError(
            f"伝票 {leg.voucher_id}: 借方金額({leg.debit.amount})と"
            f"貸方金額({leg.credit.amount})が一致していません"
        )

    debit_code = accounts.lookup(leg.debit.account)
    credit_code = accounts.lookup(leg.credit.account)

    amount = int(leg.debit.amount)
    rate_code, type_code, tax_amount = _tax_amount(amount, leg.debit.tax_category, leg.voucher_id)
    fund_a, fund_b = _fund_flags(debit_code, credit_code)

    fields = [
        leg.transaction_date.strftime("%Y/%m/%d"),  # 0
        fiscal_period_code(leg.transaction_date, accounts.fiscal_start_month),  # 1
        "",                    # 2
        '""',                  # 3
        "0",                   # 4
        "1",                   # 5
        debit_code.code,       # 6
        "",                    # 7
        '""',                  # 8
        '""',                  # 9
        "2",                   # 10
        "0",                   # 11
        "1",                   # 12
        "0",                   # 13
        '""',                  # 14
        "0",                   # 15
        '""',                  # 16
        credit_code.code,      # 17
        "",                    # 18
        '""',                  # 19
        '""',                  # 20
        "0", "0", "0", "0",   # 21-24
        '""',                  # 25
        "0",                   # 26
        '""',                  # 27
        str(amount),           # 28
        str(tax_amount),       # 29
        rate_code,             # 30
        type_code,             # 31
        "0",                   # 32
        fund_a,                # 33
        fund_b,                # 34
        _q(leg.description),   # 35
        "0", "0", "0", "0", "0",  # 36-40
        "",                    # 41
        "0",                   # 42
        '""',                  # 43
    ]
    return ",".join(fields)


def write_kaikei_taisho_file(legs: list[LegRow], accounts: AccountCodeTable, path: str) -> None:
    lines = [build_row(leg, accounts) for leg in legs]
    with open(path, "wb") as f:
        for line in lines:
            f.write(line.encode("cp932") + b"\r\n")
