"""証憑画像(PDF/JPG/PNG)から、自社(依頼主)を特定できる情報を検出して黒塗りして
から保存するスクリプト。

【重要】このスクリプトは情報漏洩対策の要となる処理である。Claudeが証憑を
読み取る前に必ずこのスクリプトを実行し、出力されたマスク済み画像だけを
Read等で開くこと。元のPDF/画像ファイルを直接Claudeに読み込ませてはならない。

黒塗りの対象は、証憑を発行した取引先そのものの情報ではなく、証憑の送り先
(＝自社)や、通帳・クレジットカード明細に記載される自社の口座・カード情報など、
「自社を特定できる情報」である。これを黒塗りすることで、取引先分析に不要な
自社の識別情報が外部に渡ることを防ぐ。具体的には以下を検出・黒塗りする:

- 宛名(「様」「御中」で終わる行) … 常に
- 自社のインボイス登録番号(--own-invoice-no で指定した番号のみ) … 常に
- 住所(都道府県名を含む行、郵便番号)・電話番号 … **宛名の近くにある場合のみ**
- 金融機関名・支店名・店番・口座番号・カード会社名・カード番号
  … **通帳やカード明細のようにそれが自社のものである書類か、宛名の近くの場合のみ**

住所・電話・口座に条件を付けているのは、これらが文字の見た目だけでは「自社のもの」か
「取引先のもの」か区別できないためである。レシート・領収証には支払先(店舗)の住所と
電話番号が必ず印字されており、条件なしで黒塗りすると支払先の情報まで消してしまう。
実際に、支払先の名称や住所が黒塗りされ、インボイス登録番号が読み取りにくくなる
事象が起きたため、書類内での位置(宛名との近さ)と書類の種類を手がかりに絞り込む。

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

# 区切りは、OCRがハイフンを重複して読む(「999--8888」)ことや、全角ダッシュ・
# 空白で印字されることがあるため、1〜2文字のゆらぎを許容する。実機のOCR結果で
# 「TEL045-999--8888」が検出できず自社の電話番号が黒塗りされない事象を確認済み。
_PHONE_SEP = r"[-‐‑‒–—―ー−\s]{1,2}"
_PHONE_RE = re.compile(rf"0\d{{1,4}}{_PHONE_SEP}\d{{1,4}}{_PHONE_SEP}\d{{3,4}}")
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


def _is_addressee_line(text: str) -> bool:
    return text.endswith(_ADDRESSEE_SUFFIXES)


def _has_address_or_contact(text: str) -> bool:
    """住所・電話番号・郵便番号のいずれかを含む行か。

    これらは「自社のものか取引先のものか」が文字だけでは区別できない。
    レシートや領収証には支払先(店舗)の住所・電話が必ず印字されるため、
    これだけを根拠に黒塗りすると取引先の情報まで消してしまう。
    実際に、支払先の名称や住所が黒塗りされてインボイス番号が読み取りにくく
    なる事象が起きたため、後述の「自社の情報が書かれている範囲」の中に
    ある場合だけ黒塗りする。
    """
    if _PHONE_RE.search(text):
        return True
    if _POSTAL_RE.search(text):
        return True
    if any(pref in text for pref in _PREFECTURES):
        return True
    if _ADDRESS_SUFFIX_RE.search(text):
        return True
    return False


def _has_account_info(text: str) -> bool:
    """口座・カードに関する情報を含む行か(通帳・カード明細で使う)。"""
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


# 通帳・クレジットカード明細のように、書かれている口座・カード情報がそもそも
# 自社のものである書類かどうかを判断するための手がかり。
_ACCOUNT_DOCUMENT_HINTS = (
    "通帳", "お預り金額", "お引出し", "差引残高", "繰越",
    "ご利用代金明細", "カードご利用", "お支払い金額", "ご請求金額合計",
)

# 宛名(自社)から縦方向にこの割合の範囲内を「自社の情報が書かれている範囲」と
# みなす。領収証・請求書では、宛名とその住所は近接して印字され、発行者(取引先)の
# 住所・電話は離れた位置(下部や右側)に印字されるという体裁を利用する。
#
# 実際の領収証の体裁を再現して測ったところ、自社側は宛名から0.06〜0.12、
# 発行者(支払先)側は0.66以上と、はっきり差が付いた。自社の情報を取りこぼす方が
# 影響が大きいので、その間で自社側に余裕を持たせた値にしている。
_OWN_BLOCK_VERTICAL_RATIO = 0.25


def _box_center_y(box) -> float:
    return sum(p[1] for p in box) / len(box)


def looks_like_account_document(texts: "list[str]") -> bool:
    """通帳・カード明細など、口座やカードの情報が自社のものである書類か。

    レシートや領収証では「○○支店」が支払先の店舗名の一部だったり、振込先として
    取引先の口座が書かれていたりするため、口座・カード関連の検出をそのまま
    適用すると取引先の情報まで黒塗りしてしまう。
    """
    joined = "".join(texts)
    return any(hint in joined for hint in _ACCOUNT_DOCUMENT_HINTS)


def _own_block_centers(lines: "list[dict]") -> "list[float]":
    """宛名行(自社宛)の縦位置。ここを起点に「自社の情報の範囲」を決める。"""
    return [
        _box_center_y(line["box"])
        for line in lines
        if _is_addressee_line(line["text"].strip())
    ]


def _is_in_own_block(box, own_centers: "list[float]", image_height: int) -> bool:
    if not own_centers:
        return False
    limit = image_height * _OWN_BLOCK_VERTICAL_RATIO
    y = _box_center_y(box)
    return any(abs(y - c) <= limit for c in own_centers)


def should_mask_line(
    text: str,
    *,
    box,
    own_centers: "list[float]",
    image_height: int,
    is_account_document: bool,
    own_invoice_nos: "frozenset[str]" = frozenset(),
) -> bool:
    """この行を黒塗りすべきか判断する。

    文字の見た目だけでは「自社の情報」か「取引先の情報」かを区別できないため、
    書類の中での位置と種類も手がかりにする:

    - 宛名(様/御中)と、自社と分かっている登録番号 → 常に黒塗り
    - 住所・電話・郵便番号 → 宛名の近く(自社の情報が書かれている範囲)のみ
      黒塗り。レシートや領収証に必ず印字される支払先の住所・電話を消さないため
    - 口座・カード情報 → 通帳やカード明細のように、それが自社のものである書類か、
      宛名の近くにある場合のみ黒塗り
    """
    if _is_addressee_line(text):
        return True
    if _contains_own_invoice_no(text, own_invoice_nos):
        return True

    in_own_block = _is_in_own_block(box, own_centers, image_height)
    if _has_address_or_contact(text):
        return in_own_block
    if _has_account_info(text):
        return is_account_document or in_own_block
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
    texts = [line["text"].strip() for line in lines]
    own_centers = _own_block_centers(lines)
    is_account_doc = looks_like_account_document(texts)

    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    count = 0
    for line in lines:
        text = line["text"].strip()
        if should_mask_line(
            text,
            box=line["box"],
            own_centers=own_centers,
            image_height=image.height,
            is_account_document=is_account_doc,
            own_invoice_nos=own_invoice_nos,
        ):
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
