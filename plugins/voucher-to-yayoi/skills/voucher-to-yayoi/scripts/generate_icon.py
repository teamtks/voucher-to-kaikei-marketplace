"""デスクトップショートカット用のアイコンを生成する。

かわいらしい・ポップな見た目にするため、フォント依存を避けて図形だけで
描いている。2種類を出力する:

- app_icon.ico    : ランチャー(仕訳.TeamTKS)用。暖色系の角丸背景＋白いレシート型。
- review_icon.ico : 仕訳チェック資料(HTML)用。ランチャーと一目で区別できるよう
                    寒色系(ティール)の背景にし、「確認する」ことが伝わるように
                    虫めがねを重ねている。

使い方:
    python generate_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
BG_COLOR = (255, 122, 89)       # 明るいコーラルオレンジ
BG_SHADOW = (235, 96, 64)       # 背景の縁取り(少し濃いめ)
RECEIPT_COLOR = (255, 255, 255)
LINE_COLOR = (255, 200, 180)
ACCENT_COLOR = (76, 205, 196)   # 合計行のアクセント(ティール)

# チェック資料用(ランチャーと配色を入れ替えて区別する)
REVIEW_BG_COLOR = (78, 205, 196)      # ティール
REVIEW_BG_SHADOW = (55, 182, 172)
REVIEW_LINE_COLOR = (183, 232, 228)
REVIEW_ACCENT_COLOR = (255, 122, 89)  # 虫めがね(コーラル)


def _rounded_square(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _receipt_shape(size: int, fill=RECEIPT_COLOR) -> Image.Image:
    """ジグザグの下端を持つ「レシート」形のマスク画像を作る。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin_x = int(size * 0.22)
    top = int(size * 0.14)
    zigzag_top = int(size * 0.82)
    zag_count = 6
    zag_w = (size - 2 * margin_x) / zag_count

    points = [(margin_x, top), (size - margin_x, top), (size - margin_x, zigzag_top)]
    for i in range(zag_count, 0, -1):
        x = margin_x + (i - 0.5) * zag_w
        y = zigzag_top + (size * 0.06 if i % 2 == 0 else 0)
        points.append((x, y))
    points.append((margin_x, zigzag_top))

    draw.polygon(points, fill=fill)
    return img


def build_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(SIZE * 0.04)
    _rounded_square(draw, (pad, pad, SIZE - pad, SIZE - pad), radius=int(SIZE * 0.22), fill=BG_SHADOW)
    _rounded_square(draw, (pad, 0, SIZE - pad, SIZE - 2 * pad), radius=int(SIZE * 0.22), fill=BG_COLOR)

    receipt = _receipt_shape(SIZE)
    img.alpha_composite(receipt)

    # レシート内のテキスト行(細い横棒)
    line_x0 = int(SIZE * 0.32)
    line_x1 = int(SIZE * 0.68)
    for i, y in enumerate([0.30, 0.38, 0.46]):
        draw.line([(line_x0, int(SIZE * y)), (line_x1, int(SIZE * y))], fill=LINE_COLOR, width=int(SIZE * 0.02))

    # 合計行(アクセントカラーの太い線)
    total_y = int(SIZE * 0.58)
    draw.line([(line_x0, total_y), (line_x1, total_y)], fill=ACCENT_COLOR, width=int(SIZE * 0.03))

    return img


def build_review_icon() -> Image.Image:
    """仕訳チェック資料(HTML)用のアイコン。書類＋虫めがねで「確認する」を表す。"""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(SIZE * 0.04)
    _rounded_square(draw, (pad, pad, SIZE - pad, SIZE - pad), radius=int(SIZE * 0.22), fill=REVIEW_BG_SHADOW)
    _rounded_square(draw, (pad, 0, SIZE - pad, SIZE - 2 * pad), radius=int(SIZE * 0.22), fill=REVIEW_BG_COLOR)

    img.alpha_composite(_receipt_shape(SIZE))

    # 書類内のテキスト行
    line_x0 = int(SIZE * 0.30)
    line_x1 = int(SIZE * 0.62)
    for y in (0.28, 0.35, 0.42):
        draw.line(
            [(line_x0, int(SIZE * y)), (line_x1, int(SIZE * y))],
            fill=REVIEW_LINE_COLOR, width=int(SIZE * 0.02),
        )

    # 虫めがね(円＋柄)。書類の右下に重ねる
    cx, cy, r = int(SIZE * 0.60), int(SIZE * 0.58), int(SIZE * 0.16)
    ring = int(SIZE * 0.045)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=REVIEW_ACCENT_COLOR, width=ring)
    handle_from = (cx + int(r * 0.72), cy + int(r * 0.72))
    handle_to = (cx + int(r * 1.65), cy + int(r * 1.65))
    draw.line([handle_from, handle_to], fill=REVIEW_ACCENT_COLOR, width=int(SIZE * 0.055))

    return img


_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)]


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    for filename, builder in (
        ("app_icon.ico", build_icon),
        ("review_icon.ico", build_review_icon),
    ):
        out_path = out_dir / filename
        builder().save(out_path, format="ICO", sizes=_ICO_SIZES)
        print(f"アイコンを生成しました: {out_path}")


if __name__ == "__main__":
    main()
