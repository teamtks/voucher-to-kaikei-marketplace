"""生成前後の検証ロジック。

方針: 金額や科目に関わる不整合は例外(ValidationError)でジェネレート処理を
中止する(ハードエラー)。参考データ上不明な科目・税区分など、取り込み自体は
可能だが要確認な事項は warnings として返し、呼び出し側(cli)で表示する。
"""
from collections import defaultdict

from .models import FLAG_COMPOUND_FIRST, FLAG_COMPOUND_LAST, PLACEHOLDER_ACCOUNT, YayoiOutputRow
from .voucher_builder import LegRow

# 弥生会計の仕様: 摘要欄は全角32文字まで(CP932で1文字1〜2バイト換算、64バイトまで)。
DESCRIPTION_MAX_BYTES = 64

# CP932の機種依存文字(NEC選定IBM拡張文字・IBM拡張文字)の範囲。実データで「﨑」
# (U+FA11, CP932では0xED95)が原因の不具合が実際に確認されている。この2領域は
# 丸数字等の記号ではなく、ほぼ人名・地名専用の異体字(髙・﨑・德など)で構成されて
# いるため、機械的に標準字体へ置き換えると実在する方の氏名表記を書き換えてしまう
# 恐れがある。そのため自動置換はせず、検出したら生成を止めて人に確認してもらう
# (このスキルの「読み取り内容を鵜呑みにせず人が確認する」という基本方針に沿う)。
#
# なお「NEC選定IBM拡張」と「IBM拡張」はCP932上、同じ文字集合を指す重複領域であり、
# Python標準の`str.encode("cp932")`は常に前者(0xED-0xEE側)を選ぶため、実際の
# Unicode文字列からはIBM拡張側の生バイト(0xFA-0xFC)には到達しない。それでも
# 判定漏れが無いよう両方の範囲を残している。
_MACHINE_DEPENDENT_RANGES = (
    (0xED40, 0xEEFC),  # NEC選定IBM拡張文字
    (0xFA40, 0xFC4B),  # IBM拡張文字
)


def find_machine_dependent_chars(text: str) -> list[str]:
    """CP932の機種依存文字(NEC選定IBM拡張・IBM拡張)を含む文字を検出する。

    見つかった文字を出現順に返す(無ければ空リスト)。
    """
    found = []
    for ch in text:
        try:
            b = ch.encode("cp932")
        except UnicodeEncodeError:
            continue
        if len(b) != 2:
            continue
        value = (b[0] << 8) | b[1]
        if any(lo <= value <= hi for lo, hi in _MACHINE_DEPENDENT_RANGES):
            found.append(ch)
    return found


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
        desc_bytes = len(row.description.encode("cp932", errors="replace"))
        if desc_bytes > DESCRIPTION_MAX_BYTES:
            errors.append(
                f"伝票No {row.denpyo_no}: 摘要が全角32文字(64バイト)を超えています"
                f"({desc_bytes}バイト): {row.description}"
            )
        for field_name, value in (
            ("借方勘定科目", row.debit.account),
            ("借方補助科目", row.debit.sub_account),
            ("貸方勘定科目", row.credit.account),
            ("貸方補助科目", row.credit.sub_account),
            ("摘要", row.description),
            ("仕訳メモ", row.memo),
        ):
            bad_chars = find_machine_dependent_chars(value)
            if bad_chars:
                errors.append(
                    f"伝票No {row.denpyo_no}: 「{field_name}」に機種依存文字が含まれています"
                    f"({''.join(sorted(set(bad_chars)))})。環境によって文字化けする恐れが"
                    "あるため、正しい字体か確認したうえで、標準的な字体に置き換えるか"
                    "そのままで問題ないか判断してください"
                )
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

        # split_side="manual"(自由な複合仕訳)は非分割側の合計という概念が
        # そもそも成立しないため、このチェックは自動集計モードの伝票にのみ行う。
        if any(r.built_manually for r in group_rows):
            continue

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
