"""PaddleOCR(日本語モデル)のラッパー。

paddleocr 2.7.3 + paddlepaddle 2.6.2 の組み合わせで動作確認済み(新しい3.x系は
この開発機のCPU/oneDNN実行環境で動作しなかったため採用していない。
requirements.txtのコメント参照)。
"""
from PIL import Image


def _box_top(box) -> float:
    return min(p[1] for p in box)


def _box_bottom(box) -> float:
    return max(p[1] for p in box)


def _box_left(box) -> float:
    return min(p[0] for p in box)


def _merge_boxes(boxes: list) -> list:
    xs = [p[0] for b in boxes for p in b]
    ys = [p[1] for b in boxes for p in b]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _group_into_rows(items: list[dict]) -> list[dict]:
    """実際の請求書PDFで、日付の各要素("2026年""7月""2日"等)がPaddleOCRの検出順で
    左右がバラバラに返ってくる事例が確認された。上端Y座標のみでの単純ソートでは
    直せないため、縦方向に重なる(同じ行とみなせる)box同士をまとめ、行内はX座標で
    正しく左から右に並べ直す。

    itemsは [{"text":str, "score":float, "box":[[x,y]x4]}, ...]。
    """
    boxes_sorted = sorted(items, key=lambda l: _box_top(l["box"]))
    rows: list[list[dict]] = []
    row_top = row_bottom = None
    for item in boxes_sorted:
        top, bottom = _box_top(item["box"]), _box_bottom(item["box"])
        center = (top + bottom) / 2
        if rows and row_top is not None and row_top <= center <= row_bottom:
            rows[-1].append(item)
            row_top = min(row_top, top)
            row_bottom = max(row_bottom, bottom)
        else:
            rows.append([item])
            row_top, row_bottom = top, bottom

    merged: list[dict] = []
    for row in rows:
        row.sort(key=lambda l: _box_left(l["box"]))
        text = "".join(l["text"] for l in row)
        score = min(l["score"] for l in row)
        box = _merge_boxes([l["box"] for l in row])
        merged.append({"text": text, "score": score, "box": box})
    return merged


class JapaneseOCR:
    def __init__(self, lang: str = "japan"):
        from paddleocr import PaddleOCR  # 起動時間がかかるため遅延importする

        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)

    def recognize_lines(self, image: Image.Image) -> list[dict]:
        """1画像をOCRし、[{"text":str, "score":float, "box":[[x,y]x4]}, ...] を返す。

        同じ行(縦方向に重なるboxグループ)は結合してX座標順(左→右)に並べ替え、
        行同士は上から下の順に並べる。
        """
        import numpy as np

        array = np.array(image.convert("RGB"))
        result = self._ocr.ocr(array, cls=True)
        raw_items: list[dict] = []
        if result and result[0]:
            for box, (text, score) in result[0]:
                raw_items.append({"text": text, "score": float(score), "box": box})
        return _group_into_rows(raw_items)

    def recognize_text(self, image: Image.Image) -> str:
        return "\n".join(line["text"] for line in self.recognize_lines(image))
