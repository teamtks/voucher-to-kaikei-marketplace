"""下書きの仕訳明細行(LegRow)から、弥生インポート形式の出力行(YayoiOutputRow)を組み立てる。

弥生インポート形式.txt の実データ解析で判明した規則:
- 借方・貸方とも1科目で完結する仕訳は、識別フラグ"2000"・タイプ"0"の1行で表現する。
- 一方の側を複数科目に分割する仕訳(複合仕訳)は、同じ伝票Noを持つ複数行で表現する。
  分割していない側の科目は先頭行にのみ実科目を記載し、以降の行では"複合"という
  プレースホルダーになる。分割している側は各行に実科目を記載し、分割していない
  側は"複合"になる。識別フラグは 先頭行"2110" → 中間行(0件以上)"2100" →
  最終行"2101"、タイプは全行"3"。
- どちらの側が「分割されていない側(単一の実科目)」かは、伝票内の全LegRowで
  その側の科目情報(勘定科目・補助科目・部門・税区分)が完全一致しているかどうかで
  自動判定する。両側とも分割されている伝票(1伝票内で借方も貸方も複数の異なる
  実科目を持つ)は、このフォーマットでは表現できないためエラーとする。

注意(対象外とする複合仕訳のパターン): 実データ調査では、1伝票内で「複合」の
出現側(借方/貸方)が明細ごとに入れ替わり、非分割側の合計と分割側明細の合計が
一致しない、より複雑な複合仕訳(例: 銀行入金1件に対し、収益計上と経費相殺を
同時に行うような手動仕訳)も存在することを確認した。これは証憑書類からの
自動起票では通常発生しない、人手による特殊な振替仕訳であるため、本モジュール
は意図的にサポート対象外とする。そのような入力は上記の「両側とも分割」エラー
などで弾かれるか、期待と異なる出力になり得るため、対応が必要な場合は弥生会計上
で直接入力すること。
"""
from collections import OrderedDict
from dataclasses import replace

from .models import (
    AccountEntry,
    FLAG_COMPOUND_FIRST,
    FLAG_COMPOUND_LAST,
    FLAG_COMPOUND_MIDDLE,
    FLAG_SIMPLE,
    LegRow,
    PLACEHOLDER_ACCOUNT,
    PLACEHOLDER_TAX_CATEGORY,
    TYPE_COMPOUND,
    TYPE_SIMPLE,
    YayoiOutputRow,
)


class VoucherBuildError(Exception):
    """伝票の組み立てに失敗した場合の例外。原因を人間が読める形で保持する。"""


def _account_key(entry: AccountEntry) -> tuple:
    return (entry.account, entry.sub_account, entry.department, entry.tax_category)


def _placeholder() -> AccountEntry:
    return AccountEntry(
        account=PLACEHOLDER_ACCOUNT,
        sub_account="",
        department="",
        tax_category=PLACEHOLDER_TAX_CATEGORY,
        amount=0,
        tax_amount=0,
    )


def group_legs_by_voucher(legs: list[LegRow]) -> "OrderedDict[str, list[LegRow]]":
    """voucher_id順(初出順)にLegRowをグルーピングし、各グループをleg_no順に並べる。"""
    groups: "OrderedDict[str, list[LegRow]]" = OrderedDict()
    for leg in legs:
        groups.setdefault(leg.voucher_id, []).append(leg)
    for voucher_id, group in groups.items():
        group.sort(key=lambda r: r.leg_no)
    return groups


def _validate_common_fields(voucher_id: str, legs: list[LegRow]) -> None:
    dates = {leg.transaction_date for leg in legs}
    if len(dates) > 1:
        raise VoucherBuildError(
            f"伝票 {voucher_id}: 同一伝票内で取引日付が一致していません ({sorted(d.isoformat() for d in dates)})"
        )
    closings = {leg.closing_flag for leg in legs}
    if len(closings) > 1:
        raise VoucherBuildError(
            f"伝票 {voucher_id}: 同一伝票内で決算区分が一致していません ({sorted(closings)})"
        )
    for leg in legs:
        if leg.debit.amount != leg.credit.amount:
            raise VoucherBuildError(
                f"伝票 {voucher_id} 明細{leg.leg_no}: 借方金額({leg.debit.amount})と"
                f"貸方金額({leg.credit.amount})が一致していません"
            )
        if not leg.debit.account or not leg.credit.account:
            raise VoucherBuildError(f"伝票 {voucher_id} 明細{leg.leg_no}: 勘定科目が空欄です")


def build_voucher_rows(voucher_id: str, legs: list[LegRow], denpyo_no: int) -> list[YayoiOutputRow]:
    """1伝票分のLegRowから、弥生インポート形式の出力行(1行以上)を組み立てる。"""
    _validate_common_fields(voucher_id, legs)
    first = legs[0]

    if len(legs) == 1:
        leg = legs[0]
        return [
            YayoiOutputRow(
                flag=FLAG_SIMPLE,
                denpyo_no=denpyo_no,
                closing_flag=leg.closing_flag,
                transaction_date=leg.transaction_date,
                debit=leg.debit,
                credit=leg.credit,
                description=leg.description,
                row_type=TYPE_SIMPLE,
                memo=leg.memo,
            )
        ]

    debit_keys = {_account_key(leg.debit) for leg in legs}
    credit_keys = {_account_key(leg.credit) for leg in legs}

    explicit_sides = {leg.split_side for leg in legs if leg.split_side is not None}
    if len(explicit_sides) > 1:
        raise VoucherBuildError(
            f"伝票 {voucher_id}: 明細ごとにsplit_sideの指定が食い違っています({explicit_sides})"
        )
    explicit_side = next(iter(explicit_sides), None)
    if explicit_side is not None and explicit_side not in ("debit", "credit"):
        raise VoucherBuildError(
            f"伝票 {voucher_id}: split_sideは'debit'または'credit'を指定してください(指定値: {explicit_side})"
        )

    if explicit_side is not None:
        split_side = explicit_side
        non_split_keys = credit_keys if split_side == "debit" else debit_keys
        if len(non_split_keys) != 1:
            raise VoucherBuildError(
                f"伝票 {voucher_id}: split_side='{split_side}'指定ですが、"
                f"非分割側の科目情報が明細間で一致していません"
            )
    elif len(credit_keys) == 1 and len(debit_keys) > 1:
        split_side = "debit"
    elif len(debit_keys) == 1 and len(credit_keys) > 1:
        split_side = "credit"
    elif len(debit_keys) == 1 and len(credit_keys) == 1:
        raise VoucherBuildError(
            f"伝票 {voucher_id}: 借方・貸方とも科目情報が明細間で同一のため、"
            "どちらが分割側か自動判定できません。各明細のsplit_sideに"
            "'debit'または'credit'を明示してください。"
        )
    else:
        raise VoucherBuildError(
            f"伝票 {voucher_id}: 借方・貸方の両方が複数科目に分割されています。"
            "このフォーマットでは1伝票につきどちらか一方のみ分割に対応しています。"
            "伝票を分けて入力してください。"
        )

    primary_side_entry = first.credit if split_side == "debit" else first.debit
    total_amount = sum(leg.debit.amount for leg in legs)
    primary_total = replace(primary_side_entry, amount=total_amount)

    rows: list[YayoiOutputRow] = []

    header_debit = _placeholder() if split_side == "debit" else primary_total
    header_credit = primary_total if split_side == "debit" else _placeholder()
    if split_side == "debit":
        header_debit.amount = total_amount
    else:
        header_credit.amount = total_amount

    rows.append(
        YayoiOutputRow(
            flag=FLAG_COMPOUND_FIRST,
            denpyo_no=denpyo_no,
            closing_flag=first.closing_flag,
            transaction_date=first.transaction_date,
            debit=header_debit,
            credit=header_credit,
            description=first.description,
            row_type=TYPE_COMPOUND,
            memo=first.memo,
        )
    )

    for i, leg in enumerate(legs):
        is_last = i == len(legs) - 1
        flag = FLAG_COMPOUND_LAST if is_last else FLAG_COMPOUND_MIDDLE
        if split_side == "debit":
            debit_entry = leg.debit
            credit_entry = _placeholder()
            credit_entry.amount = leg.debit.amount
        else:
            credit_entry = leg.credit
            debit_entry = _placeholder()
            debit_entry.amount = leg.credit.amount

        rows.append(
            YayoiOutputRow(
                flag=flag,
                denpyo_no=denpyo_no,
                closing_flag=leg.closing_flag,
                transaction_date=leg.transaction_date,
                debit=debit_entry,
                credit=credit_entry,
                description=leg.description,
                row_type=TYPE_COMPOUND,
                memo=leg.memo,
            )
        )

    return rows


def build_all_vouchers(legs: list[LegRow], start_denpyo_no: int = 1) -> list[YayoiOutputRow]:
    """全LegRowから、伝票Noを自動採番しつつ全出力行を組み立てる。

    伝票Noは下書き側の値を一切信用せず、voucher_idの初出順に連番で採番する
    (弥生インポート形式.txtの実データで伝票No重複による不整合が確認されたため)。
    """
    groups = group_legs_by_voucher(legs)
    all_rows: list[YayoiOutputRow] = []
    denpyo_no = start_denpyo_no
    for voucher_id, group in groups.items():
        all_rows.extend(build_voucher_rows(voucher_id, group, denpyo_no))
        denpyo_no += 1
    return all_rows
