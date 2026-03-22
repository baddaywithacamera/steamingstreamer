"""
STEAMING STREAM — Configuration Model
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Dataclasses for all app configuration. Serialises to/from JSON.
Default values match the Squirrel FM reference setup.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

@dataclass
class EncoderConfig:
    id:               str  = field(default_factory=lambda: uuid.uuid4().hex[:8])
    enabled:          bool = True
    name:             str  = "New Encoder"
    format:           str  = "AAC"       # "AAC" | "MP3"
    bitrate:          int  = 128         # kbps
    sample_rate:      int  = 44100       # Hz
    channels:         str  = "stereo"   # "stereo" | "mono"
    server:           str  = ""
    port:             int  = 8000
    mount:            str  = "/live"
    password:         str  = ""
    server_type:      str  = "shoutcast2" # "icecast" | "shoutcast1" | "shoutcast2"
    auto_reconnect:   bool = True
    reconnect_delay:  int  = 5           # seconds
    reconnect_max:    int  = 0           # 0 = infinite
    public_directory: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "EncoderConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SourceConfig:
    device_name:  str = ""
    device_index: int = -1     # -1 = use name to resolve at runtime
    sample_rate:  int = 44100
    channels:     int = 2
    buffer_size:  int = 1024
    produce_silence: bool = False


@dataclass
class MetadataConfig:
    source_type:    str   = "file"    # "file" | "url" | "static"
    file_path:      str   = ""
    url:            str   = ""
    static_text:    str   = "Steaming Stream"
    use_first_line: bool  = True
    poll_interval:  float = 2.0       # seconds
    encoding:       str   = "utf-8"
    fallback_text:  str   = "Steaming Stream"


@dataclass
class AppSettings:
    start_on_boot:      bool = False
    start_minimized:    bool = False
    auto_connect:       bool = False
    meter_style:        str  = "led"   # "led" | "vu"
    show_spectrum:      bool = False
    meter_fps:          int  = 30
    log_level:          str  = "info"  # "info" | "warning" | "error"
    save_log:           bool = False
    log_path:           str  = ""
    http_api_enabled:   bool = True
    http_api_port:      int  = 9000
    http_api_password:  str  = ""


# ---------------------------------------------------------------------------
# Root config (one profile)
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    profile_name: str            = "Default"
    source:       SourceConfig   = field(default_factory=SourceConfig)
    metadata:     MetadataConfig = field(default_factory=MetadataConfig)
    encoders:     List[EncoderConfig] = field(default_factory=list)
    settings:     AppSettings    = field(default_factory=AppSettings)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        cfg = cls()
        cfg.profile_name = d.get("profile_name", "Default")
        if "source" in d:
            cfg.source = SourceConfig(**{
                k: v for k, v in d["source"].items()
                if k in SourceConfig.__dataclass_fields__
            })
        if "metadata" in d:
            cfg.metadata = MetadataConfig(**{
                k: v for k, v in d["metadata"].items()
                if k in MetadataConfig.__dataclass_fields__
            })
        if "encoders" in d:
            cfg.encoders = [EncoderConfig.from_dict(e) for e in d["encoders"]]
        if "settings" in d:
            cfg.settings = AppSettings(**{
                k: v for k, v in d["settings"].items()
                if k in AppSettings.__dataclass_fields__
            })
        return cfg

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Factory: Squirrel FM reference config
# ---------------------------------------------------------------------------

MAX_ENCODERS = 10


def squirrelfm_defaults() -> AppConfig:
    """
    Default config for new installs — no encoders pre-loaded.
    User adds what they need (up to MAX_ENCODERS).
    """
    return AppConfig(profile_name="Default")
