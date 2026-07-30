"""LegRow のリストから、会計大将のCSV取込形式を生成する。

弥生会計とは異なり会計大将のCSV仕様は公開されていないため、この実装は実際の
顧問先(会計大将利用)の実データを解析して判明した規則に基づく。解析に使った
実データは以下の2種類で、両者を突き合わせて規則を確定させている:

- 取込形式そのもの(44列・ヘッダ行なし)の実ファイル 5,375行
- 「仕訳日記帳」としてエクスポートされたCSV(40列・ヘッダ行あり)。こちらは
  税区分が「消費税」コード・「税率」表記・「税率区分」・「業種」といった
  人間可読な列に分かれているため、44列側の数値コードの意味を裏付けるのに使った。

確認済みの規則:
- 文字コード: CP932、改行: CRLF。ヘッダ行は無い。1行=44列(カンマ区切り)。
- 空文字列の列でも、列によって `""` (ダブルクォート2つ)で埋めるか、
  何も書かない(カンマとカンマの間が空)かが固定で決まっている
  (どちらでも取込は通ると思われるが、実データに合わせて再現している)。
- 列1(0始まり): 「月度コード」。会計年度の期首月を1か月目とする四半期番号を
  10の位、その四半期内の月番号(1-3)を1の位にした値
  (期首月,+1,+2月→1,2,3 / +3,+4,+5月→11,12,13 / +6,+7,+8月→21,22,23 /
  +9,+10,+11月→31,32,33)。実データから機械的に確認済み。
- 列6=借方科目コード、列17=貸方科目コード。
- 列10-13=借方側の税区分ブロック、列21-24=貸方側の税区分ブロック。
  税区分を持つ側にだけ値が入り、反対側は全て"0"になる。ブロックの内容は
  (取引区分, 業種, 課税フラグ, 0) で、取引区分は 1=売上系 / 2=仕入系、
  業種は簡易課税の事業区分(売上のみ1-6、仕入は0)、課税フラグは
  1=課税 / 0=非課税・不課税。
- 列28=金額、列29=消費税額、列30=消費税区分コード、列31=税率コード。
  詳細は _TAX_RULES を参照。
- 列33・列34: 資金繰り(資金収支)表での分類。**現金・預金の側ではなく、
  その相手科目に紐づく**(例: 手数料を現金/A銀行/B銀行のどれで払っても
  常に同じ値になる)。科目コードから導出できないため、
  kaikei_taisho_accounts.AccountCode の cash_flow_type / cash_flow_code を使う。

未対応(今後の拡張課題。呼び出し側でエラーにする):
- 1伝票内の明細が複数行になる仕訳(split_side指定のある複合仕訳)。
- 補助科目。会計大将は補助科目も数値コードで持つ(列7=借方補助、列18=貸方補助)が、
  その対応表を受け取る仕組みがまだ無いため、補助科目が指定されていたら
  黙って捨てるのではなくエラーにする。
"""
import math
from dataclasses import dataclass
from datetime import date

from .kaikei_taisho_accounts import AccountCode, AccountCodeTable
from .models import LegRow

# 税区分を持たない(消費税の対象として扱わない)ことを表す税区分名。
NO_TAX_CATEGORY = "対象外"


@dataclass(frozen=True)
class TaxRule:
    """税区分1つに対応する、会計大将CSVでの表現。

    kubun_code: 列30(消費税区分コード)。10=課税、30=非課税、40=不課税。
    rate_code:  列31(税率コード)。4=標準税率、5=軽減税率、0=税率なし。
    entry_kind: 税区分ブロックの1つ目。1=売上系、2=仕入系。
    business_type: 税区分ブロックの2つ目(簡易課税の事業区分)。売上のみ1-6。
    taxable:    税区分ブロックの3つ目。1=課税、0=非課税・不課税。
    rate:       消費税額の計算に使う(分子, 分母)。Noneなら消費税額は0。
    """

    kubun_code: str
    rate_code: str
    entry_kind: str
    business_type: str
    taxable: str
    rate: "tuple[int, int] | None"


def _sales_rules() -> dict[str, TaxRule]:
    """課税売上の税区分。弥生会計は事業区分(簡易課税の第○種)を税区分名の中に
    漢数字で埋め込むため(実データで「課税売上込六10%」を確認)、その表記に
    合わせて第一種〜第六種まで用意する。事業区分を使っていない(本則課税の)
    場合は漢数字なしの名前を使う。"""
    rules: dict[str, TaxRule] = {}
    kanji = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6"}
    for name, bt in list(kanji.items()) + [("", "0")]:
        rules[f"課税売上込{name}10%"] = TaxRule("10", "4", "1", bt, "1", (10, 110))
        rules[f"課税売上込{name}軽減8%"] = TaxRule("10", "5", "1", bt, "1", (8, 108))
        # 旧表記(軽減が事業区分より前に来る形)も受け付ける
        rules[f"課税売上込軽減{name}8%"] = TaxRule("10", "5", "1", bt, "1", (8, 108))
    return rules


def _purchase_rules() -> dict[str, TaxRule]:
    """課税仕入の税区分。弥生会計はインボイス区分を税区分名の末尾に付ける
    (実データで「課対仕入込10%適格」「課対仕入込軽減8%適格」を確認)。

    「適格」以外は免税事業者等からの課税仕入に対する経過措置で、控除できるのは
    消費税相当額の一定割合だけになる。会計大将の取込形式には経過措置を表す専用の
    列が無く(実データ5,375行で確認)、控除額は消費税額そのものとして表現される
    ため、割合を掛けた分子で税額を計算する:
      適格    → 10/110 (全額)
      区分80% → 8/110  (10/110の80%)
      区分50% → 5/110  (10/110の50%)
      控不    → 0      (控除できない)
    軽減8%も同様に 8/108 に割合を掛ける。
    """
    rules: dict[str, TaxRule] = {}
    # (インボイス区分, 控除割合の分子スケール)
    invoice_scales = [("適格", 1.0), ("区分80%", 0.8), ("区分50%", 0.5), ("控不", 0.0)]
    # (税率の表記, 税率コード, 分子, 分母)
    rates = [("10%", "4", 10, 110), ("軽減8%", "5", 8, 108)]
    for rate_name, rate_code, num, den in rates:
        for invoice, scale in invoice_scales:
            scaled = round(num * scale * 100)  # 分子を100倍して整数で保持する
            rate = None if scaled == 0 else (scaled, den * 100)
            rules[f"課対仕入込{rate_name}{invoice}"] = TaxRule(
                "10", rate_code, "2", "0", "1", rate
            )
    return rules


# 税区分名 → 会計大将CSVでの表現。
#
# 名前は弥生会計の税区分名に合わせている(同じ入力JSONを弥生用・会計大将用の
# どちらのジェネレータにも渡せるようにするため)。実データで実在を確認できた
# 弥生の税区分名は「対象外」「課対仕入込10%適格」「課対仕入込軽減8%適格」
# 「非課仕入」「非課売上」「課税売上込六10%」の6種類。
#
# 「不課税」は会計大将側の呼び方(弥生会計に同名の税区分は無く、弥生では
# 「対象外」を使う)。会計大将は「消費税の対象にならない損益取引(給与・
# 租税公課・海外での支出など)」を不課税(コード40)、「貸借科目間の振替など
# そもそも消費税区分を持たない取引」をコードなし(0)として区別しているため、
# 前者を表現できるようにこの名前を受け付ける。
# 課税仕入・課税売上の各税率とインボイス区分の組み合わせは、弥生会計の公式資料
# 「課税方式別税区分・税計算区分一覧」の命名規則(課税区分＋税入力区分＋税率
# ＋インボイス区分)に沿って組み立てている。本アプリは金額を税込で扱うため、
# 税入力区分は常に「込」。
_TAX_RULES: dict[str, TaxRule] = {
    "非課仕入": TaxRule("30", "0", "2", "0", "0", None),
    "非課売上": TaxRule("30", "0", "1", "0", "0", None),
    "不課税": TaxRule("40", "0", "2", "0", "0", None),
    **_purchase_rules(),
    **_sales_rules(),
}

_ZERO_BLOCK = ("0", "0", "0", "0")

_SUPPORTED_TAX_CATEGORIES = ", ".join([NO_TAX_CATEGORY, *_TAX_RULES])


class KaikeiTaishoBuildError(Exception):
    """会計大将CSVの組み立てに失敗した場合の例外。"""


def fiscal_period_code(d: date, fiscal_start_month: int) -> str:
    fiscal_month_index = (d.month - fiscal_start_month) % 12  # 0-11
    quarter = fiscal_month_index // 3       # 0-3
    month_in_quarter = fiscal_month_index % 3 + 1  # 1-3
    return str(quarter * 10 + month_in_quarter)


def _normalize_category(category: str) -> str:
    return (category or "").strip() or NO_TAX_CATEGORY


def _lookup_rule(category: str, voucher_id: str) -> TaxRule:
    try:
        return _TAX_RULES[category]
    except KeyError:
        raise KaikeiTaishoBuildError(
            f"伝票 {voucher_id}: 税区分「{category}」は会計大将CSV出力では未対応です"
            f"(対応済み: {_SUPPORTED_TAX_CATEGORIES})"
        )


def resolve_tax(leg: LegRow) -> tuple[tuple[str, ...], tuple[str, ...], str, str, int]:
    """1明細の税区分から、(借方ブロック, 貸方ブロック, 列30, 列31, 消費税額)を求める。

    税区分は借方・貸方のどちらか一方にだけ設定する(もう一方は「対象外」)。
    どちらに設定されているかで、税区分ブロックが入る側が決まる。
    """
    debit_category = _normalize_category(leg.debit.tax_category)
    credit_category = _normalize_category(leg.credit.tax_category)
    debit_taxed = debit_category != NO_TAX_CATEGORY
    credit_taxed = credit_category != NO_TAX_CATEGORY

    if debit_taxed and credit_taxed:
        raise KaikeiTaishoBuildError(
            f"伝票 {leg.voucher_id}: 借方(「{debit_category}」)と貸方(「{credit_category}」)の"
            "両方に税区分が指定されています。会計大将CSVでは片側のみに指定し、"
            f"もう片側は「{NO_TAX_CATEGORY}」にしてください"
        )

    if not debit_taxed and not credit_taxed:
        return _ZERO_BLOCK, _ZERO_BLOCK, "0", "0", 0

    category = debit_category if debit_taxed else credit_category
    entry = leg.debit if debit_taxed else leg.credit
    rule = _lookup_rule(category, leg.voucher_id)
    block = (rule.entry_kind, rule.business_type, rule.taxable, "0")

    explicit_tax = int(entry.tax_amount or 0)
    if rule.rate is None:
        if explicit_tax:
            raise KaikeiTaishoBuildError(
                f"伝票 {leg.voucher_id}: 税区分「{category}」は消費税額が発生しない区分ですが、"
                f"消費税額 {explicit_tax} が指定されています"
            )
        tax_amount = 0
    elif explicit_tax:
        # インボイス制度の経過措置(免税事業者等からの課税仕入。控除できるのは
        # 消費税相当額の80%)のように、税率から機械的に計算できない金額を
        # 人が確認して入れている場合は、その値をそのまま使う。
        tax_amount = explicit_tax
    else:
        num, den = rule.rate
        tax_amount = math.floor(int(entry.amount) * num / den)

    if debit_taxed:
        return block, _ZERO_BLOCK, rule.kubun_code, rule.rate_code, tax_amount
    return _ZERO_BLOCK, block, rule.kubun_code, rule.rate_code, tax_amount


def _cash_flow_codes(debit_code: AccountCode, credit_code: AccountCode) -> tuple[str, str]:
    """資金繰り分類コード(列33・列34)を求める。

    実データでは、現金・預金そのものではなく相手科目(費用・収益・債権債務など)
    にコードが紐づいているため、コードが設定されている側の科目から採る。
    """
    if debit_code.has_cash_flow and credit_code.has_cash_flow:
        raise KaikeiTaishoBuildError(
            "借方・貸方の両方の科目に資金繰り分類(cash_flow_type/cash_flow_code)が"
            "設定されています。資金繰り分類は現金・預金の相手科目側にだけ設定してください"
        )
    if debit_code.has_cash_flow:
        return debit_code.cash_flow_type, debit_code.cash_flow_code
    if credit_code.has_cash_flow:
        return credit_code.cash_flow_type, credit_code.cash_flow_code
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
    for side, entry in (("借方", leg.debit), ("貸方", leg.credit)):
        if (entry.sub_account or "").strip():
            raise KaikeiTaishoBuildError(
                f"伝票 {leg.voucher_id}: {side}に補助科目「{entry.sub_account}」が"
                "指定されていますが、会計大将CSV出力は補助科目に未対応です"
                "(会計大将は補助科目も数値コードで管理しており、その対応表を"
                "受け取る仕組みがまだありません)。補助科目を空欄にし、区別が"
                "必要な情報は摘要欄に書いてください"
            )

    debit_code = accounts.lookup(leg.debit.account)
    credit_code = accounts.lookup(leg.credit.account)

    amount = int(leg.debit.amount)
    debit_block, credit_block, kubun_code, rate_code, tax_amount = resolve_tax(leg)
    cash_flow_type, cash_flow_code = _cash_flow_codes(debit_code, credit_code)

    fields = [
        leg.transaction_date.strftime("%Y/%m/%d"),  # 0
        fiscal_period_code(leg.transaction_date, accounts.fiscal_start_month),  # 1
        "",                    # 2
        '""',                  # 3
        "0",                   # 4
        "1",                   # 5
        debit_code.code,       # 6
        "",                    # 7  借方補助コード(未対応)
        '""',                  # 8
        '""',                  # 9
        *debit_block,          # 10-13
        '""',                  # 14
        "0",                   # 15
        '""',                  # 16
        credit_code.code,      # 17
        "",                    # 18 貸方補助コード(未対応)
        '""',                  # 19
        '""',                  # 20
        *credit_block,         # 21-24
        '""',                  # 25
        "0",                   # 26
        '""',                  # 27
        str(amount),           # 28
        str(tax_amount),       # 29
        kubun_code,            # 30
        rate_code,             # 31
        "0",                   # 32
        cash_flow_type,        # 33
        cash_flow_code,        # 34
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
