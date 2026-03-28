"""
STEAMING STREAM — Main Window
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Chassis layout:

  ┌─────────────────────────────────────────────────────┬────┐
  │ SOURCE  [device dropdown ▾]                         │    │
  │ [toggle]  BROADCASTING / IDLE                       │ L  │
  ├─────────────────────────────────────────────────────┤ E  │
  │ ☑ │ Encoder          │ Status  │ Listeners │ Max   │ D  │
  │ ☑ │ AAC 32k — ...    │ ● live  │    4      │  12   │    │
  │ ☑ │ AAC 64k — ...    │ ● live  │    2      │   8   │ M  │
  │ ☑ │ AAC 128k — ...   │ ○ idle  │    —      │   —   │ E  │
  │ ☑ │ MP3 392k — ...   │ ○ idle  │    —      │   —   │ T  │
  ├─────────────────────────────────────────────────────┤ E  │
  │ ♫  Now Playing: Artist — Title                      │ R  │
  ├─────────────────────────────────────────────────────┤    │
  │ [▶ Start All]  [■ Stop All]  [⚙ Settings]  Total:6 │ +  │
  ├─────────────────────────────────────────────────────┤ ─  │
  │ 14:23:01  Connected: AAC 32k                        │ ✕  │
  │ 14:23:05  Metadata: Gus Gus — Arabian Horse         │    │
  └─────────────────────────────────────────────────────┴────┘
"""

import math
import os
import platform
import random
import threading
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.audio import AudioEngine
from src.core.config import AppConfig, EncoderConfig, squirrelfm_defaults, MAX_ENCODERS
from src.core.encoder_slot import EncoderSlot
from src.core.metadata import MetadataWatcher
from src.api.http_api import HttpApi
from src.ui.dialogs.encoder_dialog import EncoderDialog
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.snap_manager import SnapManager
from src.ui.widgets.toggle_switch import ToggleSwitch
from src.ui.windows.meter_window import MeterWindow
from src.ui.windows.spectrum_window import SpectrumWindow
from src.ui.windows.eq_window import EQWindow


# ---------------------------------------------------------------------------
# Config path
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    """Return OS-appropriate path for config.json."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "SteamingStream" / "config.json"


# ---------------------------------------------------------------------------
# Thread-safe Qt signals (fired from audio/encoder background threads)
# ---------------------------------------------------------------------------

class _Signals(QObject):
    log_message     = pyqtSignal(str)
    level_update    = pyqtSignal(float, float)    # left_rms, right_rms
    status_changed  = pyqtSignal(str, str)        # encoder_id, status
    metadata_update = pyqtSignal(str)             # title
    stats_update    = pyqtSignal(str, int, int)   # encoder_id, listeners, peak


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _icon_btn(label: str, bg: str = "#222", tooltip: str = "") -> QPushButton:
    """Small square icon button for the meter panel."""
    btn = QPushButton(label)
    btn.setProperty("class", "icon_btn")
    btn.setFixedSize(28, 28)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


# ---------------------------------------------------------------------------
# Encoder status constants
# ---------------------------------------------------------------------------

class EncoderStatus:
    IDLE        = "idle"
    CONNECTING  = "connecting"
    CONNECTED   = "connected"
    ERROR       = "error"

    _DOTS = {
        IDLE:       ("○", "#666666"),
        CONNECTING: ("◎", "#ffcc00"),
        CONNECTED:  ("●", "#00dd00"),
        ERROR:      ("●", "#ff3300"),
    }

    @classmethod
    def dot(cls, status: str) -> tuple[str, str]:
        return cls._DOTS.get(status, cls._DOTS[cls.IDLE])


# ---------------------------------------------------------------------------
# Encoder table
# ---------------------------------------------------------------------------

_COL_EN       = 0
_COL_NAME     = 1
_COL_STATUS   = 2
_COL_LISTEN   = 3
_COL_MAX      = 4
_COL_COUNT    = 5

_HEADERS = ["On", "Encoder", "Status", "↓", "Max"]


class EncoderTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, _COL_COUNT, parent)
        self.setObjectName("encoder_table")
        self.setHorizontalHeaderLabels(_HEADERS)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        hh = self.horizontalHeader()
        hh.setSectionResizeMode(_COL_EN,     QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(_COL_NAME,   QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(_COL_LISTEN, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(_COL_MAX,    QHeaderView.ResizeMode.Fixed)

        self.setColumnWidth(_COL_EN,     28)
        self.setColumnWidth(_COL_STATUS, 90)
        self.setColumnWidth(_COL_LISTEN, 42)
        self.setColumnWidth(_COL_MAX,    42)

        self.verticalHeader().setDefaultSectionSize(26)

    def load_encoders(self, encoders: list[EncoderConfig]) -> None:
        self.setRowCount(0)
        for enc in encoders:
            self.add_encoder_row(enc)

    def add_encoder_row(self, enc: EncoderConfig) -> None:
        row = self.rowCount()
        self.insertRow(row)

        # Enabled checkbox (centred) — toggling writes back to enc.enabled immediately
        chk = QCheckBox()
        chk.setChecked(enc.enabled)
        chk.setObjectName(f"enc_chk_{enc.id}")
        chk.toggled.connect(lambda checked, e=enc: setattr(e, "enabled", checked))
        cell_widget = QWidget()
        cell_layout = QHBoxLayout(cell_widget)
        cell_layout.addWidget(chk)
        cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        self.setCellWidget(row, _COL_EN, cell_widget)

        # Name + server summary
        server_str = (
            f"{enc.server}:{enc.port}{enc.mount}" if enc.server else "not configured"
        )
        name_item = QTableWidgetItem(f"{enc.name}  —  {enc.format} {enc.bitrate}k  ({server_str})")
        name_item.setData(Qt.ItemDataRole.UserRole, enc.id)
        self.setItem(row, _COL_NAME, name_item)

        # Status
        self._set_status_item(row, EncoderStatus.IDLE)

        # Listeners / Max (placeholder dashes)
        for col in (_COL_LISTEN, _COL_MAX):
            item = QTableWidgetItem("—")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor("#555"))
            self.setItem(row, col, item)

    def _set_status_item(self, row: int, status: str) -> None:
        dot, color = EncoderStatus.dot(status)
        labels = {
            EncoderStatus.IDLE:       "idle",
            EncoderStatus.CONNECTING: "connecting…",
            EncoderStatus.CONNECTED:  "live",
            EncoderStatus.ERROR:      "error",
        }
        item = QTableWidgetItem(f"  {dot}  {labels.get(status, status)}")
        item.setForeground(QColor(color))
        self.setItem(row, _COL_STATUS, item)

    def row_for_encoder_id(self, enc_id: str) -> int:
        """Return table row index for the given encoder id, or -1."""
        for row in range(self.rowCount()):
            item = self.item(row, _COL_NAME)
            if item and item.data(Qt.ItemDataRole.UserRole) == enc_id:
                return row
        return -1

    def update_status(self, enc_id: str, status: str) -> None:
        row = self.row_for_encoder_id(enc_id)
        if row >= 0:
            self._set_status_item(row, status)

    def update_stats(self, enc_id: str, listeners: int, peak: int) -> None:
        row = self.row_for_encoder_id(enc_id)
        if row < 0:
            return
        for col, val in ((_COL_LISTEN, listeners), (_COL_MAX, peak)):
            item = self.item(row, col)
            if item:
                item.setText(str(val) if val >= 0 else "—")
                item.setForeground(QColor("#aaa" if val >= 0 else "#555"))

    def reset_stats(self) -> None:
        """Clear listener counts and set all rows to idle after stop."""
        for row in range(self.rowCount()):
            self._set_status_item(row, EncoderStatus.IDLE)
            for col in (_COL_LISTEN, _COL_MAX):
                item = self.item(row, col)
                if item:
                    item.setText("—")
                    item.setForeground(QColor("#555"))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    VERSION = "0.2.0"

    def __init__(self, config: AppConfig | None = None):
        super().__init__()

        # Load config from disk or fall back to defaults
        cfg_path = _config_path()
        if config is not None:
            self._config = config
        elif cfg_path.exists():
            try:
                self._config = AppConfig.load(cfg_path)
            except Exception:
                self._config = squirrelfm_defaults()
        else:
            self._config = squirrelfm_defaults()

        self._cfg_path = cfg_path

        # Signals (cross-thread safe)
        self._sig = _Signals()
        self._sig.log_message.connect(self._log)
        self._sig.level_update.connect(self._on_level_update)
        self._sig.status_changed.connect(self._on_status_changed)
        self._sig.metadata_update.connect(self._on_metadata_update)
        self._sig.stats_update.connect(self._on_stats_update)

        # Runtime state
        self._audio_engine:   AudioEngine   | None = None
        self._monitor:        AudioEngine   | None = None  # level preview only
        self._slots:          list[EncoderSlot]    = []
        self._meta_watcher:   MetadataWatcher | None = None
        self._http_api:       HttpApi | None       = None
        self._running:        bool                 = False
        self._demo_t:         float                = 0.0
        self._compact:        bool                 = False

        # Satellite windows (created lazily)
        self._meter_win:    MeterWindow    | None = None
        self._spectrum_win: SpectrumWindow | None = None
        self._eq_win:       EQWindow       | None = None

        self._build_ui()
        self._populate_source_devices()

        if self._config.settings.auto_connect:
            self._on_start_all()
        else:
            self._start_monitor()

        self._log("STEAMING STREAM started.")
        if not self._running:
            self._log("Configure your encoders and hit Start All.")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _update_title(self, listeners: int = 0) -> None:
        if listeners > 0:
            self.setWindowTitle(
                f"STEAMING STREAM  v{self.VERSION}  —  {listeners} listener{'s' if listeners != 1 else ''}"
            )
        else:
            self.setWindowTitle(f"STEAMING STREAM  v{self.VERSION}")

    def _build_ui(self) -> None:
        self._update_title()
        self.setMinimumSize(360, 160)
        s = self._config.settings
        self.resize(max(360, s.window_w), max(160, s.window_h))
        if s.window_x >= 0 and s.window_y >= 0:
            self.move(s.window_x, s.window_y)

        # ── Stacked widget: full view (index 0) | compact bar (index 1) ──
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # ── Full view ─────────────────────────────────────────────────
        full = QWidget()
        full_layout = QVBoxLayout(full)
        full_layout.setContentsMargins(0, 0, 0, 0)
        full_layout.setSpacing(0)
        full_layout.addWidget(self._build_source_bar())
        full_layout.addWidget(self._build_encoder_table(), stretch=1)
        full_layout.addWidget(self._build_now_playing())
        full_layout.addWidget(self._build_button_bar())
        self._stack.addWidget(full)          # index 0

        # ── Compact bar ───────────────────────────────────────────────
        self._compact_bar = self._build_compact_bar()
        self._stack.addWidget(self._compact_bar)   # index 1

        # Menu bar
        self._build_menu()

        # Floating log dialog (hidden until Ctrl+L)
        self._build_log_dialog()

        # Register with SnapManager so satellite windows can snap to us
        SnapManager.instance().register(self)

        # Restore + open satellite windows
        self._open_satellite_windows()

        # Stats polling timer (every 30 s while running)
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(30_000)
        self._stats_timer.timeout.connect(self._poll_stats)

    def _build_menu(self) -> None:
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        file_menu.addAction("Settings…",  self._on_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        view_menu = mb.addMenu("View")
        view_menu.addAction("Meters",   self._show_meter_window)
        view_menu.addAction("Spectrum", self._show_spectrum_window)
        view_menu.addAction("EQ / Effects", self._show_eq_window)
        view_menu.addSeparator()
        shade_action = view_menu.addAction("Compact Bar", self._toggle_compact)
        shade_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        view_menu.addSeparator()
        log_action = view_menu.addAction("Log", self._on_view_log)
        log_action.setShortcut(QKeySequence("Ctrl+L"))

        help_menu = mb.addMenu("Help")
        help_menu.addAction("About / Keyboard Shortcuts", self._on_about)

    def _build_source_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("source_bar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(8)

        src_label = QLabel("SOURCE")
        src_label.setObjectName("section_label")

        self.source_combo = QComboBox()
        self.source_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.source_combo.setToolTip("Audio input device")

        # Master gain slider  (-20 dB … +12 dB, tenths)
        gain_lbl = QLabel("GAIN")
        gain_lbl.setObjectName("section_label")
        self._gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._gain_slider.setRange(-200, 120)
        self._gain_slider.setValue(int(self._config.settings.gain_db * 10))
        self._gain_slider.setFixedWidth(80)
        self._gain_slider.setToolTip("Master input gain")
        self._gain_readout = QLabel(self._fmt_gain(self._config.settings.gain_db))
        self._gain_readout.setFixedWidth(46)
        self._gain_readout.setStyleSheet("font-size: 10px; color: #aaa;")
        self._gain_slider.valueChanged.connect(self._on_gain_changed)

        self.master_toggle = ToggleSwitch(initial=False)
        self.master_toggle.toggled.connect(self._on_master_toggle)

        self.status_label = QLabel("IDLE")
        self.status_label.setObjectName("status_label")
        self.status_label.setFixedWidth(110)

        layout.addWidget(src_label)
        layout.addWidget(self.source_combo)
        layout.addWidget(gain_lbl)
        layout.addWidget(self._gain_slider)
        layout.addWidget(self._gain_readout)
        layout.addWidget(self.master_toggle)
        layout.addWidget(self.status_label)

        return frame

    @staticmethod
    def _fmt_gain(db: float) -> str:
        return f"{db:+.1f} dB" if db != 0.0 else "0.0 dB"

    def _on_gain_changed(self, value: int) -> None:
        db = value / 10.0
        self._gain_readout.setText(self._fmt_gain(db))
        self._config.settings.gain_db = db
        if self._audio_engine:
            self._audio_engine.set_gain_db(db)
        if self._monitor:
            self._monitor.set_gain_db(db)

    def _build_encoder_table(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.encoder_table = EncoderTable(wrapper)
        self.encoder_table.load_encoders(self._config.encoders)
        self.encoder_table.cellDoubleClicked.connect(self._on_edit_encoder)
        layout.addWidget(self.encoder_table)

        return wrapper

    def _build_now_playing(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("now_playing_bar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(6)

        icon = QLabel("♫")
        icon.setObjectName("np_icon")

        self.np_label = QLabel("Now Playing: —")
        self.np_label.setObjectName("np_label")
        self.np_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        layout.addWidget(icon)
        layout.addWidget(self.np_label)

        return frame

    def _build_button_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("button_bar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(6)

        self.btn_start_all = QPushButton("▶  Start All")
        self.btn_start_all.setObjectName("btn_start_all")
        self.btn_start_all.clicked.connect(self._on_start_all)

        self.btn_stop_all = QPushButton("■  Stop All")
        self.btn_stop_all.setObjectName("btn_stop_all")
        self.btn_stop_all.clicked.connect(self._on_stop_all)

        btn_settings = QPushButton("⚙  Settings")
        btn_settings.clicked.connect(self._on_settings)

        # Encoder CRUD — right side, same height as other buttons
        self.btn_add_enc    = QPushButton("+")
        self.btn_add_enc.setObjectName("btn_add_enc")
        self.btn_add_enc.setToolTip("Add encoder")
        self.btn_add_enc.setFixedWidth(36)
        self.btn_edit_enc   = QPushButton("✎")
        self.btn_edit_enc.setObjectName("btn_edit_enc")
        self.btn_edit_enc.setToolTip("Edit selected encoder")
        self.btn_edit_enc.setFixedWidth(36)
        self.btn_remove_enc = QPushButton("✕")
        self.btn_remove_enc.setObjectName("btn_remove_enc")
        self.btn_remove_enc.setToolTip("Remove selected encoder")
        self.btn_remove_enc.setFixedWidth(36)
        self.btn_add_enc.clicked.connect(self._on_add_encoder)
        self.btn_edit_enc.clicked.connect(
            lambda: self._on_edit_encoder(self.encoder_table.currentRow(), 0)
        )
        self.btn_remove_enc.clicked.connect(self._on_remove_encoder)

        layout.addWidget(self.btn_start_all)
        layout.addWidget(self.btn_stop_all)
        layout.addWidget(btn_settings)
        layout.addStretch()
        layout.addWidget(self.btn_add_enc)
        layout.addWidget(self.btn_edit_enc)
        layout.addWidget(self.btn_remove_enc)

        return frame

    def _build_log_dialog(self) -> None:
        """Build the floating log dialog (hidden until Ctrl+L)."""
        self._log_dialog = QDialog(self)
        self._log_dialog.setWindowTitle("STEAMING STREAM — Log")
        self._log_dialog.resize(680, 220)
        self._log_dialog.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self._log_dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # ESC closes the dialog
        shortcut = QShortcut(QKeySequence("Escape"), self._log_dialog)
        shortcut.activated.connect(self._log_dialog.hide)

        layout.addWidget(self.log_view)

    def _build_compact_bar(self) -> QWidget:
        """Thin status strip shown when window is in compact (windowshade) mode."""
        bar = QWidget()
        bar.setFixedHeight(28)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(12)

        self._bar_streams  = QLabel("● 0 streams")
        self._bar_streams.setStyleSheet("color: #555; font-size: 10px;")
        self._bar_listeners = QLabel("0 listeners")
        self._bar_listeners.setStyleSheet("color: #555; font-size: 10px;")
        self._bar_data     = QLabel("0 kbps")
        self._bar_data.setStyleSheet("color: #555; font-size: 10px;")
        self._bar_title    = QLabel("—")
        self._bar_title.setStyleSheet("color: #777; font-size: 10px;")
        self._bar_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        expand_btn = QPushButton("▲")
        expand_btn.setFixedSize(20, 20)
        expand_btn.setToolTip("Expand window")
        expand_btn.clicked.connect(self._toggle_compact)

        layout.addWidget(self._bar_streams)
        layout.addWidget(self._bar_listeners)
        layout.addWidget(self._bar_data)
        layout.addWidget(self._bar_title)
        layout.addWidget(expand_btn)
        return bar

    # ------------------------------------------------------------------
    # Compact bar toggle
    # ------------------------------------------------------------------

    def _toggle_compact(self) -> None:
        self._compact = not self._compact
        if self._compact:
            self._full_height = self.height()
            self._stack.setCurrentIndex(1)
            self.setFixedHeight(28 + self.menuBar().height())
        else:
            self._stack.setCurrentIndex(0)
            self.setMinimumSize(360, 160)
            self.setMaximumSize(16777215, 16777215)
            self.resize(self.width(), getattr(self, "_full_height", 320))

    def _update_compact_bar(self, streams: int, listeners: int, title: str) -> None:
        dot = "●" if streams > 0 else "○"
        color = "#00dd00" if streams > 0 else "#555"
        self._bar_streams.setText(f"<span style='color:{color}'>{dot}</span> {streams} stream{'s' if streams != 1 else ''}")
        self._bar_listeners.setText(f"{listeners} listener{'s' if listeners != 1 else ''}")
        self._bar_title.setText(title or "—")

    # ------------------------------------------------------------------
    # Satellite window management
    # ------------------------------------------------------------------

    def _open_satellite_windows(self) -> None:
        """Restore satellite windows that were visible when the app last closed."""
        s = self._config.settings

        if s.meter_visible:
            self._show_meter_window()
            if s.meter_x >= 0 and s.meter_y >= 0:
                self._meter_win.move(s.meter_x, s.meter_y)
            self._meter_win.resize(s.meter_w, s.meter_h)

        if s.spectrum_visible:
            self._show_spectrum_window()
            if s.spectrum_x >= 0 and s.spectrum_y >= 0:
                self._spectrum_win.move(s.spectrum_x, s.spectrum_y)
            self._spectrum_win.resize(s.spectrum_w, s.spectrum_h)

        if s.eq_visible:
            self._show_eq_window()
            if s.eq_x >= 0 and s.eq_y >= 0:
                self._eq_win.move(s.eq_x, s.eq_y)
            self._eq_win.resize(s.eq_w, s.eq_h)

    def _show_meter_window(self) -> None:
        if self._meter_win is None:
            self._meter_win = MeterWindow(
                style=self._config.settings.meter_style, parent=None
            )
            # Position default: right of main window
            geo = self.frameGeometry()
            self._meter_win.move(geo.right() + 2, geo.top())
        self._meter_win.show()
        self._meter_win.raise_()

    def _show_spectrum_window(self) -> None:
        if self._spectrum_win is None:
            self._spectrum_win = SpectrumWindow(parent=None)
            geo = self.frameGeometry()
            self._spectrum_win.move(geo.left(), geo.bottom() + 2)
        self._spectrum_win.show()
        self._spectrum_win.raise_()

    def _show_eq_window(self) -> None:
        if self._eq_win is None:
            src = self._config.source
            self._eq_win = EQWindow(
                sample_rate=float(src.sample_rate),
                channels=src.channels,
                parent=None,
            )
            geo = self.frameGeometry()
            self._eq_win.move(geo.left(), geo.bottom() + 2)
        self._eq_win.show()
        self._eq_win.raise_()

    # ------------------------------------------------------------------
    # Snap: main window participates in SnapManager
    # ------------------------------------------------------------------

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        from src.ui.snappable_window import SnappableWindow
        if SnappableWindow._moving:
            return
        delta = event.pos() - event.oldPos()
        if delta.isNull():
            return
        manager = SnapManager.instance()
        group   = manager.get_group(self)
        SnappableWindow._moving = True
        try:
            for w in group:
                if w is not self:
                    w.move(w.pos() + delta)
            snap = manager.compute_snap(self, group)
            if snap:
                adj = QPoint(snap[0], snap[1])
                self.move(self.pos() + adj)
                for w in group:
                    if w is not self:
                        w.move(w.pos() + adj)
        finally:
            SnappableWindow._moving = False

    # ------------------------------------------------------------------
    # Source device enumeration
    # ------------------------------------------------------------------

    def _populate_source_devices(self) -> None:
        """Fill source combo with real audio devices; fall back to placeholder."""
        self.source_combo.blockSignals(True)
        self.source_combo.clear()

        devices = AudioEngine.list_devices()
        if devices:
            for dev in devices:
                self.source_combo.addItem(dev.display_name(), userData=dev)
            # Pre-select device matching saved config
            saved = self._config.source.device_name
            if saved:
                for i in range(self.source_combo.count()):
                    d = self.source_combo.itemData(i)
                    if d and d.name == saved:
                        self.source_combo.setCurrentIndex(i)
                        break
        else:
            self.source_combo.addItem("(no devices — install sounddevice)", userData=None)

        self.source_combo.blockSignals(False)

        # Restart monitor whenever the selected device changes
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)

    # ------------------------------------------------------------------
    # Demo signal (replaced by real audio when engine starts)
    # ------------------------------------------------------------------

    def _start_demo_meters(self) -> None:
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(1000 // 30)
        self._demo_timer.timeout.connect(self._demo_tick)
        self._demo_timer.start()

    def _stop_demo_meters(self) -> None:
        if hasattr(self, "_demo_timer"):
            self._demo_timer.stop()

    # ------------------------------------------------------------------
    # Audio monitor (level preview — no encoding, no broadcast)
    # ------------------------------------------------------------------

    def _start_monitor(self) -> None:
        """Start a lightweight audio capture just for meter display."""
        if self._running:
            return  # full engine handles levels when streaming
        self._stop_monitor()

        dev_data = self.source_combo.currentData()
        if dev_data is None:
            return

        src = self._config.source
        # Use the device's actual channel count, capped at 2
        channels = min(dev_data.channels, 2) if dev_data.channels > 0 else 2
        try:
            self._monitor = AudioEngine()
            self._monitor.set_on_level(
                lambda l, r: self._sig.level_update.emit(l, r)
            )
            if self._spectrum_win:
                self._monitor.set_on_pcm(self._spectrum_win.set_pcm)
            self._monitor.set_gain_db(self._config.settings.gain_db)
            self._monitor.start(
                device_index=dev_data.index,
                sample_rate=src.sample_rate,
                channels=channels,
                buffer_size=src.buffer_size,
                is_loopback=dev_data.is_loopback,
            )
        except Exception as exc:
            self._sig.log_message.emit(f"Monitor failed: {exc}")
            self._monitor = None  # device unavailable, meters stay at zero

    def _stop_monitor(self) -> None:
        if self._monitor:
            try:
                self._monitor.stop()
            except Exception:
                pass
            self._monitor = None
        if self._meter_win: self._meter_win.set_levels(0.0, 0.0)

    def _on_source_changed(self, _index: int) -> None:
        """Restart monitor and save device selection when user picks a device."""
        dev_data = self.source_combo.currentData()
        if dev_data is not None:
            self._config.source.device_name  = dev_data.name
            self._config.source.device_index = dev_data.index
            self._save_config()
        if not self._running:
            self._start_monitor()

    def _demo_tick(self) -> None:
        self._demo_t += 0.05
        t = self._demo_t
        env   = 0.55 + 0.25 * math.sin(t * 0.31)
        left  = env + 0.12 * math.sin(t * 4.7)  + 0.04 * random.random()
        right = env + 0.12 * math.sin(t * 4.7 + 0.8) + 0.04 * random.random()
        left  = max(0.0, min(0.98, left))
        right = max(0.0, min(0.98, right))
        if self._meter_win: self._meter_win.set_levels(left, right)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f'<span style="color:#555">{ts}</span>  {message}')
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # Engine start / stop
    # ------------------------------------------------------------------

    def _on_start_all(self) -> None:
        if self._running:
            return

        self._stop_demo_meters()
        self._stop_monitor()
        self._running = True

        # --- Audio source ---
        src = self._config.source
        dev_data = self.source_combo.currentData()
        if dev_data is not None:
            device_index = dev_data.index
            is_loopback  = dev_data.is_loopback
            src.device_index = device_index
            src.device_name  = dev_data.name
        else:
            device_index = src.device_index
            is_loopback  = False

        self._audio_engine = AudioEngine()
        self._audio_engine.set_on_log(
            lambda msg: self._sig.log_message.emit(msg)
        )
        self._audio_engine.set_on_level(
            lambda l, r: self._sig.level_update.emit(l, r)
        )
        # Feed raw PCM to spectrum (set_pcm is thread-safe — only numpy + update())
        if self._spectrum_win:
            self._audio_engine.set_on_pcm(self._spectrum_win.set_pcm)
        # Apply master gain
        self._audio_engine.set_gain_db(self._config.settings.gain_db)
        # Update EQ processor sample rate if window exists
        if self._eq_win:
            self._eq_win.set_sample_rate(float(src.sample_rate))

        # --- Encoder slots ---
        self._slots = []
        enabled_encoders = [e for e in self._config.encoders if e.enabled]

        # Determine actual device channel count before building encoder slots
        dev_channels = min(dev_data.channels, 2) if dev_data is not None and dev_data.channels > 0 else src.channels

        for enc in enabled_encoders:
            # Store the capture rate/channels separately so FFmpeg knows the real
            # input spec. enc.sample_rate stays as the user-configured OUTPUT rate.
            enc.source_sample_rate = src.sample_rate
            enc.source_channels    = dev_channels

            slot = EncoderSlot(
                config=enc,
                on_status_change=lambda eid, st: self._sig.status_changed.emit(eid, st),
                on_log=lambda msg: self._sig.log_message.emit(msg),
            )
            self._audio_engine.add_slot(slot)
            self._slots.append(slot)

        # Start audio engine
        try:
            self._audio_engine.start(
                device_index=device_index,
                sample_rate=src.sample_rate,
                channels=dev_channels,
                buffer_size=src.buffer_size,
                is_loopback=is_loopback,
            )
        except Exception as exc:
            self._log(f"<span style='color:#ff3300'>Audio engine failed: {exc}</span>")
            self._running = False
            return

        # Start encoder slots
        for slot in self._slots:
            slot.start()

        # --- Metadata watcher ---
        self._meta_watcher = MetadataWatcher(
            config=self._config.metadata,
            on_update=lambda title: self._sig.metadata_update.emit(title),
            on_log=lambda msg: self._sig.log_message.emit(msg),
        )
        self._meta_watcher.start()

        # --- HTTP API ---
        g = self._config.settings
        if g.http_api_enabled:
            pw = getattr(g, "http_api_password", "")
            self._http_api = HttpApi(port=g.http_api_port, password=pw)
            self._http_api.set_on_metadata(self._on_api_metadata)
            self._http_api.set_on_log(lambda msg: self._sig.log_message.emit(msg))
            self._http_api.set_status_provider(self._build_status_dict)
            self._http_api.start()

        # Update UI state
        self._set_broadcasting_ui(True)
        self._stats_timer.start()
        # Fire one immediate stats poll after a short delay (give slots time to connect)
        QTimer.singleShot(8_000, self._poll_stats)
        self._log("▶  Starting all encoders…")

    def _on_stop_all(self) -> None:
        if not self._running:
            return

        self._log("■  Stopping all encoders…")
        self._running = False
        self._stats_timer.stop()

        # Stop metadata watcher
        if self._meta_watcher:
            self._meta_watcher.stop()
            self._meta_watcher = None

        # Stop encoder slots
        for slot in self._slots:
            slot.stop()
        self._slots = []

        # Stop audio engine
        if self._audio_engine:
            self._audio_engine.stop()
            self._audio_engine = None

        # HTTP API is a daemon thread — it exits with the process
        self._http_api = None

        # Reset UI
        self._set_broadcasting_ui(False)
        if self._meter_win:
            self._meter_win.set_levels(0.0, 0.0)
        if self._spectrum_win:
            self._spectrum_win.reset()
        self.encoder_table.reset_stats()
        self.np_label.setText("Now Playing: —")
        self._update_title(0)

        self._start_monitor()
        self._log("Stopped.")

    def _set_broadcasting_ui(self, broadcasting: bool) -> None:
        if broadcasting:
            self.status_label.setText("BROADCASTING")
            self.status_label.setStyleSheet("color: #00dd00; font-weight: 600;")
        else:
            self.status_label.setText("IDLE")
            self.status_label.setStyleSheet("color: #666;")

        # Keep toggle in sync (block its signal to avoid recursive call)
        self.master_toggle.blockSignals(True)
        self.master_toggle.set_on(broadcasting)
        self.master_toggle.blockSignals(False)

    # ------------------------------------------------------------------
    # API metadata callback (comes in on Flask thread → route via signal)
    # ------------------------------------------------------------------

    def _on_api_metadata(self, title: str) -> None:
        """Called from Flask thread — route through signal, then push to watcher."""
        self._sig.metadata_update.emit(title)
        if self._meta_watcher:
            self._meta_watcher.push_title(title)
        # Also push to all encoder slots directly
        for slot in self._slots:
            slot.update_metadata(title)

    def _build_status_dict(self) -> dict:
        """JSON payload for /status endpoint."""
        return {
            "title":    self._meta_watcher.current_title if self._meta_watcher else "",
            "running":  self._running,
            "encoders": [
                {
                    "id":     slot.encoder_id,
                    "status": slot.status,
                }
                for slot in self._slots
            ],
        }

    # ------------------------------------------------------------------
    # Stats polling
    # ------------------------------------------------------------------

    def _poll_stats(self) -> None:
        """Called every 30 s — dispatches HTTP fetches to a background thread."""
        slots = [s for s in self._slots if s.status == "connected"]
        if slots:
            threading.Thread(
                target=self._fetch_stats_bg, args=(slots,), daemon=True
            ).start()

    def _fetch_stats_bg(self, slots: list) -> None:
        """Background thread: fetch listener counts and emit results via signals."""
        total = 0
        for slot in slots:
            stats     = slot.fetch_stats()
            listeners = stats.get("listeners", -1)
            peak      = stats.get("peak", -1)
            if listeners >= 0:
                total += listeners
            self._sig.stats_update.emit(slot.encoder_id, listeners, peak)
        # _update_title must run on the UI thread — route through a no-op signal
        # by emitting a stats_update that the handler will also use to refresh title
        self._sig.stats_update.emit("__total__", total, -1)

    # ------------------------------------------------------------------
    # Signal handlers (run on main/Qt thread)
    # ------------------------------------------------------------------

    def _on_level_update(self, left: float, right: float) -> None:
        if self._meter_win:
            self._meter_win.set_levels(left, right)

    def _on_status_changed(self, enc_id: str, status: str) -> None:
        self.encoder_table.update_status(enc_id, status)
        enc = next((e for e in self._config.encoders if e.id == enc_id), None)
        name = enc.name if enc else enc_id
        labels = {
            "connecting": f"Connecting: {name}…",
            "connected":  f"Connected: {name}",
            "error":      f"<span style='color:#ff3300'>Error: {name}</span>",
            "idle":       f"Idle: {name}",
        }
        self._log(labels.get(status, f"{name}: {status}"))

    def _on_metadata_update(self, title: str) -> None:
        self.np_label.setText(f"Now Playing: {title}")
        self._log(f"Metadata: {title}")
        # Push to encoder slots for server-side metadata update
        for slot in self._slots:
            slot.update_metadata(title)

    def _on_stats_update(self, enc_id: str, listeners: int, peak: int) -> None:
        if enc_id == "__total__":
            self._update_title(listeners)
            streams = sum(1 for s in self._slots if s.status == "connected")
            title = self.np_label.text().replace("Now Playing: ", "")
            self._update_compact_bar(streams, max(0, listeners), title)
        else:
            self.encoder_table.update_stats(enc_id, listeners, peak)

    # ------------------------------------------------------------------
    # Master toggle (follows start/stop state)
    # ------------------------------------------------------------------

    def _on_master_toggle(self, on: bool) -> None:
        if on:
            self._on_start_all()
        else:
            self._on_stop_all()

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _on_about(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("About STEAMING STREAM")
        dlg.setMinimumWidth(420)
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel(f"STEAMING STREAM  v{self.VERSION}")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #eee;")
        layout.addWidget(title)

        desc = QLabel(
            "Multi-bitrate audio encoder for internet radio broadcasting.\n"
            "GPL v3 — github.com/baddaywithacamera/steamingstreamer"
        )
        desc.setStyleSheet("color: #888; font-size: 10px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        shortcuts = QLabel(
            "<b>Keyboard shortcuts</b><br><br>"
            "<b>Ctrl+L</b> &nbsp;&nbsp; Show / hide log<br>"
            "<b>ESC</b> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp; Close log window<br>"
            "<br>"
            "<b>Metadata push URL</b> (RadioDJ / StationPlaylist)<br>"
            "<code>http://localhost:9000/metadata?song=Artist - Title</code>"
        )
        shortcuts.setStyleSheet("color: #aaa; font-size: 11px; line-height: 1.6;")
        shortcuts.setWordWrap(True)
        shortcuts.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(shortcuts)

        note = QLabel(
            "⚠  Features in progress: spectrum analyzer, "
            "system tray, TUNE/TWERKER playout integration."
        )
        note.setStyleSheet("color: #666; font-size: 10px; font-style: italic;")
        note.setWordWrap(True)
        layout.addWidget(note)

        btn = QPushButton("Close")
        btn.setFixedWidth(80)
        btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        dlg.exec()

    def _on_settings(self) -> None:
        was_running = self._running
        if was_running:
            self._on_stop_all()

        dlg = SettingsDialog(self._config, parent=self)
        if dlg.exec():
            # Re-populate device combo in case settings changed device
            self._populate_source_devices()
            self._log("Settings saved.")
            self._save_config()
            # Apply meter style change immediately (hot-swap the widget)
            if self._meter_win: self._meter_win.set_style(self._config.settings.meter_style)

        if was_running:
            self._on_start_all()

    # ------------------------------------------------------------------
    # Encoder table CRUD
    # ------------------------------------------------------------------

    def _on_view_log(self) -> None:
        if self._log_dialog.isVisible():
            self._log_dialog.hide()
        else:
            # Position below the main window on first show
            geo = self.geometry()
            self._log_dialog.move(geo.left(), geo.bottom() + 4)
            self._log_dialog.show()
            self._log_dialog.raise_()

    def _on_add_encoder(self) -> None:
        if len(self._config.encoders) >= MAX_ENCODERS:
            self._log(f"Maximum of {MAX_ENCODERS} encoders reached.")
            return
        enc = EncoderConfig()
        dlg = EncoderDialog(enc, parent=self)
        if dlg.exec():
            new_enc = dlg.get_encoder()
            self._config.encoders.append(new_enc)
            self.encoder_table.add_encoder_row(new_enc)
            self._log(f"Encoder added: {new_enc.name}")
            self._save_config()

    def _on_edit_encoder(self, row: int, _col: int = 0) -> None:
        if row < 0:
            return
        name_item = self.encoder_table.item(row, _COL_NAME)
        if not name_item:
            return
        enc_id = name_item.data(Qt.ItemDataRole.UserRole)
        enc = next((e for e in self._config.encoders if e.id == enc_id), None)
        if not enc:
            return
        dlg = EncoderDialog(enc, parent=self)
        if dlg.exec():
            self.encoder_table.load_encoders(self._config.encoders)
            self._log(f"Encoder updated: {enc.name}")
            self._save_config()

    def _on_remove_encoder(self) -> None:
        row = self.encoder_table.currentRow()
        if row < 0:
            self._log("Select an encoder row to remove.")
            return
        name_item = self.encoder_table.item(row, _COL_NAME)
        if not name_item:
            return
        enc_id = name_item.data(Qt.ItemDataRole.UserRole)
        enc = next((e for e in self._config.encoders if e.id == enc_id), None)
        name = enc.name if enc else "encoder"
        self._config.encoders = [e for e in self._config.encoders if e.id != enc_id]
        self.encoder_table.removeRow(row)
        self._log(f"Encoder removed: {name}")
        self._save_config()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _save_config(self) -> None:
        try:
            self._config.save(self._cfg_path)
        except Exception as exc:
            self._log(f"Could not save config: {exc}")

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._running:
            self._on_stop_all()
        self._stop_monitor()
        self._log_dialog.hide()

        # Persist main window geometry
        s = self._config.settings
        s.window_x = self.x()
        s.window_y = self.y()
        s.window_w = self.width()
        s.window_h = self.height() if not self._compact else getattr(self, "_full_height", self.height())
        s.gain_db  = self._config.settings.gain_db

        # Persist satellite window state
        if self._meter_win:
            g = self._meter_win.geometry()
            s.meter_x, s.meter_y = g.x(), g.y()
            s.meter_w, s.meter_h = g.width(), g.height()
            s.meter_visible = self._meter_win.isVisible()
        else:
            s.meter_visible = False

        if self._spectrum_win:
            g = self._spectrum_win.geometry()
            s.spectrum_x, s.spectrum_y = g.x(), g.y()
            s.spectrum_w, s.spectrum_h = g.width(), g.height()
            s.spectrum_visible = self._spectrum_win.isVisible()
        else:
            s.spectrum_visible = False

        if self._eq_win:
            g = self._eq_win.geometry()
            s.eq_x, s.eq_y = g.x(), g.y()
            s.eq_w, s.eq_h = g.width(), g.height()
            s.eq_visible = self._eq_win.isVisible()
        else:
            s.eq_visible = False

        # Close satellite windows cleanly
        for w in (self._meter_win, self._spectrum_win, self._eq_win):
            if w:
                w.close()

        SnapManager.instance().unregister(self)
        self._save_config()
        event.accept()
