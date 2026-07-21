"""会計大将CSV出力に必要な「勘定科目名 → 会計大将の科目コード」対応表の読み込み。

弥生会計と異なり、会計大将のCSV取込形式は勘定科目を名称ではなく数値コードで
指定する。このコードは案件(顧問先)ごとに異なる独自の体系のため、スキル本体に
固定で埋め込むことはできない。案件フォルダの「参考資料ファイル」に、
以下の形式のJSONファイル(例: 会計大将科目コード表.json)を用意してもらい、
そのパスを generate_kaikei_taisho.py に渡す。

{
  "fiscal_start_month": 2,
  "accounts": {
    "旅費交通費": {"code": "636"},
    "現金":       {"code": "111", "fund_type_code": "2", "fund_ledger_id": "18"},
    "代表者借入金": {"code": "314"}
  }
}

- "fiscal_start_month": その会社の会計年度が何月始まりか(1-12)。会計大将の
  CSVは各行に「月度コード」(四半期*10+四半期内の月番号。例: 期首月=1,2,3 →
  次の3か月=11,12,13 → ...)を持つため、期首月が分からないと計算できない。
  勘定科目一覧表や総勘定元帳など、その会社の実際の会計期間から確認すること
  (安易に2月始まりだと仮定しないこと)。
- "fund_type_code" / "fund_ledger_id": 現金・預金などの「資金科目」だけに
  設定する。会計大将は資金科目が絡む行に、通常の勘定科目コードとは別に
  資金管理用の内部コードを持たせている(実データ解析で確認済み)。この値は
  科目コードから機械的に導出できず、会社ごとの実データ(既存の会計大将CSV
  エクスポート等)から実例を探して確認するしかない。資金科目でない科目には
  設定不要(省略時は共に"0"として扱われる)。
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
    fund_type_code: str = "0"
    fund_ledger_id: str = "0"


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
            fund_type_code=str(entry.get("fund_type_code", "0")),
            fund_ledger_id=str(entry.get("fund_ledger_id", "0")),
        )

    if errors:
        raise AccountCodeError(errors)

    return AccountCodeTable(fiscal_start_month=fiscal_start_month, accounts=accounts)
