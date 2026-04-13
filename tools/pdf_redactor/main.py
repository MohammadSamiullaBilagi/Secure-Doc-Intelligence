"""PDF Redaction Tool — Entry Point.

A standalone desktop application for permanently redacting sensitive information
(PAN, Aadhaar, names, bank account numbers) from PDF documents before uploading
to Legal AI Expert.

Usage:
    python main.py          # Run from source
    pdf_redactor.exe        # Run built executable

Build:
    pip install -r requirements.txt
    pyinstaller build.spec
"""

import sys

from PyQt6.QtWidgets import QApplication

from config import APP_NAME
from redactor_ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
