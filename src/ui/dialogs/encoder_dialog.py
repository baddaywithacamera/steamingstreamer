"""
STEAMING STREAM — Encoder Configuration Dialog
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Four-tab dialog for configuring a single encoder slot.
  Connection  — server, port, mount, password, format, bitrate
  Station     — stream name, description, genre, URL (Shoutcast directory info)
  Metadata    — per-encoder metadata override (inherits global by default)
  Statistics  — live listener count, peak, uptime, current track (read-only)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.config import EncoderConfig


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class EncoderDialog(QDialog):
    """Edit or create an encoder slot."""

    def __init__(self, encoder: EncoderConfig | None = None, parent=None):
        super().__init__(parent)
        self._encoder = encoder or EncoderConfig()
        self._is_new  = encoder is None

        self.setWindowTitle("Add Encoder" if self._is_new else "Edit Encoder")
        self.setMinimumWidth(460)
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

        # Display name at top (outside tabs, always visible)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Display name:"))
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("e.g.  AAC 128k — Standard")
        name_row.addWidget(self.inp_name, stretch=1)

        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.setChecked(True)
        name_row.addWidget(self.chk_enabled)

        root.addLayout(name_row)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_connection(), "Connection")
        self.tabs.addTab(self._tab_station(),    "Station Info")
        self.tabs.addTab(self._tab_metadata(),   "Metadata")
        self.tabs.addTab(self._tab_statistics(), "Statistics")
        root.addWidget(self.tabs)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Tab: Connection
    # ------------------------------------------------------------------

    def _tab_connection(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Server
        self.inp_server = QLineEdit()
        self.inp_server.setPlaceholderText("e.g.  streaming.myradiostream.com")
        form.addRow("Server:", self.inp_server)

        # Port
        self.inp_port = QSpinBox()
        self.inp_port.setRange(1, 65535)
        self.inp_port.setValue(8000)
        self.inp_port.setFixedWidth(90)
        form.addRow("Port:", self.inp_port)

        # Server type (before mount/SID so toggling it updates the labels)
        self.cmb_server_type = QComboBox()
        self.cmb_server_type.addItem("Shoutcast 2 / MRS",    "shoutcast2")
        self.cmb_server_type.addItem("Icecast 2",             "icecast")
        self.cmb_server_type.addItem("Shoutcast 1 (legacy)",  "shoutcast1")
        self.cmb_server_type.setFixedWidth(180)
        self.cmb_server_type.currentIndexChanged.connect(self._on_server_type_changed)
        form.addRow("Server type:", self.cmb_server_type)

        # Stream ID — Shoutcast 2 / MRS only
        self.spn_stream_id = QSpinBox()
        self.spn_stream_id.setRange(1, 99)
        self.spn_stream_id.setValue(1)
        self.spn_stream_id.setFixedWidth(60)
        self._lbl_stream_id = form.addRow("Stream ID (SID):", self.spn_stream_id)

        # Mount — Icecast / Shoutcast 1
        self.inp_mount = QLineEdit()
        self.inp_mount.setPlaceholderText("/live")
        self._lbl_mount = form.addRow("Mount point:", self.inp_mount)

        # Password
        pw_row = QHBoxLayout()
        self.inp_password = QLineEdit()
        self.inp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_password.setPlaceholderText("Source password from MRS control panel")
        self.btn_show_pw = QPushButton("show")
        self.btn_show_pw.setCheckable(True)
        self.btn_show_pw.setFixedWidth(48)
        self.btn_show_pw.toggled.connect(self._toggle_password)
        pw_row.addWidget(self.inp_password)
        pw_row.addWidget(self.btn_show_pw)
        form.addRow("Password:", pw_row)

        form.addRow(_separator())

        # Format + bitrate on one row
        format_row = QHBoxLayout()
        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["AAC", "AAC+", "MP3"])
        self.cmb_format.setFixedWidth(80)

        self.cmb_bitrate = QComboBox()
        self._populate_bitrates("AAC")
        self.cmb_format.currentTextChanged.connect(self._populate_bitrates)

        format_row.addWidget(self.cmb_format)
        format_row.addWidget(QLabel("kbps:"))
        format_row.addWidget(self.cmb_bitrate)
        format_row.addStretch()
        form.addRow("Format:", format_row)

        # Sample rate + channels
        sr_row = QHBoxLayout()
        self.cmb_sample_rate = QComboBox()
        self.cmb_sample_rate.addItems(["32000", "44100", "48000"])
        self.cmb_sample_rate.setCurrentIndex(1)  # default 44100
        self.cmb_sample_rate.setFixedWidth(80)

        self.cmb_channels = QComboBox()
        self.cmb_channels.addItems(["stereo", "mono"])
        self.cmb_channels.setFixedWidth(80)

        sr_row.addWidget(self.cmb_sample_rate)
        sr_row.addWidget(QLabel("Hz    Channels:"))
        sr_row.addWidget(self.cmb_channels)
        sr_row.addStretch()
        form.addRow("Sample rate:", sr_row)

        form.addRow(_separator())

        # Reconnect
        rc_row = QHBoxLayout()
        self.chk_reconnect = QCheckBox("Auto reconnect every")
        self.chk_reconnect.setChecked(True)
        self.spn_reconnect_delay = QSpinBox()
        self.spn_reconnect_delay.setRange(1, 300)
        self.spn_reconnect_delay.setValue(5)
        self.spn_reconnect_delay.setFixedWidth(60)
        self.spn_reconnect_delay.setSuffix(" sec")

        rc_row.addWidget(self.chk_reconnect)
        rc_row.addWidget(self.spn_reconnect_delay)
        rc_row.addStretch()
        form.addRow("", rc_row)

        # Max reconnect attempts
        max_row = QHBoxLayout()
        self.spn_reconnect_max = QSpinBox()
        self.spn_reconnect_max.setRange(0, 9999)
        self.spn_reconnect_max.setValue(0)
        self.spn_reconnect_max.setFixedWidth(70)
        max_row.addWidget(self.spn_reconnect_max)
        max_row.addWidget(QLabel("  (0 = infinite)"))
        max_row.addStretch()
        form.addRow("Max attempts:", max_row)

        # Public directory
        self.chk_public = QCheckBox("List in public stream directory")
        form.addRow("", self.chk_public)

        return w

    # ------------------------------------------------------------------
    # Tab: Station Info
    # ------------------------------------------------------------------

    def _tab_station(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.inp_station_name = QLineEdit()
        self.inp_station_name.setPlaceholderText("Squirrel FM")
        form.addRow("Station name:", self.inp_station_name)

        self.inp_genre = QLineEdit()
        self.inp_genre.setPlaceholderText("Variety")
        form.addRow("Genre:", self.inp_genre)

        self.inp_station_url = QLineEdit()
        self.inp_station_url.setPlaceholderText("https://squirrelfm.ca")
        form.addRow("Station URL:", self.inp_station_url)

        self.inp_description = QLineEdit()
        self.inp_description.setPlaceholderText("Squirrel FM — all the good stuff")
        form.addRow("Description:", self.inp_description)

        note = QLabel(
            "Station info is sent to the Shoutcast/Icecast server on connect.\n"
            "It appears in stream directories if 'List in directory' is enabled."
        )
        note.setObjectName("hint_label")
        note.setWordWrap(True)
        form.addRow("", note)

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

        self.chk_meta_inherit = QCheckBox("Use global metadata settings")
        self.chk_meta_inherit.setChecked(True)
        self.chk_meta_inherit.toggled.connect(self._toggle_metadata_override)
        form.addRow("", self.chk_meta_inherit)

        form.addRow(_separator())

        # Override fields (disabled while inherit is checked)
        self.meta_override_widgets = []

        self.cmb_meta_source = QComboBox()
        self.cmb_meta_source.addItems(["Read from file", "Read from URL", "Static text"])
        form.addRow("Source:", self.cmb_meta_source)
        self.meta_override_widgets.append(self.cmb_meta_source)

        file_row = QHBoxLayout()
        self.inp_meta_file = QLineEdit()
        self.inp_meta_file.setPlaceholderText("Path to now-playing text file")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(28)
        file_row.addWidget(self.inp_meta_file)
        file_row.addWidget(btn_browse)
        form.addRow("File path:", file_row)
        self.meta_override_widgets += [self.inp_meta_file, btn_browse]

        self.chk_first_line = QCheckBox("Use first line only")
        self.chk_first_line.setChecked(True)
        form.addRow("", self.chk_first_line)
        self.meta_override_widgets.append(self.chk_first_line)

        self._toggle_metadata_override(True)

        return w

    # ------------------------------------------------------------------
    # Tab: Statistics (read-only, populated at runtime)
    # ------------------------------------------------------------------

    def _tab_statistics(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.lbl_stat_status    = _stat_value("—")
        self.lbl_stat_listeners = _stat_value("—")
        self.lbl_stat_peak      = _stat_value("—")
        self.lbl_stat_uptime    = _stat_value("—")
        self.lbl_stat_track     = _stat_value("—")

        form.addRow("Status:",           self.lbl_stat_status)
        form.addRow("Listeners:",        self.lbl_stat_listeners)
        form.addRow("Peak listeners:",   self.lbl_stat_peak)
        form.addRow("Uptime:",           self.lbl_stat_uptime)
        form.addRow("Current track:",    self.lbl_stat_track)

        form.addRow(_separator())

        note = QLabel("Statistics update when the encoder is connected.")
        note.setObjectName("hint_label")
        form.addRow("", note)

        return w

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _populate_bitrates(self, fmt: str = "AAC") -> None:
        aac_rates  = ["32", "48", "64", "96", "128", "192", "256", "320"]
        aacp_rates = ["16", "24", "32", "40", "48", "64"]   # AAC+ shines at low bitrates
        mp3_rates  = ["32", "48", "64", "96", "128", "160", "192", "256", "320"]
        if fmt == "MP3":
            rates = mp3_rates
        elif fmt == "AAC+":
            rates = aacp_rates
        else:
            rates = aac_rates
        current = self.cmb_bitrate.currentText() if self.cmb_bitrate.count() else "128"
        self.cmb_bitrate.blockSignals(True)
        self.cmb_bitrate.clear()
        self.cmb_bitrate.addItems(rates)
        idx = self.cmb_bitrate.findText(current)
        self.cmb_bitrate.setCurrentIndex(idx if idx >= 0 else rates.index("128") if "128" in rates else 0)
        self.cmb_bitrate.blockSignals(False)

    def _on_server_type_changed(self, _index: int) -> None:
        is_sc2 = self.cmb_server_type.currentData() == "shoutcast2"
        self.spn_stream_id.setVisible(is_sc2)
        self.inp_mount.setVisible(not is_sc2)

    def _toggle_password(self, show: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        self.inp_password.setEchoMode(mode)
        self.btn_show_pw.setText("hide" if show else "show")

    def _toggle_metadata_override(self, inherit: bool) -> None:
        for w in self.meta_override_widgets:
            w.setEnabled(not inherit)

    # ------------------------------------------------------------------
    # Populate from config
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        enc = self._encoder
        self.inp_name.setText(enc.name)
        self.chk_enabled.setChecked(enc.enabled)

        self.inp_server.setText(enc.server)
        self.inp_port.setValue(enc.port)
        self.inp_mount.setText(enc.mount)
        self.spn_stream_id.setValue(getattr(enc, "stream_id", 1))

        # Station Info tab
        self.inp_station_name.setText(getattr(enc, "station_name", ""))
        self.inp_genre.setText(getattr(enc, "genre", ""))
        self.inp_station_url.setText(getattr(enc, "url", ""))
        self.inp_description.setText(getattr(enc, "description", ""))

        # Server type — also triggers SID/mount visibility
        for i in range(self.cmb_server_type.count()):
            if self.cmb_server_type.itemData(i) == enc.server_type:
                self.cmb_server_type.setCurrentIndex(i)
                break
        self._on_server_type_changed(0)  # ensure correct field is visible

        self.inp_password.setText(enc.password)

        fmt_idx = self.cmb_format.findText(enc.format if enc.format else "AAC")
        if fmt_idx >= 0:
            self.cmb_format.setCurrentIndex(fmt_idx)
        self._populate_bitrates(enc.format)
        br_idx = self.cmb_bitrate.findText(str(enc.bitrate))
        if br_idx >= 0:
            self.cmb_bitrate.setCurrentIndex(br_idx)

        sr_idx = self.cmb_sample_rate.findText(str(enc.sample_rate))
        if sr_idx >= 0:
            self.cmb_sample_rate.setCurrentIndex(sr_idx)

        ch_idx = self.cmb_channels.findText(enc.channels)
        if ch_idx >= 0:
            self.cmb_channels.setCurrentIndex(ch_idx)

        self.chk_reconnect.setChecked(enc.auto_reconnect)
        self.spn_reconnect_delay.setValue(enc.reconnect_delay)
        self.spn_reconnect_max.setValue(enc.reconnect_max)
        self.chk_public.setChecked(enc.public_directory)

    # ------------------------------------------------------------------
    # Accept — write back to config object
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        enc = self._encoder
        enc.name            = self.inp_name.text().strip() or "Encoder"
        enc.enabled         = self.chk_enabled.isChecked()
        enc.server          = self.inp_server.text().strip()
        enc.port            = self.inp_port.value()
        enc.mount           = self.inp_mount.text().strip() or "/live"
        enc.stream_id       = self.spn_stream_id.value()
        enc.server_type     = self.cmb_server_type.currentData() or "shoutcast2"
        enc.password        = self.inp_password.text().strip()
        enc.format          = self.cmb_format.currentText()
        enc.bitrate         = int(self.cmb_bitrate.currentText())
        enc.sample_rate     = int(self.cmb_sample_rate.currentText())
        enc.channels        = self.cmb_channels.currentText()
        enc.auto_reconnect  = self.chk_reconnect.isChecked()
        enc.reconnect_delay = self.spn_reconnect_delay.value()
        enc.reconnect_max   = self.spn_reconnect_max.value()
        enc.public_directory = self.chk_public.isChecked()

        # Station Info tab
        enc.station_name = self.inp_station_name.text().strip()
        enc.genre        = self.inp_genre.text().strip()
        enc.url          = self.inp_station_url.text().strip()
        enc.description  = self.inp_description.text().strip()

        self.accept()

    def get_encoder(self) -> EncoderConfig:
        """Return the (possibly modified) encoder config."""
        return self._encoder


# ---------------------------------------------------------------------------
# Minor helpers
# ---------------------------------------------------------------------------

def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setObjectName("form_separator")
    return line


def _stat_value(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("stat_value")
    return lbl
