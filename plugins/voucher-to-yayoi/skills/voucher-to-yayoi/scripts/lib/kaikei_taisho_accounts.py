"""会計大将CSV出力に必要な「勘定科目名 → 会計大将の科目コード」対応表の読み込み。

弥生会計と異なり、会計大将のCSV取込形式は勘定科目を名称ではなく数値コードで
指定する。このコードは案件(顧問先)ごとに異なる独自の体系のため、スキル本体に
固定で埋め込むことはできない。案件フォルダの「参考資料ファイル」に、
以下の形式のJSONファイル(例: 会計大将科目コード表.json)を用意してもらい、
そのパスを generate_kaikei_taisho.py に渡す。

{
  "fiscal_start_month": 2,
  "accounts": {
    "旅費交通費": {"code": "636", "cash_flow_type": "2", "cash_flow_code": "18"},
    "現金":       {"code": "111"},
    "代表者借入金": {"code": "314", "cash_flow_type": "2", "cash_flow_code": "40"}
  }
}

- "fiscal_start_month": その会社の会計年度が何月始まりか(1-12)。会計大将の
  CSVは各行に「月度コード」(四半期*10+四半期内の月番号。例: 期首月=1,2,3 →
  次の3か月=11,12,13 → ...)を持つため、期首月が分からないと計算できない。
  勘定科目一覧表や総勘定元帳など、その会社の実際の会計期間から確認すること
  (安易に2月始まりだと仮定しないこと)。
- "cash_flow_type" / "cash_flow_code": 資金繰り(資金収支)表での分類。
  会計大将のエクスポートCSVでは「資金繰コード」「資金繰名」として出力される
  項目にあたり、実データ解析では **現金・預金の側ではなく、その相手科目
  (費用・収益・債権債務などの「理由」側の科目)に紐づいている** ことが
  確認できている(例: 手数料を現金/A銀行/B銀行のどれで払っても常に同じ
  コードになる)。cash_flow_type は 1=入金 / 2=出金。cash_flow_code は
  資金繰り区分の番号(例: 18=販売管理費、15=人件費、3=売掛金入金)で、
  科目コードから機械的に導出できないため、会社ごとの実データ(既存の
  会計大将CSVエクスポート等)から実例を探して確認する必要がある。
  設定しなかった科目は共に"0"(資金繰り対象外)として扱われる。

なお、旧バージョンではこの2項目を "fund_type_code" / "fund_ledger_id" と呼び、
現金・預金側の科目に設定する想定になっていた(実データの解析が不十分だった
ための誤り)。互換のため旧名でも読み込めるようにしてあるが、値は上記の
「相手科目側に付ける」考え方で設定し直すこと。
"""
import json
from dataclasses import dataclass
from pathlib import Path


class AccountCodeError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class AccountCode:
    code: str
    cash_flow_type: str = "0"
    cash_flow_code: str = "0"

    @property
    def has_cash_flow(self) -> bool:
        return self.cash_flow_type != "0" or self.cash_flow_code != "0"


@dataclass
class AccountCodeTable:
    fiscal_start_month: int
    accounts: dict[str, AccountCode]

    def lookup(self, account_name: str) -> AccountCode:
        try:
            return self.accounts[account_name]
        except KeyError:
            raise AccountCodeError(
                [f"科目コード表に「{account_name}」のコードが定義されていません"]
            )


def load_account_code_table(path: str) -> AccountCodeTable:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    errors = []
    fiscal_start_month = raw.get("fiscal_start_month")
    if not isinstance(fiscal_start_month, int) or not (1 <= fiscal_start_month <= 12):
        errors.append(
            f"{path}: fiscal_start_month(1-12の整数、会計年度の開始月)が正しく指定されていません"
        )

    accounts_raw = raw.get("accounts")
    if not isinstance(accounts_raw, dict) or not accounts_raw:
        errors.append(f"{path}: accounts(科目コードの対応表)が空、または存在しません")
        accounts_raw = {}

    accounts: dict[str, AccountCode] = {}
    for name, entry in accounts_raw.items():
        if not isinstance(entry, dict) or "code" not in entry:
            errors.append(f"{path}: 科目「{name}」に code が指定されていません")
            continue
        accounts[name] = AccountCode(
            code=str(entry["code"]),
            # 旧名(fund_type_code / fund_ledger_id)も読めるようにしておく。
            cash_flow_type=str(
                entry.get("cash_flow_type", entry.get("fund_type_code", "0"))
            ),
            cash_flow_code=str(
                entry.get("cash_flow_code", entry.get("fund_ledger_id", "0"))
            ),
        )

    if errors:
        raise AccountCodeError(errors)

    return AccountCodeTable(fiscal_start_month=fiscal_start_month, accounts=accounts)
