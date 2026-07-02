"""西暦⇔和暦(弥生形式 "R.06/07/01" 表記)の変換ユーティリティ。"""
import re
from datetime import date

# (元号記号, 元号開始日) を新しい順に並べる
_ERAS = [
    ("R", date(2019, 5, 1)),   # 令和
    ("H", date(1989, 1, 8)),   # 平成
]
_ERA_START_YEAR = {"R": 2018, "H": 1988}

_YAYOI_DATE_RE = re.compile(r"^([RrHh])\.?\s*(\d{1,2})/(\d{1,2})/(\d{1,2})$")
_ISO_DATE_RE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")


def to_yayoi_date_str(d: date) -> str:
    """date を弥生インポート形式の日付表記 "R.06/07/01" に変換する。"""
    for symbol, start in _ERAS:
        if d >= start:
            era_year = d.year - start.year + 1
            return f"{symbol}.{era_year:02d}/{d.month:02d}/{d.day:02d}"
    raise ValueError(f"対応していない元号の日付です: {d.isoformat()}")


def parse_date_str(text: str) -> date:
    """下書きExcelの取引日付欄("R.06/07/01" またはISO形式)をdateに変換する。"""
    text = (text or "").strip()
    m = _YAYOI_DATE_RE.match(text)
    if m:
        era = m.group(1).upper()
        era_year, month, day = int(m.group(2)), int(m.group(3)), int(m.group(4))
        return date(_ERA_START_YEAR[era] + era_year, month, day)
    m = _ISO_DATE_RE.match(text)
    if m:
        year, month, day = (int(x) for x in m.groups())
        return date(year, month, day)
    raise ValueError(f"日付として解釈できません: {text!r}")
