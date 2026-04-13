"""Applies permanent redactions to PDF using PyMuPDF.

Uses fitz.Page.add_redact_annot() + apply_redactions() which permanently
removes the underlying text data — same technology used by law firms and
government agencies. Even if someone removes the black box, the text is gone.
"""

import fitz


def apply_redactions(
    input_path: str,
    output_path: str,
    redactions: list,
) -> str:
    """Apply permanent redactions and save to output_path.

    Args:
        input_path: Path to the original PDF.
        output_path: Path to save the redacted PDF.
        redactions: List of dicts, each with:
            - page (int): 0-based page number
            - rect (list): [x0, y0, x1, y1] in PDF coordinates

    Returns:
        output_path on success.
    """
    doc = fitz.open(input_path)

    # Group redactions by page
    pages_to_redact = {}
    for r in redactions:
        pg = r["page"]
        if pg not in pages_to_redact:
            pages_to_redact[pg] = []
        pages_to_redact[pg].append(r["rect"])

    for page_num, rects in pages_to_redact.items():
        page = doc[page_num]
        for rect_coords in rects:
            rect = fitz.Rect(rect_coords)
            page.add_redact_annot(rect, fill=(0, 0, 0))  # Black fill
        page.apply_redactions()  # Permanently removes underlying text

    doc.save(output_path)
    doc.close()
    return output_path
