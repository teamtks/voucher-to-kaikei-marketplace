"""弥生会計インポート形式の生成に使うデータモデル。"""
from dataclasses import dataclass
from datetime import date

# 「複合」プレースホルダー行に使う固定値(弥生インポート形式.txtの実データから確認済み)
PLACEHOLDER_ACCOUNT = "複合"
PLACEHOLDER_TAX_CATEGORY = "対象外"

# 単純仕訳(1行完結)の識別フラグ・タイプ
FLAG_SIMPLE = "2000"
TYPE_SIMPLE = "0"

# 複合仕訳(伝票内で1行のみ)の識別フラグ・タイプ
# 弥生インポート形式.txtには「2110→2101」の2行構成の複合仕訳も存在するため、
# 複合仕訳は必ず先頭=2110・最終=2101、中間行(0件以上)は2100とする。
FLAG_COMPOUND_FIRST = "2110"
FLAG_COMPOUND_MIDDLE = "2100"
FLAG_COMPOUND_LAST = "2101"
TYPE_COMPOUND = "3"


@dataclass
class AccountEntry:
    """勘定科目1行分(片側)の情報。"""
    account: str
    sub_account: str = ""
    department: str = ""
    tax_category: str = ""
    amount: int = 0
    tax_amount: int = 0


@dataclass
class LegRow:
    """下書きExcelの1行(1仕訳明細行)に対応する入力データ。

    1つのvoucher_idを複数のLegRowが共有する場合、借方または貸方のどちらか
    一方の科目情報が全行で一致している必要がある(その側が「非分割側」となり、
    もう一方が分割対象になる)。voucher_id内でLegRowが1件のみの場合は単純仕訳
    (識別フラグ2000)として出力される。
    """
    voucher_id: str
    leg_no: int
    transaction_date: date
    debit: AccountEntry
    credit: AccountEntry
    closing_flag: str = ""  # "" または "本決"
    description: str = ""  # 摘要
    memo: str = ""  # 仕訳メモ
    # 複合仕訳(1伝票内にLegRowが複数件)の場合、どちらの側が「分割対象」かを
    # 明示する。借方・貸方の科目情報からどちらが単一の非分割側か自動判定できる
    # 場合は省略可(None)。分割側の全明細が偶然同じ科目・税区分になっている等、
    # 自動判定できない場合はレビュー側で明示する必要がある。
    # "manual"を指定した場合、各明細のdebit/credit(「複合」プレースホルダーを
    # 含む)をそのまま出力行にする(自動集計・自動判定を一切行わない)。給与仕訳の
    # ように、実科目が現れる側が明細ごとに入れ替わり、非分割側の合計と分割側の
    # 合計が一致しないような自由な複合仕訳を表現する場合に使う。この場合、
    # 「複合」プレースホルダーが必要な明細には呼び出し側が事前にAccountEntry
    # (account="複合", tax_category="対象外", amount=その明細の金額)を設定して
    # おく必要がある。
    split_side: str | None = None  # "debit" / "credit" / "manual"


@dataclass
class YayoiOutputRow:
    """弥生インポート形式の1行(25列)に対応する出力データ。"""
    flag: str
    denpyo_no: int
    closing_flag: str
    transaction_date: date
    debit: AccountEntry
    credit: AccountEntry
    description: str
    row_type: str
    memo: str = ""
    number: str = ""
    due_date: str = ""
    source: str = ""
    tag1: str = "0"
    tag2: str = "0"
    adjustment: str = "no"
    # split_side="manual"(自由な複合仕訳)で組み立てられた行かどうか。
    # validators側で、自動集計モード専用の合計チェックを除外する判定に使う。
    built_manually: bool = False
