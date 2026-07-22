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
- インボイス登録番号(T+13桁)
- 金融機関名・支店名(通帳等)
- 店番・口座番号
- カード会社名・カード番号(クレジットカード明細等)

使い方:
    python mask_addressee.py <入力PDF/JPG/PNG> <出力先フォルダ>

出力: 入力ファイル名に "_masked_pageN.png" を付けたファイルを出力先フォルダに保存する。
"""
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
_INVOICE_NO_RE = re.compile(r"T\d{13}")
_POSTAL_RE = re.compile(r"〒?\s?\d{3}-\d{4}")
_ADDRESS_SUFFIX_RE = re.compile(r"\d+(丁目|番地|号)")
_BANK_NAME_RE = re.compile(r".+(銀行|信用金庫|信用組合|労働金庫|農業協同組合)")
_BRANCH_NAME_RE = re.compile(r".+(支店|出張所)")
_BRANCH_NO_RE = re.compile(r"店番[:：]?\s*\d{1,4}")
_ACCOUNT_NO_RE = re.compile(r"(口座番号|口座No\.?)[:：]?\s*\d{4,10}")
_ACCOUNT_PLAIN_RE = re.compile(r"口座\s*[:：]?\s*(普通|当座|定期)?\s*\d{4,10}")
_CARD_COMPANY_RE = re.compile(r".+(カード株式会社|カード\(株\))")
_CARD_NO_RE = re.compile(r"(\d{4}[\s-]){3}\d{4}")


def _is_sensitive_line(text: str) -> bool:
    """自社(依頼主)を特定できる情報を含む行かどうかを判定する。"""
    if text.endswith(_ADDRESSEE_SUFFIXES):
        return True
    if _PHONE_RE.search(text):
        return True
    if _INVOICE_NO_RE.search(text):
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


def _load_pages(path: Path) -> list[Image.Image]:
    if path.suffix.lower() == ".pdf":
        return rasterize_pdf(str(path), dpi=200)
    return [Image.open(path).convert("RGB")]


def mask_addressee_lines(image: Image.Image, ocr: JapaneseOCR) -> tuple[Image.Image, int]:
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
        if _is_sensitive_line(text):
            xs = [p[0] for p in line["box"]]
            ys = [p[1] for p in line["box"]]
            x0, x1 = min(xs) - _PADDING, max(xs) + _PADDING
            y0, y1 = min(ys) - _PADDING, max(ys) + _PADDING
            draw.rectangle([x0, y0, x1, y1], fill="black")
            count += 1
    return masked, count


def main():
    if len(sys.argv) != 3:
        print("使い方: python mask_addressee.py <入力PDF/JPG/PNG> <出力先フォルダ>")
        raise SystemExit(1)

    input_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    ocr = JapaneseOCR()
    pages = _load_pages(input_path)

    for i, page in enumerate(pages, start=1):
        masked, count = mask_addressee_lines(page, ocr)
        out_path = output_dir / f"{input_path.stem}_masked_page{i}.png"
        masked.save(out_path)
        note = f"自社を特定できる情報を{count}件検出し黒塗りしました" if count > 0 else "自社を特定できる情報(宛名/住所/電話番号/口座情報等)は検出されませんでした"
        print(f"{out_path}  ({note})")


if __name__ == "__main__":
    main()
