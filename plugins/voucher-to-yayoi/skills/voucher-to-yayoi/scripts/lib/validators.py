"""生成前後の検証ロジック。

方針: 金額や科目に関わる不整合は例外(ValidationError)でジェネレート処理を
中止する(ハードエラー)。参考データ上不明な科目・税区分など、取り込み自体は
可能だが要確認な事項は warnings として返し、呼び出し側(cli)で表示する。
"""
from collections import defaultdict

from .models import FLAG_COMPOUND_FIRST, FLAG_COMPOUND_LAST, PLACEHOLDER_ACCOUNT, YayoiOutputRow
from .voucher_builder import LegRow


class ValidationError(Exception):
    """複数件のエラーメッセージをまとめて保持する。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def validate_legs(legs: list[LegRow]) -> list[str]:
    """generate実行前の下書きデータに対する必須項目チェック。エラー文字列のリストを返す。"""
    errors: list[str] = []
    for leg in legs:
        loc = f"伝票 {leg.voucher_id} 明細{leg.leg_no}"
        if not leg.debit.account:
            errors.append(f"{loc}: 借方勘定科目が空欄です")
        if not leg.credit.account:
            errors.append(f"{loc}: 貸方勘定科目が空欄です")
        if leg.debit.amount <= 0:
            errors.append(f"{loc}: 借方金額が0以下です({leg.debit.amount})")
        if leg.debit.amount != leg.credit.amount:
            errors.append(
                f"{loc}: 借方金額({leg.debit.amount})と貸方金額({leg.credit.amount})が一致していません"
            )
        if leg.transaction_date is None:
            errors.append(f"{loc}: 取引日付が空欄です")
    return errors


def validate_output_rows(rows: list[YayoiOutputRow]) -> list[str]:
    """generate実行後の出力データに対する整合性チェック(生成ロジックの安全網)。"""
    errors: list[str] = []

    denpyo_no_dates: dict[int, set] = defaultdict(set)
    for row in rows:
        if row.debit.amount != row.credit.amount:
            errors.append(
                f"伝票No {row.denpyo_no}: 借方金額({row.debit.amount})と"
                f"貸方金額({row.credit.amount})が一致していません"
            )
        if not row.debit.account or not row.credit.account:
            errors.append(f"伝票No {row.denpyo_no}: 勘定科目が空欄の行があります")
        denpyo_no_dates[row.denpyo_no].add(row.transaction_date)

    for denpyo_no, dates in denpyo_no_dates.items():
        if len(dates) > 1:
            errors.append(f"伝票No {denpyo_no}: 同一伝票内で取引日付が一致していません")

    groups: dict[int, list[YayoiOutputRow]] = defaultdict(list)
    for row in rows:
        groups[row.denpyo_no].append(row)

    for denpyo_no, group_rows in groups.items():
        if len(group_rows) == 1:
            continue
        header = next((r for r in group_rows if r.flag == FLAG_COMPOUND_FIRST), None)
        details = [r for r in group_rows if r.flag != FLAG_COMPOUND_FIRST]
        if header is None:
            errors.append(f"伝票No {denpyo_no}: 複合仕訳の先頭行(識別フラグ2110)がありません")
            continue
        if not any(r.flag == FLAG_COMPOUND_LAST for r in group_rows):
            errors.append(f"伝票No {denpyo_no}: 複合仕訳の最終行(識別フラグ2101)がありません")

        header_amount = header.debit.amount if header.debit.account == PLACEHOLDER_ACCOUNT else header.credit.amount
        detail_total = 0
        for d in details:
            detail_total += d.debit.amount if d.debit.account != PLACEHOLDER_ACCOUNT else d.credit.amount
        if header_amount != detail_total:
            errors.append(
                f"伝票No {denpyo_no}: 先頭行の金額({header_amount})と"
                f"明細行の合計({detail_total})が一致していません"
            )

    return errors


def assert_valid(errors: list[str]) -> None:
    if errors:
        raise ValidationError(errors)
