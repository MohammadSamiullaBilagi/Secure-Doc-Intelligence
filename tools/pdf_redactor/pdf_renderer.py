"""Renders PDF pages as QPixmap images using PyMuPDF."""

import fitz
from PyQt6.QtGui import QPixmap, QImage


def render_page(doc: fitz.Document, page_num: int, zoom: float = 2.0) -> QPixmap:
    """Render a single PDF page to a QPixmap at the given zoom level."""
    page = doc[page_num]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    img = QImage(
        pix.samples,
        pix.width,
        pix.height,
        pix.stride,
        QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888,
    )
    return QPixmap.fromImage(img)


def get_page_size(doc: fitz.Document, page_num: int) -> tuple:
    """Return (width, height) of a page in PDF points."""
    page = doc[page_num]
    rect = page.rect
    return rect.width, rect.height
