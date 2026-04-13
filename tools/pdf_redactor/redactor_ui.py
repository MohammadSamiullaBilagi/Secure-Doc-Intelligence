"""Main window for the PDF Redaction Tool — PyQt6 GUI."""

import webbrowser
from pathlib import Path

import fitz
from PyQt6.QtWidgets import (
    QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QToolBar, QStatusBar, QFileDialog, QMessageBox, QLabel, QDockWidget,
    QListWidget, QListWidgetItem, QTextBrowser, QHBoxLayout, QWidget,
    QVBoxLayout, QPushButton,
)
from PyQt6.QtGui import QAction, QPen, QBrush, QColor, QKeySequence
from PyQt6.QtCore import Qt, QRectF, QPointF

from config import APP_NAME, APP_VERSION, UPLOAD_URL, WINDOW_WIDTH, WINDOW_HEIGHT, DEFAULT_ZOOM
from pdf_renderer import render_page
from redaction_engine import apply_redactions
from redaction_guide import GUIDE_HTML


class RedactionRect(QGraphicsRectItem):
    """A red semi-transparent rectangle drawn by the user for redaction."""

    def __init__(self, rect: QRectF, page: int):
        super().__init__(rect)
        self.page = page
        pen = QPen(QColor(220, 30, 30), 2)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(220, 30, 30, 80)))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)


class PDFGraphicsView(QGraphicsView):
    """Custom QGraphicsView that handles mouse drawing of redaction rectangles."""

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.drawing = False
        self.start_point = QPointF()
        self.current_rect = None
        self.main_window = parent

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.start_point = self.mapToScene(event.pos())
            self.current_rect = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing:
            current = self.mapToScene(event.pos())
            rect = QRectF(self.start_point, current).normalized()

            if self.current_rect:
                self.scene().removeItem(self.current_rect)

            self.current_rect = RedactionRect(rect, self.main_window.current_page)
            self.scene().addItem(self.current_rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            if self.current_rect:
                rect = self.current_rect.rect()
                if rect.width() > 5 and rect.height() > 5:
                    self.main_window.add_redaction(self.current_rect)
                else:
                    self.scene().removeItem(self.current_rect)
                self.current_rect = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    """Main application window for the PDF Redaction Tool."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self.doc = None
        self.file_path = None
        self.current_page = 0
        self.total_pages = 0
        self.zoom = DEFAULT_ZOOM
        self.redactions = []  # List of RedactionRect items

        self._setup_ui()
        self._setup_toolbar()
        self._setup_sidebar()
        self._setup_statusbar()

    def _setup_ui(self):
        self.scene = QGraphicsScene()
        self.view = PDFGraphicsView(self.scene, parent=self)
        self.setCentralWidget(self.view)

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Open PDF
        open_action = QAction("Open PDF", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self.open_pdf)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        # Page navigation
        self.prev_action = QAction("< Prev", self)
        self.prev_action.setShortcut(QKeySequence("Left"))
        self.prev_action.triggered.connect(self.prev_page)
        self.prev_action.setEnabled(False)
        toolbar.addAction(self.prev_action)

        self.page_label = QLabel(" Page 0/0 ")
        toolbar.addWidget(self.page_label)

        self.next_action = QAction("Next >", self)
        self.next_action.setShortcut(QKeySequence("Right"))
        self.next_action.triggered.connect(self.next_page)
        self.next_action.setEnabled(False)
        toolbar.addAction(self.next_action)

        toolbar.addSeparator()

        # Undo last
        undo_action = QAction("Undo Last Box", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(self.undo_last)
        toolbar.addAction(undo_action)

        # Clear all on page
        clear_action = QAction("Clear Page Boxes", self)
        clear_action.triggered.connect(self.clear_page_redactions)
        toolbar.addAction(clear_action)

        toolbar.addSeparator()

        # Apply & Save
        save_action = QAction("Apply & Save Redacted PDF", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.save_redacted)
        toolbar.addAction(save_action)

        toolbar.addSeparator()

        # Upload
        upload_action = QAction("Upload to Platform", self)
        upload_action.triggered.connect(self.open_upload_page)
        toolbar.addAction(upload_action)

        # Guide
        guide_action = QAction("Redaction Guide", self)
        guide_action.setShortcut(QKeySequence("F1"))
        guide_action.triggered.connect(self.show_guide)
        toolbar.addAction(guide_action)

    def _setup_sidebar(self):
        dock = QDockWidget("Redaction Boxes", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)

        container = QWidget()
        layout = QVBoxLayout(container)

        self.redaction_list = QListWidget()
        layout.addWidget(QLabel("Redactions:"))
        layout.addWidget(self.redaction_list)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected_redaction)
        layout.addWidget(delete_btn)

        dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Open a PDF to begin redacting.")

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return

        self.doc = fitz.open(path)
        self.file_path = path
        self.current_page = 0
        self.total_pages = len(self.doc)

        # Clear old redactions
        self.redactions.clear()
        self.redaction_list.clear()

        self._render_current_page()
        self._update_nav()
        self.statusbar.showMessage(f"Opened: {Path(path).name} ({self.total_pages} pages)")

    def _render_current_page(self):
        if not self.doc:
            return

        self.scene.clear()
        pixmap = render_page(self.doc, self.current_page, self.zoom)
        self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        # Re-draw existing redaction boxes for this page
        for r in self.redactions:
            if r.page == self.current_page:
                self.scene.addItem(r)

    def _update_nav(self):
        self.page_label.setText(f" Page {self.current_page + 1}/{self.total_pages} ")
        self.prev_action.setEnabled(self.current_page > 0)
        self.next_action.setEnabled(self.current_page < self.total_pages - 1)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_current_page()
            self._update_nav()

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_current_page()
            self._update_nav()

    def add_redaction(self, rect_item: RedactionRect):
        self.redactions.append(rect_item)
        r = rect_item.rect()
        item = QListWidgetItem(
            f"Page {rect_item.page + 1}: ({int(r.x())},{int(r.y())}) {int(r.width())}x{int(r.height())}"
        )
        self.redaction_list.addItem(item)
        self.statusbar.showMessage(f"Redaction box added. Total: {len(self.redactions)}")

    def undo_last(self):
        if not self.redactions:
            return
        last = self.redactions.pop()
        if last.scene():
            self.scene.removeItem(last)
        if self.redaction_list.count() > 0:
            self.redaction_list.takeItem(self.redaction_list.count() - 1)
        self.statusbar.showMessage(f"Undone. Remaining: {len(self.redactions)}")

    def clear_page_redactions(self):
        to_remove = [r for r in self.redactions if r.page == self.current_page]
        for r in to_remove:
            self.redactions.remove(r)
            if r.scene():
                self.scene.removeItem(r)
        # Rebuild list widget
        self.redaction_list.clear()
        for r in self.redactions:
            rect = r.rect()
            self.redaction_list.addItem(
                f"Page {r.page + 1}: ({int(rect.x())},{int(rect.y())}) {int(rect.width())}x{int(rect.height())}"
            )
        self.statusbar.showMessage(f"Cleared {len(to_remove)} boxes from page {self.current_page + 1}")

    def delete_selected_redaction(self):
        idx = self.redaction_list.currentRow()
        if idx < 0 or idx >= len(self.redactions):
            return
        r = self.redactions.pop(idx)
        if r.scene():
            self.scene.removeItem(r)
        self.redaction_list.takeItem(idx)
        self.statusbar.showMessage(f"Deleted. Remaining: {len(self.redactions)}")

    def save_redacted(self):
        if not self.doc or not self.file_path:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return

        if not self.redactions:
            QMessageBox.warning(self, "No Redactions", "Draw redaction boxes first.")
            return

        # Ask for save path
        default_name = Path(self.file_path).stem + "_redacted.pdf"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Redacted PDF",
            str(Path(self.file_path).parent / default_name),
            "PDF Files (*.pdf)",
        )
        if not save_path:
            return

        # Convert screen coordinates to PDF coordinates
        redaction_data = []
        for r in self.redactions:
            rect = r.rect()
            # Convert from zoomed pixel coords back to PDF points
            redaction_data.append({
                "page": r.page,
                "rect": [
                    rect.x() / self.zoom,
                    rect.y() / self.zoom,
                    (rect.x() + rect.width()) / self.zoom,
                    (rect.y() + rect.height()) / self.zoom,
                ],
            })

        try:
            # Close current doc handle before redaction engine opens it
            self.doc.close()
            apply_redactions(self.file_path, save_path, redaction_data)

            # Reopen the original doc for continued viewing
            self.doc = fitz.open(self.file_path)

            self.redactions.clear()
            self.redaction_list.clear()
            self._render_current_page()

            QMessageBox.information(
                self, "Success",
                f"Redacted PDF saved to:\n{save_path}\n\n"
                f"Underlying text has been permanently removed.\n"
                f"You can now upload this file to Legal AI Expert."
            )
            self.statusbar.showMessage(f"Saved: {Path(save_path).name}")

        except Exception as e:
            # Reopen doc on error
            self.doc = fitz.open(self.file_path)
            QMessageBox.critical(self, "Error", f"Failed to apply redactions:\n{e}")

    def open_upload_page(self):
        webbrowser.open(UPLOAD_URL)
        self.statusbar.showMessage("Opened upload page in browser.")

    def show_guide(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Redaction Guide")
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(GUIDE_HTML)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
