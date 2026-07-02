"""証憑画像(PDF/JPG/PNG)の宛名(「様」「御中」の行)を検出し、黒塗りしてから
保存するスクリプト。

【重要】このスクリプトは情報漏洩対策の要となる処理である。Claudeが証憑を
読み取る前に必ずこのスクリプトを実行し、出力されたマスク済み画像だけを
Read等で開くこと。元のPDF/画像ファイルを直接Claudeに読み込ませてはならない。

宛名(自社名/請求先名)は、証憑を発行した取引先そのものではなく、証憑の
送り先(＝自社)の名前であることが多いため、これを黒塗りすることで、
取引先分析に不要な自社の識別情報が外部に渡ることを防ぐ。

使い方:
    python mask_addressee.py <入力PDF/JPG/PNG> <出力先フォルダ>

出力: 入力ファイル名に "_masked_pageN.png" を付けたファイルを出力先フォルダに保存する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw

from lib.ocr_engine import JapaneseOCR
from lib.pdf_rasterize import rasterize_pdf

_ADDRESSEE_SUFFIXES = ("様", "御中")
_PADDING = 6  # 黒塗り範囲を検出boxより少し広めに取る(文字のはみ出し対策)


def _load_pages(path: Path) -> list[Image.Image]:
    if path.suffix.lower() == ".pdf":
        return rasterize_pdf(str(path), dpi=200)
    return [Image.open(path).convert("RGB")]


def mask_addressee_lines(image: Image.Image, ocr: JapaneseOCR) -> tuple[Image.Image, int]:
    """画像中の「様」「御中」で終わる行を検出し、黒塗りした画像を返す。

    戻り値は (マスク後画像, 黒塗りした行数)。行数が0の場合は宛名行を検出できな
    かったことを意味するので、呼び出し側でユーザーに確認を促すこと(検出漏れの
    まま元画像相当の内容がそのまま渡ってしまう事故を防ぐため)。
    """
    lines = ocr.recognize_lines(image)
    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    count = 0
    for line in lines:
        text = line["text"].strip()
        if text.endswith(_ADDRESSEE_SUFFIXES):
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
        note = f"宛名行を{count}件検出し黒塗りしました" if count > 0 else "宛名行(様/御中)は検出されませんでした"
        print(f"{out_path}  ({note})")


if __name__ == "__main__":
    main()
