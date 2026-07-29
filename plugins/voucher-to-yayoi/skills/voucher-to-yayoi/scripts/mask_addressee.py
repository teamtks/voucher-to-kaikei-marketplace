"""証憑画像(PDF/JPG/PNG)から、自社(依頼主)を特定できる情報を検出して黒塗りして
から保存するスクリプト。

【重要】このスクリプトは情報漏洩対策の要となる処理である。Claudeが証憑を
読み取る前に必ずこのスクリプトを実行し、出力されたマスク済み画像だけを
Read等で開くこと。元のPDF/画像ファイルを直接Claudeに読み込ませてはならない。

黒塗りの対象は、証憑を発行した取引先そのものの情報ではなく、証憑の送り先
(＝自社)や、通帳・クレジットカード明細に記載される自社の口座・カード情報など、
「自社を特定できる情報」である。これを黒塗りすることで、取引先分析に不要な
自社の識別情報が外部に渡ることを防ぐ。具体的には以下を検出・黒塗りする:

- 宛名(「様」「御中」で終わる行)
- 住所(都道府県名を含む行、郵便番号)
- 電話番号
- 金融機関名・支店名(通帳等)
- 店番・口座番号
- カード会社名・カード番号(クレジットカード明細等)
- 自社のインボイス登録番号(--own-invoice-no で指定した番号のみ)

インボイス登録番号については注意が必要である。領収書・請求書に印字されている
登録番号は通常**取引先(相手方)**のものであり、これは自社を特定する情報ではない。
むしろ摘要欄に記載する必要がある重要な情報なので、黒塗りしてはならない
(黒塗りするとClaudeが読み取れなくなる)。黒塗りするのは、自社発行の請求書の
控えなどに写り込んだ**自社自身の**登録番号だけであり、その番号が分かっている
場合に --own-invoice-no で明示的に指定する。

使い方:
    python mask_addressee.py <入力PDF/JPG/PNG> <出力先フォルダ> [--own-invoice-no T1234567890123 ...]

出力:
- "<入力ファイル名>_masked_pageN.png": 黒塗り済み画像。**Claudeが読み取るのはこれだけ。**
- "<入力ファイル名>_original_pageN.png": 黒塗り前のページ画像(入力がPDFの場合のみ)。
  手順5のチェック資料(利用者自身のブラウザでしか開かないHTML)に埋め込んで、
  利用者が証憑の全体を見比べて確認するためのもの。Claudeはこの画像を読み込まない。
  入力がJPG/PNGの場合は元ファイルそのものが使えるため出力しない。
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw

from lib.ocr_engine import JapaneseOCR
from lib.pdf_rasterize import rasterize_pdf

_ADDRESSEE_SUFFIXES = ("様", "御中")
_PADDING = 6  # 黒塗り範囲を検出boxより少し広めに取る(文字のはみ出し対策)

_PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)

_PHONE_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")
# 前後を数字で挟まれていない「3桁-4桁」だけを郵便番号とみなす。境界を付けないと、
# 「T 1234-567890123」のような長い数字列の一部にも一致してしまい、取引先の
# インボイス登録番号の行まで黒塗りされてしまう。
_POSTAL_RE = re.compile(r"〒?\s?(?<!\d)\d{3}-\d{4}(?!\d)")
_ADDRESS_SUFFIX_RE = re.compile(r"\d+(丁目|番地|号)")
_BANK_NAME_RE = re.compile(r".+(銀行|信用金庫|信用組合|労働金庫|農業協同組合)")
_BRANCH_NAME_RE = re.compile(r".+(支店|出張所)")
_BRANCH_NO_RE = re.compile(r"店番[:：]?\s*\d{1,4}")
_ACCOUNT_NO_RE = re.compile(r"(口座番号|口座No\.?)[:：]?\s*\d{4,10}")
_ACCOUNT_PLAIN_RE = re.compile(r"口座\s*[:：]?\s*(普通|当座|定期)?\s*\d{4,10}")
_CARD_COMPANY_RE = re.compile(r".+(カード株式会社|カード\(株\))")
_CARD_NO_RE = re.compile(r"(\d{4}[\s-]){3}\d{4}")


def normalize_invoice_no(text: str) -> str:
    """インボイス登録番号の比較用に、記号・空白を除いて大文字化する。

    OCRの結果は「T1234567890123」「登録番号: T 1234-567890123」のように
    区切り文字や空白が入りうるため、比較前に揺れを吸収する。
    """
    return re.sub(r"[^0-9A-Za-z]", "", text).upper()


def _contains_own_invoice_no(text: str, own_invoice_nos: "frozenset[str]") -> bool:
    if not own_invoice_nos:
        return False
    normalized = normalize_invoice_no(text)
    return any(no in normalized for no in own_invoice_nos)


def _is_sensitive_line(text: str, own_invoice_nos: "frozenset[str]" = frozenset()) -> bool:
    """自社(依頼主)を特定できる情報を含む行かどうかを判定する。

    own_invoice_nos には自社のインボイス登録番号を(正規化済みの形で)渡す。
    取引先の登録番号は自社を特定する情報ではなく、摘要欄に必要な情報なので
    黒塗りしない。
    """
    if text.endswith(_ADDRESSEE_SUFFIXES):
        return True
    if _PHONE_RE.search(text):
        return True
    if _contains_own_invoice_no(text, own_invoice_nos):
        return True
    if _POSTAL_RE.search(text):
        return True
    if any(pref in text for pref in _PREFECTURES):
        return True
    if _ADDRESS_SUFFIX_RE.search(text):
        return True
    if _BANK_NAME_RE.match(text):
        return True
    if _BRANCH_NAME_RE.match(text):
        return True
    if _BRANCH_NO_RE.search(text):
        return True
    if _ACCOUNT_NO_RE.search(text):
        return True
    if _ACCOUNT_PLAIN_RE.search(text):
        return True
    if _CARD_COMPANY_RE.match(text):
        return True
    if _CARD_NO_RE.search(text):
        return True
    return False


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def _load_pages(path: Path) -> list[Image.Image]:
    if _is_pdf(path):
        return rasterize_pdf(str(path), dpi=200)
    return [Image.open(path).convert("RGB")]


def mask_addressee_lines(
    image: Image.Image,
    ocr: JapaneseOCR,
    own_invoice_nos: "frozenset[str]" = frozenset(),
) -> tuple[Image.Image, int]:
    """画像中の、自社を特定できる情報を含む行を検出し、黒塗りした画像を返す。

    戻り値は (マスク後画像, 黒塗りした行数)。行数が0の場合は該当行を検出でき
    なかったことを意味するので、呼び出し側でユーザーに確認を促すこと(検出漏れの
    まま元画像相当の内容がそのまま渡ってしまう事故を防ぐため)。
    """
    lines = ocr.recognize_lines(image)
    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    count = 0
    for line in lines:
        text = line["text"].strip()
        if _is_sensitive_line(text, own_invoice_nos):
            xs = [p[0] for p in line["box"]]
            ys = [p[1] for p in line["box"]]
            x0, x1 = min(xs) - _PADDING, max(xs) + _PADDING
            y0, y1 = min(ys) - _PADDING, max(ys) + _PADDING
            draw.rectangle([x0, y0, x1, y1], fill="black")
            count += 1
    return masked, count


def main():
    parser = argparse.ArgumentParser(
        description="証憑画像から自社を特定できる情報を検出して黒塗りする"
    )
    parser.add_argument("input", help="入力PDF/JPG/PNGファイル")
    parser.add_argument("output_dir", help="出力先フォルダ")
    parser.add_argument(
        "--own-invoice-no",
        action="append",
        default=[],
        metavar="T1234567890123",
        help="自社のインボイス登録番号(分かっている場合のみ指定。複数回指定可)。"
        "取引先の登録番号は摘要欄に必要な情報なので黒塗りしない。",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    own_invoice_nos = frozenset(
        normalized
        for normalized in (normalize_invoice_no(no) for no in args.own_invoice_no)
        if normalized
    )

    ocr = JapaneseOCR()
    pages = _load_pages(input_path)
    # PDFはページ画像がこの場でしか手に入らないため、チェック資料用に黒塗り前の
    # 画像も保存する。JPG/PNGは元ファイルをそのまま使えるので保存しない。
    save_originals = _is_pdf(input_path)

    for i, page in enumerate(pages, start=1):
        if save_originals:
            original_path = output_dir / f"{input_path.stem}_original_page{i}.png"
            page.save(original_path)
            print(f"{original_path}  (黒塗り前・チェック資料用。Claudeは読み込まない)")

        masked, count = mask_addressee_lines(page, ocr, own_invoice_nos)
        out_path = output_dir / f"{input_path.stem}_masked_page{i}.png"
        masked.save(out_path)
        note = f"自社を特定できる情報を{count}件検出し黒塗りしました" if count > 0 else "自社を特定できる情報(宛名/住所/電話番号/口座情報等)は検出されませんでした"
        print(f"{out_path}  ({note})")


if __name__ == "__main__":
    main()
