"""
STEAMING STREAM — Settings Dialog
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Four tabs:
  Source    — audio input device, sample rate, buffer size
  Metadata  — now-playing file/URL/static, polling interval
  General   — startup behaviour, tray, silence padding
  API       — RadioCaster HTTP API port and password
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.config import AppConfig


class SettingsDialog(QDialog):

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_source(),   "Source")
        self.tabs.addTab(self._tab_metadata(), "Metadata")
        self.tabs.addTab(self._tab_general(),  "General")
        self.tabs.addTab(self._tab_api(),      "API")
        root.addWidget(self.tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Tab: Source
    # ------------------------------------------------------------------

    def _tab_source(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Device selector
        dev_row = QHBoxLayout()
        self.cmb_device = QComboBox()
        self.cmb_device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._refresh_devices()

        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip("Refresh device list")
        btn_refresh.clicked.connect(self._refresh_devices)

        dev_row.addWidget(self.cmb_device, stretch=1)
        dev_row.addWidget(btn_refresh)
        form.addRow("Input device:", dev_row)

        hint = QLabel(
            "On Windows, choose a [loopback] device to capture system audio.\n"
            "On Linux, choose the PulseAudio monitor source."
        )
        hint.setObjectName("hint_label")
        hint.setWordWrap(True)
        form.addRow("", hint)

        form.addRow(_sep())

        # Sample rate
        self.cmb_sample_rate = QComboBox()
        self.cmb_sample_rate.addItems(["44100", "48000"])
        self.cmb_sample_rate.setFixedWidth(90)
        form.addRow("Sample rate (Hz):", self.cmb_sample_rate)

        # Buffer size
        self.cmb_buffer = QComboBox()
        self.cmb_buffer.addItems(["256", "512", "1024", "2048", "4096"])
        self.cmb_buffer.setCurrentText("1024")
        self.cmb_buffer.setFixedWidth(90)
        buf_hint = QLabel("  Smaller = lower latency, less stable")
        buf_hint.setObjectName("hint_label")
        buf_row = QHBoxLayout()
        buf_row.addWidget(self.cmb_buffer)
        buf_row.addWidget(buf_hint)
        buf_row.addStretch()
        form.addRow("Buffer size:", buf_row)

        # Produce silence
        self.chk_silence = QCheckBox(
            "Produce silence when no audio is present"
        )
        form.addRow("", self.chk_silence)

        return w

    # ------------------------------------------------------------------
    # Tab: Metadata
    # ------------------------------------------------------------------

    def _tab_metadata(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cmb_meta_type = QComboBox()
        self.cmb_meta_type.addItems(["Read from file", "Read from URL", "Static text"])
        self.cmb_meta_type.currentIndexChanged.connect(self._on_meta_type_changed)
        form.addRow("Source:", self.cmb_meta_type)

        # File path
        file_row = QHBoxLayout()
        self.inp_meta_file = QLineEdit()
        self.inp_meta_file.setPlaceholderText("e.g.  C:\\RadioDJ\\nowplaying.txt")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(28)
        btn_browse.clicked.connect(self._browse_metadata_file)
        file_row.addWidget(self.inp_meta_file)
        file_row.addWidget(btn_browse)
        self._meta_file_row_label = "File path:"
        form.addRow("File path:", file_row)
        self._file_row_idx = form.rowCount() - 1

        # URL
        self.inp_meta_url = QLineEdit()
        self.inp_meta_url.setPlaceholderText("http://localhost/nowplaying")
        form.addRow("URL:", self.inp_meta_url)
        self._url_row_idx = form.rowCount() - 1

        # Static text
        self.inp_static = QLineEdit()
        self.inp_static.setPlaceholderText("Squirrel FM")
        form.addRow("Text:", self.inp_static)
        self._static_row_idx = form.rowCount() - 1

        form.addRow(_sep())

        self.chk_first_line = QCheckBox("Use first line only")
        self.chk_first_line.setChecked(True)
        form.addRow("", self.chk_first_line)

        poll_row = QHBoxLayout()
        self.spn_poll = QDoubleSpinBox()
        self.spn_poll.setRange(0.5, 30.0)
        self.spn_poll.setValue(2.0)
        self.spn_poll.setSingleStep(0.5)
        self.spn_poll.setSuffix(" sec")
        self.spn_poll.setFixedWidth(90)
        poll_row.addWidget(self.spn_poll)
        poll_row.addStretch()
        form.addRow("Poll interval:", poll_row)

        self.inp_fallback = QLineEdit()
        self.inp_fallback.setPlaceholderText("Steaming Stream")
        form.addRow("Fallback text:", self.inp_fallback)

        self._form_meta = form
        self._on_meta_type_changed(0)

        return w

    # ------------------------------------------------------------------
    # Tab: General
    # ------------------------------------------------------------------

    def _tab_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.chk_autoconnect  = QCheckBox("Connect all encoders automatically on launch")
        self.chk_start_boot   = QCheckBox("Start with Windows / Linux session")
        self.chk_start_min    = QCheckBox("Start minimised to system tray")

        for chk in (self.chk_autoconnect, self.chk_start_boot, self.chk_start_min):
            form.addRow("", chk)

        form.addRow(_sep())

        fps_row = QHBoxLayout()
        self.spn_fps = QSpinBox()
        self.spn_fps.setRange(10, 60)
        self.spn_fps.setValue(30)
        self.spn_fps.setSuffix(" fps")
        self.spn_fps.setFixedWidth(80)
        fps_row.addWidget(self.spn_fps)
        fps_row.addWidget(QLabel("  Higher = smoother meters, more CPU"))
        fps_row.addStretch()
        form.addRow("Meter rate:", fps_row)

        self.cmb_log_level = QComboBox()
        self.cmb_log_level.addItems(["info", "warning", "error"])
        self.cmb_log_level.setFixedWidth(100)
        form.addRow("Log level:", self.cmb_log_level)

        return w

    # ------------------------------------------------------------------
    # Tab: API
    # ------------------------------------------------------------------

    def _tab_api(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.chk_api_enabled = QCheckBox("Enable RadioCaster-compatible HTTP API")
        self.chk_api_enabled.setChecked(True)
        form.addRow("", self.chk_api_enabled)

        self.spn_api_port = QSpinBox()
        self.spn_api_port.setRange(1024, 65535)
        self.spn_api_port.setValue(9000)
        self.spn_api_port.setFixedWidth(90)
        form.addRow("Port:", self.spn_api_port)

        self.inp_api_password = QLineEdit()
        self.inp_api_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_api_password.setPlaceholderText("Optional — leave blank to accept all requests")
        form.addRow("Password:", self.inp_api_password)

        form.addRow(_sep())

        info = QLabel(
            "RadioDJ metadata push URL:\n"
            "  http://localhost:9000/metadata?song=Artist - Title\n\n"
            "StationPlaylist / other software:\n"
            "  http://localhost:9000/api/metadata?title=Title&artist=Artist"
        )
        info.setObjectName("hint_label")
        info.setWordWrap(True)
        form.addRow("", info)

        return w

    # ------------------------------------------------------------------
    # Populate from config
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        s = self._config.source
        m = self._config.metadata
        g = self._config.settings

        # Source
        sr_idx = self.cmb_sample_rate.findText(str(s.sample_rate))
        if sr_idx >= 0:
            self.cmb_sample_rate.setCurrentIndex(sr_idx)
        buf_idx = self.cmb_buffer.findText(str(s.buffer_size))
        if buf_idx >= 0:
            self.cmb_buffer.setCurrentIndex(buf_idx)
        self.chk_silence.setChecked(s.produce_silence)

        # Metadata
        type_map = {"file": 0, "url": 1, "static": 2}
        self.cmb_meta_type.setCurrentIndex(type_map.get(m.source_type, 0))
        self.inp_meta_file.setText(m.file_path)
        self.inp_meta_url.setText(m.url)
        self.inp_static.setText(m.static_text)
        self.chk_first_line.setChecked(m.use_first_line)
        self.spn_poll.setValue(m.poll_interval)
        self.inp_fallback.setText(m.fallback_text)

        # General
        self.chk_autoconnect.setChecked(g.auto_connect)
        self.chk_start_boot.setChecked(g.start_on_boot)
        self.chk_start_min.setChecked(g.start_minimized)
        self.spn_fps.setValue(g.meter_fps)
        ll_idx = self.cmb_log_level.findText(g.log_level)
        if ll_idx >= 0:
            self.cmb_log_level.setCurrentIndex(ll_idx)

        # API
        self.chk_api_enabled.setChecked(g.http_api_enabled)
        self.spn_api_port.setValue(g.http_api_port)
        self.inp_api_password.setText(getattr(g, "http_api_password", ""))

    # ------------------------------------------------------------------
    # Accept — write back
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        s = self._config.source
        m = self._config.metadata
        g = self._config.settings

        # Source
        dev_data = self.cmb_device.currentData()
        if dev_data is not None:
            s.device_index = dev_data.get("index", -1)
            s.device_name  = dev_data.get("name", "")
        s.sample_rate  = int(self.cmb_sample_rate.currentText())
        s.buffer_size  = int(self.cmb_buffer.currentText())
        s.produce_silence = self.chk_silence.isChecked()

        # Metadata
        type_map = {0: "file", 1: "url", 2: "static"}
        m.source_type   = type_map[self.cmb_meta_type.currentIndex()]
        m.file_path     = self.inp_meta_file.text().strip()
        m.url           = self.inp_meta_url.text().strip()
        m.static_text   = self.inp_static.text().strip()
        m.use_first_line = self.chk_first_line.isChecked()
        m.poll_interval = self.spn_poll.value()
        m.fallback_text = self.inp_fallback.text().strip() or "Steaming Stream"

        # General
        g.auto_connect   = self.chk_autoconnect.isChecked()
        g.start_on_boot  = self.chk_start_boot.isChecked()
        g.start_minimized = self.chk_start_min.isChecked()
        g.meter_fps      = self.spn_fps.value()
        g.log_level      = self.cmb_log_level.currentText()

        # API
        g.http_api_enabled   = self.chk_api_enabled.isChecked()
        g.http_api_port      = self.spn_api_port.value()
        g.http_api_password  = self.inp_api_password.text()

        self.accept()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_devices(self) -> None:
        from src.core.audio import AudioEngine
        self.cmb_device.clear()
        devices = AudioEngine.list_devices()
        if not devices:
            self.cmb_device.addItem("(no devices found — install sounddevice)", {})
            return
        for dev in devices:
            self.cmb_device.addItem(dev.display_name(), {"index": dev.index, "name": dev.name})

    def _on_meta_type_changed(self, idx: int) -> None:
        # Show/hide rows based on source type
        # 0=file, 1=url, 2=static
        show_file   = idx == 0
        show_url    = idx == 1
        show_static = idx == 2

        self.inp_meta_file.setVisible(show_file)
        self.inp_meta_url.setVisible(show_url)
        self.inp_static.setVisible(show_static)
        self.chk_first_line.setVisible(idx in (0, 1))
        self.spn_poll.setEnabled(idx in (0, 1))

    def _browse_metadata_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select now-playing file",
            filter="Text files (*.txt);;All files (*)"
        )
        if path:
            self.inp_meta_file.setText(path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setObjectName("form_separator")
    return f
