"""PyMuPDF(fitz)でPDFの各ページをOCR用の画像にラスタライズする。"""
import fitz  # PyMuPDF
from PIL import Image


def rasterize_pdf(path: str, dpi: int = 300) -> list[Image.Image]:
    """PDFの各ページをPIL.Imageのリストとして返す。"""
    images: list[Image.Image] = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix)
            mode = "RGB" if pix.n < 4 else "RGBA"
            image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            if mode == "RGBA":
                image = image.convert("RGB")
            images.append(image)
    return images
