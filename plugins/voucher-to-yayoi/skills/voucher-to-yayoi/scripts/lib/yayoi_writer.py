"""YayoiOutputRow のリストを、弥生会計インポート形式のテキストへ変換・出力する。

弥生インポート形式.txt の実データから確認済みの出力仕様:
- 文字コード: CP932 (Shift-JIS系。半角カナ等の互換性のため "shift_jis" ではなく "cp932" を使う)
- 改行: CRLF
- 文字列項目は空文字列を含め必ずダブルクォートで囲む
- 数値項目(伝票No・金額・消費税額・タイプ)はクォートしない
"""
import codecs

from .models import YayoiOutputRow
from .wareki import to_yayoi_date_str


def _q(value: str) -> str:
    """文字列項目をダブルクォートで囲む(埋め込みクォートは""にエスケープ)。"""
    return '"' + str(value).replace('"', '""') + '"'


def _n(value) -> str:
    """数値項目(クォートなし)。"""
    return str(int(value))


def format_row(row: YayoiOutputRow) -> str:
    fields = [
        _q(row.flag),
        _n(row.denpyo_no),
        _q(row.closing_flag),
        _q(to_yayoi_date_str(row.transaction_date)),
        _q(row.debit.account),
        _q(row.debit.sub_account),
        _q(row.debit.department),
        _q(row.debit.tax_category),
        _n(row.debit.amount),
        _n(row.debit.tax_amount),
        _q(row.credit.account),
        _q(row.credit.sub_account),
        _q(row.credit.department),
        _q(row.credit.tax_category),
        _n(row.credit.amount),
        _n(row.credit.tax_amount),
        _q(row.description),
        _q(row.number),
        _q(row.due_date),
        _n(row.row_type),
        _q(row.source),
        _q(row.memo),
        _q(row.tag1),
        _q(row.tag2),
        _q(row.adjustment),
    ]
    return ",".join(fields)


def format_rows(rows: list[YayoiOutputRow]) -> str:
    """CRLF区切りの本文を組み立てる(末尾もCRLFで終端)。"""
    return "".join(format_row(row) + "\r\n" for row in rows)


def write_yayoi_file(rows: list[YayoiOutputRow], path: str) -> None:
    text = format_rows(rows)
    with codecs.open(path, "w", encoding="cp932", errors="strict") as f:
        f.write(text)
