#!/usr/bin/env python3
"""
Hyprland auto-tag daemon: marks "media-like" windows with a tag (default: 'opaque')
based on configurable rules (classes, title patterns, class+title AND rules, fullscreen).
Requires a Hyprland rule:
  windowrulev2 = opacity 1.0 1.0 override, tag:opaque

Config (JSON) default path: ~/.config/hypr-opaque-media.json
Environment:
  HYPRO_CONFIG             - override config path
  HYPRO_LOG_LEVEL          - logging level (DEBUG, INFO, WARNING, ERROR), overrides config
  HYPRO_NOTIFY_ON_ERRORS=1 - force desktop notifications on critical errors
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, fields
from typing import Any

# Optional watchdog (file change monitoring). Falls back to polling if not available or disabled.
try:
    from watchdog.events import FileSystemEventHandler  # type: ignore
    from watchdog.observers import Observer  # type: ignore

    HAVE_WATCHDOG = True
except Exception:
    HAVE_WATCHDOG = False

CONFIG_PATH = os.path.expanduser(os.environ.get("HYPRO_CONFIG", "~/.config/hypr-opaque-media.json"))

# --------------------------------------------------------------------------------------
# Metrics (optional)

_METRICS_ENABLED: bool = False
_METRICS_LOG_EVERY: int = 1000
_METRICS: dict[str, int] = {
    "events_processed": 0,
    "hyprctl_calls": 0,
    "hyprctl_errors": 0,
    "max_cache_size": 0,
    "current_cache_size": 0,
    "bytes_read": 0,
    "event_processing_time_ms": 0,
    "max_event_processing_time_ms": 0,
    "unsupported_events": 0,
    "buffer_size_exceeded": 0,
    "tag_operations": 0,
    "log_file_rotations": 0,
    "config_reload_time_ms": 0,
    "config_reloads": 0,
    "notifications_sent": 0,
    "invalid_regex_patterns": 0,
}

# Runtime‑детектор поддержки address‑фильтра у hyprctl clients
_ADDRESS_FILTER_SUPPORTED: bool | None = None


def _metrics_inc(key: str, delta: int = 1) -> None:
    if _METRICS_ENABLED:
        _METRICS[key] = _METRICS.get(key, 0) + delta


def _metrics_maybe_log() -> None:
    if not _METRICS_ENABLED:
        return
    avg_ms = 0
    if _METRICS.get("events_processed", 0) > 0:
        avg_ms = _METRICS.get("event_processing_time_ms", 0) // max(1, _METRICS["events_processed"])
    # Логируем по числу событий, реже по числу вызовов hyprctl (x10 интервал) и объёму байт
    if (
        _METRICS["events_processed"] % max(1, _METRICS_LOG_EVERY) == 0
        or _METRICS["hyprctl_calls"] % max(1, _METRICS_LOG_EVERY * 10) == 0
        or _METRICS["bytes_read"] % max(1, _METRICS_LOG_EVERY * 4096) == 0
    ):
        log.info(
            "Metrics: events=%s hyprctl_calls=%s hyprctl_errors=%s max_cache_size=%s "
            "current_cache_size=%s bytes_read=%s avg_event_time_ms=%s max_event_time_ms=%s "
            "unsupported_events=%s buffer_size_exceeded=%s tag_operations=%s log_rotations=%s "
            "config_reloads=%s config_reload_time_ms=%s notifications_sent=%s invalid_regex=%s",
            _METRICS["events_processed"],
            _METRICS["hyprctl_calls"],
            _METRICS["hyprctl_errors"],
            _METRICS["max_cache_size"],
            _METRICS["current_cache_size"],
            _METRICS["bytes_read"],
            avg_ms,
            _METRICS["max_event_processing_time_ms"],
            _METRICS["unsupported_events"],
            _METRICS["buffer_size_exceeded"],
            _METRICS["tag_operations"],
            _METRICS["log_file_rotations"],
            _METRICS["config_reloads"],
            _METRICS["config_reload_time_ms"],
            _METRICS["notifications_sent"],
            _METRICS["invalid_regex_patterns"],
        )


def _metrics_update_max_cache(clients_len: int) -> None:
    if _METRICS_ENABLED:
        _METRICS["current_cache_size"] = clients_len
        if clients_len > _METRICS.get("max_cache_size", 0):
            _METRICS["max_cache_size"] = clients_len


# --------------------------------------------------------------------------------------
# Logging


def _make_logger(
    level_name: str = "INFO", fmt: str = "[hypr-opaque] %(levelname)s: %(message)s"
) -> logging.Logger:
    logger = logging.getLogger("hypr-opaque")
    if logger.handlers:
        # Update level/format if logger already exists
        logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))
        _apply_log_format(fmt)
        return logger
    lvl = getattr(logging, level_name.upper(), logging.INFO)
    logger.setLevel(lvl)
    h = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(fmt)
    h.setFormatter(formatter)
    logger.addHandler(h)
    return logger


def _apply_log_format(fmt: str) -> None:
    """Apply formatter to all existing handlers with validation and fallback."""
    logger = logging.getLogger("hypr-opaque")
    try:
        formatter = logging.Formatter(fmt)
    except Exception as e:
        default_fmt = DEFAULT_CONFIG.get("log_format", "[hypr-opaque] %(levelname)s: %(message)s")
        log.warning("Invalid log_format '%s', falling back to default: %s", fmt, e)
        formatter = logging.Formatter(default_fmt)
    for h in logger.handlers:
        try:
            h.setFormatter(formatter)
        except Exception as e:
            log.warning("Failed to apply formatter to handler: %s", e)


log = _make_logger(os.environ.get("HYPRO_LOG_LEVEL", "INFO"))


def _has_notify_send() -> bool:
    try:
        subprocess.run(
            ["notify-send", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return True
    except FileNotFoundError:
        log.warning("notify-send not found, notifications disabled")
        return False
    except Exception as e:
        log.warning("notify-send check failed: %s", e)
        return False


def notify_error(msg: str, enabled: bool) -> None:
    """Send critical desktop notification if enabled; checks notify-send availability."""
    if not enabled:
        return
    if not _has_notify_send():
        return
    try:
        subprocess.run(
            ["notify-send", "-u", "critical", "hypr-opaque-media", msg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        _metrics_inc("notifications_sent")
    except Exception as e:
        log.warning("Failed to send notification: %s", e)


# --------------------------------------------------------------------------------------
# Hyprctl helpers


def sh_json(args: list[str]) -> Any | None:
    """Run 'hyprctl <args> -j' and parse JSON. Returns None on error."""
    _metrics_inc("hyprctl_calls")
    try:
        p = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True)
    except FileNotFoundError:
        log.error("hyprctl not found in PATH")
        _metrics_inc("hyprctl_errors")
        return None
    except Exception as e:
        log.error("hyprctl failed to run %s: %s", " ".join(args), e)
        _metrics_inc("hyprctl_errors")
        return None
    if p.returncode != 0:
        log.debug(
            "hyprctl %s returned %s: %s", " ".join(args), p.returncode, (p.stderr or "").strip()
        )
        _metrics_inc("hyprctl_errors")
        return None
    try:
        return json.loads(p.stdout)
    except Exception as e:
        log.warning("JSON parse error for hyprctl %s: %s", " ".join(args), e)
        _metrics_inc("hyprctl_errors")
        return None


@dataclass
class ClientInfo:
    address: str
    cls: str = ""
    title: str = ""
    fullscreen: bool = False
    minimized: bool = False
    urgent: bool = False
    tags: set[str] = field(default_factory=set)


def hypr_clients() -> dict[str, ClientInfo]:
    """Get all clients and map by address."""
    data = sh_json(["clients"]) or []
    out: dict[str, ClientInfo] = {}
    for c in data:
        addr = c.get("address")
        if not addr:
            continue
        out[addr] = ClientInfo(
            address=addr,
            cls=(c.get("class") or c.get("initialClass") or "").lower(),
            title=(c.get("title") or c.get("initialTitle") or ""),
            fullscreen=bool(c.get("fullscreen")),
            minimized=bool(c.get("minimized")),
            urgent=bool(c.get("urgent")),
            tags=set(c.get("tags") or []),
        )
    return out


def hypr_client_by_address(address: str) -> ClientInfo | None:
    """
    Try to fetch a single client by address using hyprctl filter if available,
    fall back to scanning the full list. After first failure, stop using the filter.
    """
    global _ADDRESS_FILTER_SUPPORTED

    # Если ещё не знаем, попробуем один раз
    if _ADDRESS_FILTER_SUPPORTED is not False:
        data = sh_json(["clients", f"address:{address}"])
        # При успехе hyprctl может вернуть dict или list с записью
        if isinstance(data, dict) and data.get("address") == address:
            return ClientInfo(
                address=address,
                cls=(data.get("class") or data.get("initialClass") or "").lower(),
                title=(data.get("title") or data.get("initialTitle") or ""),
                fullscreen=bool(data.get("fullscreen")),
                minimized=bool(data.get("minimized")),
                urgent=bool(data.get("urgent")),
                tags=set(data.get("tags") or []),
            )
        if isinstance(data, list):
            for c in data:
                if isinstance(c, dict) and c.get("address") == address:
                    return ClientInfo(
                        address=address,
                        cls=(c.get("class") or c.get("initialClass") or "").lower(),
                        title=(c.get("title") or c.get("initialTitle") or ""),
                        fullscreen=bool(c.get("fullscreen")),
                        minimized=bool(c.get("minimized")),
                        urgent=bool(c.get("urgent")),
                        tags=set(c.get("tags") or []),
                    )
        # Если дошли сюда — фильтр не дал результата (или JSON невалидный) — больше не пробуем
        _ADDRESS_FILTER_SUPPORTED = False

    # Фоллбек: полный список
    allc = sh_json(["clients"]) or []
    for c in allc:
        if c.get("address") == address:
            return ClientInfo(
                address=address,
                cls=(c.get("class") or c.get("initialClass") or "").lower(),
                title=(c.get("title") or c.get("initialTitle") or ""),
                fullscreen=bool(c.get("fullscreen")),
                minimized=bool(c.get("minimized")),
                urgent=bool(c.get("urgent")),
                tags=set(c.get("tags") or []),
            )
    return None


def toggle_tag(address: str, tag: str) -> None:
    """Toggle a tag on a specific window address."""
    result = subprocess.run(
        ["hyprctl", "dispatch", "tagwindow", tag, f"address:{address}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        log.debug("Failed to toggle tag %s for %s: returncode=%s", tag, address, result.returncode)
    else:
        log.debug("Toggled tag %s for %s", tag, address)


def ensure_tag(address: str, tag: str, want: bool, known_tags: set[str]) -> bool:
    """
    Ensure window at 'address' has (or doesn't have) 'tag'.
    Calls hyprctl only when state changes. Returns True if changed.
    """
    has = tag in known_tags
    if want != has:
        toggle_tag(address, tag)
        _metrics_inc("tag_operations")
        # optimistic local update
        if want:
            known_tags.add(tag)
        else:
            known_tags.discard(tag)
        log.debug("tag %s %s", ("+" if want else "-"), address)
        return True
    return False


# --------------------------------------------------------------------------------------
# Events


def parse_event(line: bytes) -> tuple[str | None, dict[str, str]]:
    """Parse socket2 line: either JSON payload (event>>{...}) or legacy k:v,k:v."""
    if not line:
        return None, {}
    try:
        head, payload = line.split(b">>", 1)
    except ValueError:
        return None, {}
    ev = head.decode(errors="ignore").strip()
    payload = payload.strip()

    # Try JSON payload first
    if payload.startswith(b"{") and payload.endswith(b"}"):
        try:
            obj = json.loads(payload.decode("utf-8", "ignore"))
            parts: dict[str, str] = {}
            if isinstance(obj, dict):
                for k, v in obj.items():
                    parts[str(k)] = "" if v is None else str(v)
            return ev, parts
        except Exception:
            pass  # fall back

    # Legacy k:v,k:v parsing; strip quotes from both keys and values
    parts: dict[str, str] = {}
    for chunk in payload.split(b","):
        if b":" not in chunk:
            continue
        k, v = chunk.split(b":", 1)
        ks = k.decode(errors="ignore").strip().strip('"').strip("'")
        vs = v.decode(errors="ignore").strip().strip('"').strip("'")
        parts[ks] = vs
    return ev, parts


def normalize_event_name(ev: str) -> str:
    """Map new '-v2' events back to legacy names the handler understands."""
    if ev.endswith("v2"):
        return ev[:-2]
    return ev


def _normalize_address_string(addr: str | None) -> str | None:
    """Return normalized hex address like 0x..., or None."""
    if not addr:
        return None
    a = addr.strip()
    # некоторые payload присылают address в виде "0x..." уже ок
    # на всякий случай оставим простую проверку
    return a if a.startswith("0x") else None


def get_address_from_parts(parts: dict[str, str]) -> str | None:
    """Try to extract window address from various possible keys."""
    candidates = (
        "address",
        "addr",
        "windowaddress",
        "window_address",
        "windowAddr",
        "window",
    )
    for k in candidates:
        if k in parts:
            a = _normalize_address_string(parts.get(k))
            if a:
                return a
    return None


def hypr_active_window_address() -> str | None:
    """Get the currently active window address via hyprctl."""
    data = sh_json(["activewindow"])
    if isinstance(data, dict):
        return _normalize_address_string(str(data.get("address", "") or ""))
    return None


# --------------------------------------------------------------------------------------
# Matching logic


@dataclass
class RuleConfig:
    tag: str = "opaque"
    fullscreen_is_media: bool = True
    minimized_is_opaque: bool = True
    urgent_is_opaque: bool = True
    case_insensitive: bool = True
    classes: list[str] = field(default_factory=list)
    title_patterns: list[str] = field(default_factory=list)
    class_title_rules: list[dict[str, str]] = field(default_factory=list)
    # Localized title pattern groups: {"en": [...], "ru": [...]}
    title_patterns_localized: dict[str, list[str]] = field(default_factory=dict)
    config_poll_interval_sec: float = 8.0
    socket_timeout_sec: float = 1.0
    use_watchdog: bool = False
    notify_on_errors: bool = False
    log_level: str = "INFO"
    # Safety/perf tweaks
    safe_close_check: bool = False
    safe_close_check_delay_sec: float = 0.1
    max_reconnect_attempts: int = 0  # 0 = infinite
    # Metrics
    enable_metrics: bool = False
    metrics_log_every: int = 1000
    # Cache maintenance / heartbeat
    cache_clean_interval_sec: float = 300.0
    heartbeat_interval_sec: float = 600.0
    buffer_log_interval_sec: float = 600.0
    # Buffer safety
    max_buffer_size_bytes: int = 1048576
    # Socket read buffer
    socket_buffer_size_bytes: int = 4096
    # File logging
    log_file: str | None = None
    max_log_file_size_bytes: int = 1048576
    max_log_rotations: int = 5
    # Log format
    log_format: str = "[hypr-opaque] %(levelname)s: %(message)s"


class Matcher:
    """
    Compiled rules engine for deciding if a window should be opaque.
    """

    def __init__(self, cfg: RuleConfig):
        flags = re.IGNORECASE if cfg.case_insensitive else 0

        # exact class matches
        self.class_set: set[str] = {
            str(x).lower().strip() for x in cfg.classes if isinstance(x, str) and x.strip()
        }

        # title regex
        self.title_res: list[re.Pattern] = []

        def _compile_many(patterns: list[str]) -> None:
            for pat in patterns:
                if not isinstance(pat, str) or not pat.strip():
                    continue
                try:
                    self.title_res.append(re.compile(pat, flags))
                except re.error as e:
                    log.warning("Bad title regex skipped: %r (%s)", pat, e)
                    _metrics_inc("invalid_regex_patterns")

        _compile_many(cfg.title_patterns)
        # localized groups (merge flat)
        for _, patterns in (cfg.title_patterns_localized or {}).items():
            if not isinstance(patterns, list):
                continue
            _compile_many([p for p in patterns if isinstance(p, str)])

        # class+title AND rules
        self.class_title_rules: list[tuple[re.Pattern, re.Pattern]] = []
        for r in cfg.class_title_rules:
            if not isinstance(r, dict):
                continue
            cr, tr = r.get("class_regex"), r.get("title_regex")
            if (
                not isinstance(cr, str)
                or not cr.strip()
                or not isinstance(tr, str)
                or not tr.strip()
            ):
                continue
            try:
                self.class_title_rules.append((re.compile(cr, flags), re.compile(tr, flags)))
            except re.error as e:
                log.warning("Bad class/title rule skipped: %r (%s)", r, e)
                _metrics_inc("invalid_regex_patterns")

        self.fullscreen_is_media = bool(cfg.fullscreen_is_media)
        self.minimized_is_opaque = bool(cfg.minimized_is_opaque)
        self.urgent_is_opaque = bool(cfg.urgent_is_opaque)

    def should_be_opaque(self, info: ClientInfo) -> bool:
        if self.minimized_is_opaque and info.minimized:
            return True
        if self.urgent_is_opaque and info.urgent:
            return True
        if self.fullscreen_is_media and info.fullscreen:
            return True
        if info.cls in self.class_set:
            return True
        for cr, tr in self.class_title_rules:
            if cr.search(info.cls) and tr.search(info.title):
                return True
        return any(tre.search(info.title) for tre in self.title_res)


# --------------------------------------------------------------------------------------
# Config loading / validation

DEFAULT_CONFIG = {
    "tag": "opaque",
    "fullscreen_is_media": True,
    "minimized_is_opaque": True,
    "urgent_is_opaque": True,
    "case_insensitive": True,
    "classes": [
        "mpv",
        "vlc",
        "celluloid",
        "io.github.celluloid_player.Celluloid",
        "imv",
        "swayimg",
        "nsxiv",
        "feh",
        "loupe",
        "gwenview",
        "ristretto",
        "eog",
        "eom",
    ],
    "title_patterns": [
        "(Picture[- ]in[- ]Picture|Картинка в картинке)",
        "\\.(mp4|mkv|webm|avi|mov|png|jpe?g|webp|gif|bmp|svg|tiff)(\\)|$| |·|—)",
    ],
    "class_title_rules": [
        {"class_regex": "(^|\\b)(firefox)(\\b|$)", "title_regex": "(YouTube|Twitch|Vimeo)"},
        {
            "class_regex": "(chromium|google-?chrome|brave|vivaldi|microsoft-edge)",
            "title_regex": "(YouTube|Twitch|Vimeo)",
        },
    ],
    "title_patterns_localized": {},
    "config_poll_interval_sec": 8.0,
    "socket_timeout_sec": 1.0,
    "use_watchdog": False,
    "notify_on_errors": False,
    "log_level": "INFO",
    "safe_close_check": False,
    "safe_close_check_delay_sec": 0.1,
    "max_reconnect_attempts": 0,
    "enable_metrics": False,
    "metrics_log_every": 1000,
    "cache_clean_interval_sec": 300.0,
    "heartbeat_interval_sec": 600.0,
    "buffer_log_interval_sec": 600.0,
    "max_buffer_size_bytes": 1048576,
    "socket_buffer_size_bytes": 4096,
    "log_file": None,
    "max_log_file_size_bytes": 1048576,
    "max_log_rotations": 5,
    "log_format": "[hypr-opaque] %(levelname)s: %(message)s",
}


def _ensure_file_logging(
    log_file: str | None, max_size: int, max_rotations: int, log_format: str
) -> None:
    if not log_file:
        return
    try:
        # Check write access to directory
        log_dir = os.path.dirname(log_file) or "."
        if not os.access(log_dir, os.W_OK):
            log.warning("Log directory %s is not writable, file logging disabled", log_dir)
            return

        # Rotate if exceeded
        if os.path.exists(log_file):
            try:
                size = os.path.getsize(log_file)
            except OSError:
                size = 0
            if size > max_size:
                try:
                    # Remove oldest backups if exceed limit
                    base = os.path.basename(log_file)
                    try:
                        baks = [
                            f
                            for f in os.listdir(log_dir)
                            if f.startswith(base + ".") and f.endswith(".bak")
                        ]
                        baks.sort(key=lambda fn: os.path.getmtime(os.path.join(log_dir, fn)))
                        while len(baks) >= max_rotations:
                            oldest = baks.pop(0)
                            try:
                                os.remove(os.path.join(log_dir, oldest))
                                log.debug("Removed old rotated log %s", oldest)
                            except Exception as e:
                                log.warning("Failed to remove old rotated log %s: %s", oldest, e)
                    except Exception:
                        pass
                    bak = f"{log_file}.{int(time.time())}.bak"
                    os.rename(log_file, bak)
                    log.warning(
                        "Log file %s exceeded %s bytes (%s), rotated to %s",
                        log_file,
                        max_size,
                        size,
                        bak,
                    )
                    _metrics_inc("log_file_rotations")
                except Exception as e:
                    log.warning("Failed to rotate log file %s: %s", log_file, e)
        logger = logging.getLogger("hypr-opaque")
        # Avoid duplicate handlers to the same file
        for h in logger.handlers:
            if isinstance(h, logging.FileHandler) and getattr(
                h, "baseFilename", None
            ) == os.path.abspath(log_file):
                return
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter(log_format))
        logger.addHandler(fh)
        logger.info("File logging enabled at %s", log_file)
    except Exception as e:
        log.warning("Failed to set up file logging to %s: %s", log_file, e)


def load_config(path: str) -> tuple[RuleConfig, Matcher, float]:
    """
    Load config JSON, shallow-merge with defaults, validate types,
    compile matcher. Returns (cfg, matcher, mtime).
    """
    start_load = time.monotonic()

    cfg_raw = DEFAULT_CONFIG.copy()
    try:
        with open(path, encoding="utf-8") as f:
            user_cfg = json.load(f)
        if isinstance(user_cfg, dict):
            cfg_raw.update(user_cfg)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.error("Config load error: %s", e)

    def _list(val: Any, typ: type) -> list[Any]:
        if not isinstance(val, list):
            return []
        out = []
        for x in val:
            if isinstance(x, typ):
                if typ is str:
                    if x.strip():
                        out.append(x)
                else:
                    out.append(x)
            else:
                log.warning("Invalid config list item skipped: %r", x)
        return out

    def _map_str_list(val: Any) -> dict[str, list[str]]:
        if not isinstance(val, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, v in val.items():
            if isinstance(k, str) and isinstance(v, list):
                out[k] = [p for p in v if isinstance(p, str) and p.strip()]
        return out

    # Helpers: treat values below min as invalid -> use default (not clamped-down)
    def _float_min(val: Any, default: float, min_value: float) -> float:
        try:
            x = float(val)
        except Exception:
            return default
        return default if x < min_value else x

    def _int_min(val: Any, default: int, min_value: int) -> int:
        try:
            x = int(val)
        except Exception:
            return default
        return default if x < min_value else x

    # Metrics log frequency clamp [1..1_000_000]
    raw_metrics_every = cfg_raw.get("metrics_log_every", 1000)
    try:
        metrics_every = int(raw_metrics_every)
    except Exception:
        metrics_every = 1000
    metrics_every = max(1, min(1_000_000, metrics_every))

    poll_sec = _float_min(cfg_raw.get("config_poll_interval_sec", 8.0), 8.0, 0.1)
    sock_to = _float_min(cfg_raw.get("socket_timeout_sec", 1.0), 1.0, 0.1)
    cache_clean_sec = _float_min(cfg_raw.get("cache_clean_interval_sec", 300.0), 300.0, 1.0)
    heartbeat_sec = _float_min(cfg_raw.get("heartbeat_interval_sec", 600.0), 600.0, 1.0)
    buffer_log_sec = _float_min(cfg_raw.get("buffer_log_interval_sec", 600.0), 600.0, 1.0)
    max_buf_bytes = _int_min(cfg_raw.get("max_buffer_size_bytes", 1048576), 1048576, 4096)
    sock_buf_bytes = _int_min(cfg_raw.get("socket_buffer_size_bytes", 4096), 4096, 1024)
    max_log_file_size = _int_min(cfg_raw.get("max_log_file_size_bytes", 1048576), 1048576, 1024)
    max_log_rotations = _int_min(cfg_raw.get("max_log_rotations", 5), 5, 1)
    safe_close_delay = _float_min(cfg_raw.get("safe_close_check_delay_sec", 0.1), 0.1, 0.01)

    # max reconnect non-negative
    try:
        max_reconnect = int(cfg_raw.get("max_reconnect_attempts", 0))
    except Exception:
        max_reconnect = 0
    max_reconnect = max(0, max_reconnect)

    # booleans / strings
    log_file_val = cfg_raw.get("log_file", None)
    if not isinstance(log_file_val, str) or not log_file_val.strip():
        log_file_val = None
    log_format_val = (
        str(cfg_raw.get("log_format", DEFAULT_CONFIG["log_format"])) or DEFAULT_CONFIG["log_format"]
    )

    cfg = RuleConfig(
        tag=str(cfg_raw.get("tag", "opaque")) or "opaque",
        fullscreen_is_media=bool(cfg_raw.get("fullscreen_is_media", True)),
        minimized_is_opaque=bool(cfg_raw.get("minimized_is_opaque", True)),
        urgent_is_opaque=bool(cfg_raw.get("urgent_is_opaque", True)),
        case_insensitive=bool(cfg_raw.get("case_insensitive", True)),
        classes=_list(cfg_raw.get("classes", []), str),
        title_patterns=_list(cfg_raw.get("title_patterns", []), str),
        class_title_rules=_list(cfg_raw.get("class_title_rules", []), dict),
        title_patterns_localized=_map_str_list(cfg_raw.get("title_patterns_localized", {})),
        config_poll_interval_sec=poll_sec,
        socket_timeout_sec=sock_to,
        use_watchdog=bool(cfg_raw.get("use_watchdog", False)) and HAVE_WATCHDOG,
        notify_on_errors=bool(cfg_raw.get("notify_on_errors", False))
        or (os.environ.get("HYPRO_NOTIFY_ON_ERRORS") == "1"),
        log_level=str(cfg_raw.get("log_level", "INFO")) or "INFO",
        safe_close_check=bool(cfg_raw.get("safe_close_check", False)),
        safe_close_check_delay_sec=safe_close_delay,
        max_reconnect_attempts=max_reconnect,
        enable_metrics=bool(cfg_raw.get("enable_metrics", False)),
        metrics_log_every=metrics_every,
        cache_clean_interval_sec=cache_clean_sec,
        heartbeat_interval_sec=heartbeat_sec,
        buffer_log_interval_sec=buffer_log_sec,
        max_buffer_size_bytes=max_buf_bytes,
        socket_buffer_size_bytes=sock_buf_bytes,
        log_file=log_file_val,
        max_log_file_size_bytes=max_log_file_size,
        max_log_rotations=max_log_rotations,
        log_format=log_format_val,
    )

    # logging level from ENV overrides config
    env_level = os.environ.get("HYPRO_LOG_LEVEL")
    level_to_use = env_level or cfg.log_level
    log.setLevel(getattr(logging, level_to_use.upper(), logging.INFO))
    _apply_log_format(cfg.log_format)

    # Activate file logging if configured
    _ensure_file_logging(
        cfg.log_file, cfg.max_log_file_size_bytes, cfg.max_log_rotations, cfg.log_format
    )

    # Validate tag
    if "," in cfg.tag or not cfg.tag.strip():
        log.error("Invalid tag '%s': tag must be non-empty and must not contain commas", cfg.tag)
        sys.exit(1)

    # Setup metrics globals (reset on reload for consistency)
    global _METRICS_ENABLED, _METRICS_LOG_EVERY, _METRICS
    _METRICS_ENABLED = cfg.enable_metrics
    _METRICS_LOG_EVERY = max(1, cfg.metrics_log_every)
    _METRICS = {
        "events_processed": 0,
        "hyprctl_calls": 0,
        "hyprctl_errors": 0,
        "max_cache_size": 0,
        "current_cache_size": 0,
        "bytes_read": 0,
        "event_processing_time_ms": 0,
        "max_event_processing_time_ms": 0,
        "unsupported_events": 0,
        "buffer_size_exceeded": 0,
        "tag_operations": 0,
        "log_file_rotations": 0,
        "config_reload_time_ms": 0,
        "config_reloads": _METRICS.get("config_reloads", 0),  # preserve if global existed
        "notifications_sent": 0,
        "invalid_regex_patterns": 0,
    }
    log.debug(
        "Metrics reset on config reload (enabled=%s, every=%s)",
        _METRICS_ENABLED,
        _METRICS_LOG_EVERY,
    )

    matcher = Matcher(cfg)
    try:
        mtime = os.path.getmtime(path)
    except FileNotFoundError:
        mtime = 0.0

    took_ms = max(1, int((time.monotonic() - start_load) * 1000))
    _metrics_inc("config_reload_time_ms", took_ms)
    _metrics_inc("config_reloads", 1)

    return cfg, matcher, mtime


# --------------------------------------------------------------------------------------
# Version info


def check_hyprland_version() -> None:
    global _ADDRESS_FILTER_SUPPORTED
    data = sh_json(["version"])
    if data is None:
        log.warning("Failed to fetch Hyprland version: hyprctl version -j failed")
        return
    if isinstance(data, dict):
        ver = data.get("version") or data.get("tag") or ""
        log.info("Hyprland version: %s", ver or "unknown")
        features = data.get("features", {})
        if isinstance(features, dict):
            # В некоторых сборках может быть флаг поддержки address_filter
            if "address_filter" in features:
                _ADDRESS_FILTER_SUPPORTED = bool(features.get("address_filter"))
                log.debug("hyprctl clients address: filter supported: %s", _ADDRESS_FILTER_SUPPORTED)
        else:
            log.debug("No 'features' in hyprctl version output (that's fine)")
    else:
        log.warning("Unexpected response from hyprctl version -j: %s", data)


# --------------------------------------------------------------------------------------
# Event handling helper


def handle_event(
    ev: str,
    parts: dict[str, str],
    clients: dict[str, ClientInfo],
    cfg: RuleConfig,
    matcher: Matcher,
) -> None:
    """
    Handle a single Hyprland event. Mutates clients cache, may call hyprctl.
    Intended for reuse in main loop and tests.
    """
    # Сначала постараемся вытащить адрес из payload
    addr = get_address_from_parts(parts)

    # Для ключевых событий используем фолбэк на активное окно,
    # если адрес так и не найден (Hypr v0.50+ иногда не шлёт address).
    if addr is None and ev in ("windowtitle", "activewindow", "focuswindow", "openwindow", "minimized", "urgent"):
        addr = hypr_active_window_address()
        if addr:
            log.debug("Event %s without address: using active window %s", ev, addr)

    # Update cache from event payload (cheap path)
    if addr:
        info = clients.get(addr)
        if info is None:
            fetched = hypr_client_by_address(addr)
            if fetched is not None:
                clients[addr] = info = fetched
                _metrics_update_max_cache(len(clients))
            else:
                log.debug("%s: address %s not found yet, skipping", ev, addr)
                return
        if "class" in parts and parts["class"]:
            info.cls = parts["class"].lower()
        if "title" in parts:
            info.title = parts["title"]
        if ev == "fullscreen":
            state = parts.get("state", parts.get("fullscreen", "0"))
            info.fullscreen = str(state).strip() in ("1", "true", "True")
        if ev == "minimized":
            state = parts.get("state", "0")
            info.minimized = str(state).strip() in ("1", "true", "True")
        if ev == "urgent":
            state = parts.get("state", "0")
            info.urgent = str(state).strip() in ("1", "true", "True")

    # React to relevant events
    if ev in ("openwindow", "windowtitle", "fullscreen"):
        if not addr:
            log.debug("%s event without address, skipping", ev)
            return
        changed = ensure_tag(addr, cfg.tag, matcher.should_be_opaque(clients[addr]), clients[addr].tags)
        log.debug("Processed %s for %s: %s", ev, addr, "tag updated" if changed else "no tag change")

    elif ev in ("changetag", "windowtag", "windowtagdel", "tagadded", "tagremoved"):
        if addr:
            updated = hypr_client_by_address(addr)
            if updated is not None:
                clients[addr].tags = updated.tags
                _metrics_update_max_cache(len(clients))
                changed = ensure_tag(addr, cfg.tag, matcher.should_be_opaque(clients[addr]), clients[addr].tags)
                log.debug("Processed %s for %s: %s", ev, addr, "tag updated" if changed else "no tag change")

    elif ev in ("movewindow", "windowmoved", "windowresized", "float"):
        if addr:
            updated = hypr_client_by_address(addr)
            if updated is not None:
                clients[addr] = updated
                _metrics_update_max_cache(len(clients))
                changed = ensure_tag(addr, cfg.tag, matcher.should_be_opaque(updated), updated.tags)
                log.debug("Processed %s for %s: %s", ev, addr, "tag updated" if changed else "no tag change")

    elif ev in ("focuswindow", "activewindow", "screencopy", "minimized", "urgent"):
        if addr:
            updated = hypr_client_by_address(addr)
            if updated is not None:
                if ev == "minimized":
                    state = parts.get("state", "0")
                    updated.minimized = str(state).strip() in ("1", "true", "True")
                if ev == "urgent":
                    state = parts.get("state", "0")
                    updated.urgent = str(state).strip() in ("1", "true", "True")
                clients[addr] = updated
                _metrics_update_max_cache(len(clients))
                changed = ensure_tag(addr, cfg.tag, matcher.should_be_opaque(updated), updated.tags)
                log.debug("Processed %s for %s: %s", ev, addr, "tag updated" if changed else "no tag change")

    elif ev == "workspace":
        log.debug("Workspace changed, refreshing cache")
        new_clients = hypr_clients()
        for a, inf in new_clients.items():
            ensure_tag(a, cfg.tag, matcher.should_be_opaque(inf), inf.tags)
        clients.clear()
        clients.update(new_clients)
        _metrics_update_max_cache(len(clients))
        log.debug(
            "Cache size after workspace: %s clients%s",
            len(clients),
            " (empty)" if len(clients) == 0 else "",
        )

    elif ev in ("monitoradded", "monitorremoved"):
        log.debug("%s: monitors changed, refreshing cache", ev)
        new_clients = hypr_clients()
        for a, inf in new_clients.items():
            ensure_tag(a, cfg.tag, matcher.should_be_opaque(inf), inf.tags)
        clients.clear()
        clients.update(new_clients)
        _metrics_update_max_cache(len(clients))
        log.debug(
            "Cache size after monitor change: %s clients%s",
            len(clients),
            " (empty)" if len(clients) == 0 else "",
        )

    elif ev in ("closewindow", "destroywindow"):
        if addr and addr in clients:
            if cfg.safe_close_check:
                removed = False
                for _ in range(2):
                    if hypr_client_by_address(addr) is None:
                        clients.pop(addr, None)
                        removed = True
                        _metrics_update_max_cache(len(clients))
                        log.debug("%s for %s: verified and removed from cache", ev, addr)
                        break
                    time.sleep(cfg.safe_close_check_delay_sec)
                if not removed:
                    still_exists = hypr_client_by_address(addr) is not None
                    log.debug(
                        "%s for %s: verification failed, keeping in cache (window %s)",
                        ev,
                        addr,
                        "still exists" if still_exists else "unknown",
                    )
            else:
                clients.pop(addr, None)
                _metrics_update_max_cache(len(clients))

    else:
        # Понижаем шум: v2‑события уже нормализуются, остальное логируем на DEBUG
        log.debug("Unsupported event %s ignored: %s", ev, parts)
        _METRICS["unsupported_events"] = _METRICS.get("unsupported_events", 0) + 1


# --------------------------------------------------------------------------------------
# Main helpers


def _connect_with_backoff(
    sock_path: str, timeout_sec: float, max_attempts: int, notify_on_errors: bool
) -> socket.socket:
    """
    Connect with incremental backoff. If max_attempts > 0 and exceeded, raises OSError.
    """
    attempt = 0
    backoff = 0.5
    while True:
        attempt += 1
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(sock_path)
            if timeout_sec and timeout_sec > 0.0:
                s.settimeout(timeout_sec)
            log.info("Daemon connected to Hyprland socket %s", sock_path)
            return s
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            log.warning(
                "Socket connect failed (attempt %s): %s (type: %s)", attempt, e, type(e).__name__
            )
            if max_attempts == 0 and attempt % 10 == 0:
                log.warning("Still trying to connect to %s (attempt %s)", sock_path, attempt)
            if max_attempts > 0 and attempt >= max_attempts:
                msg = f"Failed to connect to {sock_path} after {attempt} attempts"
                log.error(msg)
                notify_error(msg, notify_on_errors)
                raise
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)


# --------------------------------------------------------------------------------------
# Watchdog support (optional)


class _ConfigWatcher(FileSystemEventHandler):  # type: ignore
    def __init__(self, path: str, on_change):
        super().__init__()
        self.path = os.path.realpath(path)
        self.on_change = on_change

    def on_modified(self, event):
        try:
            if not event.is_directory and os.path.realpath(event.src_path) == self.path:
                self.on_change()
        except Exception as e:
            log.warning("Watchdog event error: %s", e)


# --------------------------------------------------------------------------------------
# Cache maintenance


def clean_stale_clients(clients: dict[str, ClientInfo], buf: bytes) -> int:
    """Remove entries from cache that no longer exist in Hyprland."""
    log.debug("Event buffer size before cache cleanup: %s bytes", len(buf))
    to_remove: list[str] = []
    for addr in list(clients.keys()):
        if hypr_client_by_address(addr) is None:
            to_remove.append(addr)
    for addr in to_remove:
        clients.pop(addr, None)
    if to_remove:
        log.debug("Removed %s stale clients from cache: %s", len(to_remove), ", ".join(to_remove))
    else:
        log.debug("No stale clients found in cache")
    _metrics_update_max_cache(len(clients))
    return len(to_remove)


# --------------------------------------------------------------------------------------
# Buffer safety helper


def enforce_buffer_limit(buf: bytes, limit: int) -> bytes:
    """Ensure buffer does not exceed limit; clears and warns if exceeded."""
    if len(buf) > limit:
        log.warning(
            "Event buffer exceeded %s bytes (was %s bytes), clearing to prevent memory issues",
            limit,
            len(buf),
        )
        _metrics_inc("buffer_size_exceeded")
        return b""
    return buf


# --------------------------------------------------------------------------------------
# Main


def main() -> None:
    """
    Entry point: subscribe to Hyprland events, tag/untag windows based on config.
    """
    # hyprctl availability check
    try:
        subprocess.run(
            ["hyprctl", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        log.error("hyprctl not found or failed to run: %s", e)
        sys.exit(1)

    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if not sig or not xdg:
        log.error("Not in Hyprland session (HYPRLAND_INSTANCE_SIGNATURE/XDG_RUNTIME_DIR missing).")
        sys.exit(1)
    sock_path = os.path.join(xdg, "hypr", sig, ".socket2.sock")

    cfg, matcher, cfg_mtime = load_config(CONFIG_PATH)
    log.info(
        "Config loaded from %s: tag=%s poll=%ss watchdog=%s log=%s "
        "safe_close=%s/%ss max_reconnect=%s metrics=%s/%s "
        "cache_clean=%ss heartbeat=%ss buffer_log=%ss max_buf=%sB "
        "recv_buf=%sB log_file=%s max_log=%sB rotations=%s "
        "min_opaque=%s urgent_opaque=%s",
        CONFIG_PATH,
        cfg.tag,
        cfg.config_poll_interval_sec,
        cfg.use_watchdog,
        logging.getLevelName(log.level),
        cfg.safe_close_check,
        cfg.safe_close_check_delay_sec,
        cfg.max_reconnect_attempts,
        "on" if _METRICS_ENABLED else "off",
        _METRICS_LOG_EVERY,
        cfg.cache_clean_interval_sec,
        cfg.heartbeat_interval_sec,
        cfg.buffer_log_interval_sec,
        cfg.max_buffer_size_bytes,
        cfg.socket_buffer_size_bytes,
        cfg.log_file or "stdout",
        cfg.max_log_file_size_bytes,
        cfg.max_log_rotations,
        cfg.minimized_is_opaque,
        cfg.urgent_is_opaque,
    )

    check_hyprland_version()

    # Initial snapshot and apply
    clients: dict[str, ClientInfo] = hypr_clients()
    for addr, info in clients.items():
        ensure_tag(addr, cfg.tag, matcher.should_be_opaque(info), info.tags)
    _metrics_update_max_cache(len(clients))
    log.debug(
        "Cache size after initial apply: %s clients%s",
        len(clients),
        " (empty)" if len(clients) == 0 else "",
    )

    # Optional watchdog for instant config reloads
    observer: Observer | None = None
    need_reload_flag = False

    def trigger_reload():
        nonlocal need_reload_flag
        need_reload_flag = True

    if cfg.use_watchdog and HAVE_WATCHDOG:
        try:
            observer = Observer()
            watch_dir = os.path.dirname(CONFIG_PATH) or "."
            observer.schedule(
                _ConfigWatcher(CONFIG_PATH, trigger_reload), path=watch_dir, recursive=False
            )
            observer.start()
            log.info("Watchdog started for %s", CONFIG_PATH)
        except Exception as e:
            log.warning("Watchdog start failed, fallback to polling: %s", e)
            observer = None

    buf = b""
    now = time.monotonic()
    next_cfg_check = now + cfg.config_poll_interval_sec
    next_cache_clean = now + cfg.cache_clean_interval_sec
    last_event_received = now
    last_no_event_log = now
    next_buf_log = now + cfg.buffer_log_interval_sec  # периодический лог размера буфера

    def _log_final_metrics():
        if _METRICS_ENABLED:
            avg_ms = 0
            if _METRICS.get("events_processed", 0) > 0:
                avg_ms = _METRICS.get("event_processing_time_ms", 0) // max(
                    1, _METRICS["events_processed"]
                )
            log.info(
                "Final metrics: events=%s hyprctl_calls=%s hyprctl_errors=%s max_cache=%s "
                "current_cache=%s bytes_read=%s avg_event_ms=%s max_event_ms=%s unsupported=%s "
                "buffer_exceeded=%s tag_ops=%s log_rotations=%s config_reloads=%s "
                "config_reload_ms=%s notifications=%s invalid_regex=%s",
                _METRICS["events_processed"],
                _METRICS["hyprctl_calls"],
                _METRICS["hyprctl_errors"],
                _METRICS["max_cache_size"],
                _METRICS["current_cache_size"],
                _METRICS["bytes_read"],
                avg_ms,
                _METRICS["max_event_processing_time_ms"],
                _METRICS["unsupported_events"],
                _METRICS["buffer_size_exceeded"],
                _METRICS["tag_operations"],
                _METRICS["log_file_rotations"],
                _METRICS["config_reloads"],
                _METRICS["config_reload_time_ms"],
                _METRICS["notifications_sent"],
                _METRICS["invalid_regex_patterns"],
            )

    while True:
        try:
            s = _connect_with_backoff(
                sock_path, cfg.socket_timeout_sec, cfg.max_reconnect_attempts, cfg.notify_on_errors
            )
        except OSError:
            # Give up for this run; systemd (if used) may restart us.
            _log_final_metrics()
            break

        try:
            with s:
                while True:
                    now = time.monotonic()

                    # Heartbeat: periodic "no events" log
                    if (
                        now - last_event_received >= cfg.heartbeat_interval_sec
                        and now - last_no_event_log >= cfg.heartbeat_interval_sec
                    ):
                        log.debug(
                            "No events received in last %s seconds", cfg.heartbeat_interval_sec
                        )
                        last_no_event_log = now

                    # Periodic buffer size log (independent interval)
                    if now >= next_buf_log:
                        log.debug(
                            "Current event buffer size: %s bytes (exceeded %s times)",
                            len(buf),
                            _METRICS.get("buffer_size_exceeded", 0),
                        )
                        next_buf_log = now + cfg.buffer_log_interval_sec

                    # Periodic cache cleanup
                    if now >= next_cache_clean:
                        clean_stale_clients(clients, buf)
                        next_cache_clean = now + cfg.cache_clean_interval_sec

                    # Config reload (watchdog or polling)
                    if need_reload_flag or (not cfg.use_watchdog and now >= next_cfg_check):
                        need_reload_flag = False
                        try:
                            mtime = os.path.getmtime(CONFIG_PATH)
                        except FileNotFoundError:
                            mtime = 0.0
                        if mtime != cfg_mtime or cfg.use_watchdog:
                            log.debug("Config changed (mtime %s -> %s)", cfg_mtime, mtime)
                            old_cfg = cfg
                            cfg, matcher, cfg_mtime = load_config(CONFIG_PATH)
                            # Log changed fields
                            try:
                                changed = []
                                for f in fields(RuleConfig):
                                    old_val = getattr(old_cfg, f.name)
                                    new_val = getattr(cfg, f.name)
                                    if old_val != new_val:
                                        changed.append(f"{f.name}: {old_val} -> {new_val}")
                                if changed:
                                    log.debug("Config changes: %s", ", ".join(changed))
                            except Exception as e:
                                log.debug("Failed to diff config: %s", e)
                            log.info(
                                "Config reloaded: tag=%s poll=%ss watchdog=%s log=%s "
                                "safe_close=%s/%ss max_reconnect=%s metrics=%s/%s "
                                "cache_clean=%ss heartbeat=%ss buffer_log=%ss max_buf=%sB "
                                "recv_buf=%sB log_file=%s max_log=%sB rotations=%s "
                                "min_opaque=%s urgent_opaque=%s",
                                cfg.tag,
                                cfg.config_poll_interval_sec,
                                cfg.use_watchdog,
                                logging.getLevelName(log.level),
                                cfg.safe_close_check,
                                cfg.safe_close_check_delay_sec,
                                cfg.max_reconnect_attempts,
                                "on" if _METRICS_ENABLED else "off",
                                _METRICS_LOG_EVERY,
                                cfg.cache_clean_interval_sec,
                                cfg.heartbeat_interval_sec,
                                cfg.buffer_log_interval_sec,
                                cfg.max_buffer_size_bytes,
                                cfg.socket_buffer_size_bytes,
                                cfg.log_file or "stdout",
                                cfg.max_log_file_size_bytes,
                                cfg.max_log_rotations,
                                cfg.minimized_is_opaque,
                                cfg.urgent_is_opaque,
                            )
                            # Re-evaluate all (refresh cache completely)
                            clients = hypr_clients()
                            clean_stale_clients(clients, buf)
                            for addr, info in clients.items():
                                ensure_tag(addr, cfg.tag, matcher.should_be_opaque(info), info.tags)
                            # Clear buffer without extra logging (убран избыточный лог)
                            buf = b""
                            log.debug("Cleared event buffer due to config reload")
                            _metrics_update_max_cache(len(clients))
                            log.debug(
                                "Cache size after reload: %s clients%s",
                                len(clients),
                                " (empty)" if len(clients) == 0 else "",
                            )
                        next_cfg_check = now + cfg.config_poll_interval_sec

                    # Read events
                    try:
                        data = s.recv(cfg.socket_buffer_size_bytes)
                    except socket.timeout:
                        log.debug("Socket read timeout, no data")
                        data = b""
                    if not data:
                        continue

                    _metrics_inc("bytes_read", len(data))
                    _metrics_maybe_log()

                    last_event_received = time.monotonic()
                    buf += data

                    # Buffer size protection
                    buf = enforce_buffer_limit(buf, cfg.max_buffer_size_bytes)

                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        ev, parts = parse_event(line)
                        if not ev:
                            continue

                        # Нормализация названий событий (v2 -> base)
                        ev = normalize_event_name(ev)

                        # Приглушаем шум от смены фокуса монитора (не влияет на теги)
                        if ev in ("focusedmon",):
                            continue

                        _metrics_inc("events_processed")
                        _metrics_maybe_log()
                        last_event_received = time.monotonic()

                        start = time.monotonic()
                        handle_event(ev, parts, clients, cfg, matcher)
                        took_ms = max(1, int((time.monotonic() - start) * 1000))
                        _metrics_inc("event_processing_time_ms", took_ms)
                        if took_ms > _METRICS.get("max_event_processing_time_ms", 0):
                            _METRICS["max_event_processing_time_ms"] = took_ms
                        if took_ms > 100:
                            log.warning("Slow event %s took %s ms", ev, took_ms)
                        _metrics_update_max_cache(len(clients))

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
            _log_final_metrics()
            break
        except Exception as e:
            log.error("Unhandled error in loop: %s (reconnecting in 1s)", e)
            notify_error(f"hypr-opaque-media error: {e}", cfg.notify_on_errors)
            time.sleep(1.0)
            continue

    # Cleanup
    if observer:
        try:
            observer.stop()
            observer.join(timeout=2)
        except Exception as e:
            log.warning("Failed to stop watchdog observer: %s", e)


if __name__ == "__main__":
    main()