"""
STEAMING STREAM — Application bootstrap
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Sets up QApplication, applies the dark theme, and launches the main window.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from src.ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

DARK_STYLESHEET = """
QWidget {
    background-color: #1a1a1a;
    color: #e0e0e0;
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 11px;
}

QMainWindow {
    background-color: #1a1a1a;
}

QMenuBar {
    background-color: #242424;
    border-bottom: 1px solid #303030;
}
QMenuBar::item:selected { background-color: #333; }
QMenu {
    background-color: #2a2a2a;
    border: 1px solid #444;
}
QMenu::item:selected { background-color: #0d6efd; }

/* ── Source bar ── */
QFrame#source_bar {
    background-color: #1e1e1e;
    border-bottom: 1px solid #2a2a2a;
}

QLabel#section_label {
    color: #555;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
}

QLabel#status_label {
    color: #555;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 1px;
}

/* ── Encoder table ── */
QTableWidget#encoder_table {
    background-color: #181818;
    alternate-background-color: #1e1e1e;
    gridline-color: transparent;
    border: none;
    outline: none;
    selection-background-color: #0d3a6e;
    selection-color: #cce0ff;
}
QTableWidget#encoder_table::item {
    padding: 2px 6px;
    border: none;
}
QHeaderView::section {
    background-color: #222;
    color: #666;
    border: none;
    border-right: 1px solid #2a2a2a;
    border-bottom: 1px solid #2a2a2a;
    padding: 3px 6px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ── Now playing ── */
QFrame#now_playing_bar {
    background-color: #161616;
    border-top: 1px solid #242424;
    border-bottom: 1px solid #242424;
}
QLabel#np_icon {
    color: #2a7a5a;
    font-size: 14px;
}
QLabel#np_label {
    color: #4ab;
    font-style: italic;
}

/* ── Button bar ── */
QFrame#button_bar {
    background-color: #1e1e1e;
    border-top: 1px solid #2a2a2a;
}
QPushButton {
    background-color: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 3px;
    padding: 4px 14px;
    color: #ccc;
}
QPushButton:hover {
    background-color: #363636;
    border-color: #505050;
}
QPushButton:pressed {
    background-color: #1a1a1a;
}
QPushButton#btn_start_all {
    background-color: #112211;
    border-color: #1a5a1a;
    color: #4ddd4d;
    font-weight: 700;
}
QPushButton#btn_start_all:hover { background-color: #193319; }
QPushButton#btn_stop_all {
    background-color: #221111;
    border-color: #5a1a1a;
    color: #dd4d4d;
    font-weight: 700;
}
QPushButton#btn_stop_all:hover { background-color: #331919; }

/* ── Encoder CRUD buttons ── */
QPushButton#btn_add_enc {
    background-color: #1a2a1a;
    border-color: #2a5a2a;
    color: #6ddd6d;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#btn_add_enc:hover { background-color: #223322; }
QPushButton#btn_edit_enc {
    background-color: #1a1a2a;
    border-color: #2a2a5a;
    color: #7a9aee;
    font-size: 13px;
}
QPushButton#btn_edit_enc:hover { background-color: #222233; }
QPushButton#btn_remove_enc {
    background-color: #2a1a1a;
    border-color: #5a2a2a;
    color: #dd6d6d;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#btn_remove_enc:hover { background-color: #332222; }

/* ── Log dialog ── */
QTextEdit#log_view {
    background-color: #111;
    border: none;
    color: #888;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 10px;
    padding: 4px 8px;
}

/* ── Meter panel ── */
QWidget#meter_panel {
    background-color: #141414;
    border-left: 1px solid #2a2a2a;
}

/* ── Small icon buttons ── */
QPushButton.icon_btn {
    background-color: #222;
    border: 1px solid #333;
    border-radius: 2px;
    padding: 2px;
    color: #aaa;
    font-size: 13px;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
}
QPushButton.icon_btn:hover {
    background-color: #2e2e2e;
    border-color: #484848;
    color: #eee;
}

/* ── Combos ── */
QComboBox {
    background-color: #252525;
    border: 1px solid #383838;
    border-radius: 3px;
    padding: 3px 8px;
    color: #ccc;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #222;
    border: 1px solid #444;
    selection-background-color: #0d6efd;
}

/* ── Scrollbars ── */
QScrollBar:vertical {
    background: #1a1a1a;
    width: 7px;
}
QScrollBar::handle:vertical {
    background: #3a3a3a;
    border-radius: 3px;
    min-height: 16px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Dialogs ── */
QDialog {
    background-color: #1e1e1e;
}
QTabWidget::pane {
    border: 1px solid #2a2a2a;
    background-color: #1e1e1e;
}
QTabBar::tab {
    background-color: #252525;
    color: #888;
    border: 1px solid #2a2a2a;
    border-bottom: none;
    padding: 5px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border-top: 2px solid #0d6efd;
}
QTabBar::tab:hover:!selected {
    background-color: #2d2d2d;
    color: #bbb;
}
QSpinBox {
    background-color: #252525;
    border: 1px solid #383838;
    border-radius: 3px;
    padding: 3px 6px;
    color: #ccc;
}
QCheckBox {
    color: #ccc;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #555;
    border-radius: 2px;
    background-color: #252525;
}
QCheckBox::indicator:checked {
    background-color: #0d6efd;
    border-color: #0d6efd;
}
QFrame#form_separator {
    color: #2a2a2a;
    max-height: 1px;
}
QLabel#hint_label {
    color: #555;
    font-size: 10px;
}
QLabel#stat_value {
    color: #4ab;
    font-weight: 500;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}
"""


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class SteamingStreamApp(QApplication):

    def __init__(self, argv):
        super().__init__(argv)
        self.setApplicationName("STEAMING STREAM")
        self.setApplicationVersion("0.1.0")

        self._apply_dark_palette()
        self.setStyleSheet(DARK_STYLESHEET)

        self._window = MainWindow()
        self._window.show()

    def _apply_dark_palette(self) -> None:
        """Base palette so system widgets default to dark even before stylesheet."""
        self.setStyle("Fusion")
        pal = QPalette()
        c = {
            QPalette.ColorRole.Window:          QColor(26,  26,  26),
            QPalette.ColorRole.WindowText:      QColor(220, 220, 220),
            QPalette.ColorRole.Base:            QColor(20,  20,  20),
            QPalette.ColorRole.AlternateBase:   QColor(30,  30,  30),
            QPalette.ColorRole.Text:            QColor(220, 220, 220),
            QPalette.ColorRole.BrightText:      QColor(255, 255, 255),
            QPalette.ColorRole.Button:          QColor(42,  42,  42),
            QPalette.ColorRole.ButtonText:      QColor(220, 220, 220),
            QPalette.ColorRole.Highlight:       QColor(13,  74, 143),
            QPalette.ColorRole.HighlightedText: QColor(220, 220, 220),
            QPalette.ColorRole.Link:            QColor(70, 150, 220),
            QPalette.ColorRole.Mid:             QColor(40,  40,  40),
            QPalette.ColorRole.Dark:            QColor(15,  15,  15),
            QPalette.ColorRole.Shadow:          QColor(0,    0,   0),
        }
        for role, color in c.items():
            pal.setColor(role, color)
        self.setPalette(pal)
