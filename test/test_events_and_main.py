import contextlib
import importlib.util
import json
import logging
import os
import sys
import time as _time
import unittest
from itertools import chain, repeat
from unittest.mock import MagicMock, patch

import pytest

# Enforce Python version for tests (aligns with runtime requirement)

"""
Unit tests for hypr-opaque-media.py.
Covers:
- parse_event: Parsing Hyprland socket2 events (workspace, monitoradded/removed, activewindow).
- Matcher.should_be_opaque: Window matching logic (class, title, fullscreen, minimized/urgent).
- ensure_tag: Tag toggling and state management (+ tag_operations metric).
- hypr_client_by_address: Single-client fetch with address filter and fallback (via sh_json mock).
- clean_stale_clients: Cache stale removal (with removed addresses list log + buffer size log).
- load_config: Error handling for missing/invalid JSON and clamps + config_reload_time_ms increment.
- check_hyprland_version: Version and features logging.
- main (integration-lite): buffer size period log; slow event warning; early hyprctl check.
- safe_close_check handling via handle_event (with configurable delay).
- destroywindow handling via handle_event.
- windowtagdel/tagadded handling: tags update + ensure_tag invocation.
- windowmoved/windowresized/float handling via handle_event.
- screencopy/minimized/urgent handling via handle_event (incl. states).
- enforce_buffer_limit: clears buffer and warns when exceeded (with actual size) and increments.
- unsupported event warning emitted with parts and metric increment when metrics enabled.
- periodic cache cleanup trigger via cache_clean_interval_sec (time.monotonic mocked).
- file logging setup and error handling in _ensure_file_logging, including rotation success.
- hyprctl_errors metric increments on failures.
- invalid log_format fallback.
- invalid_regex_patterns metric increments on bad regex.
- current_cache_size metric updates.
- connect_with_backoff logs exception type.
- notify_error dynamic check + notifications_sent metric.
"""

# Prefer local repository script if present;
# allow override via HYPRO_MODULE_PATH; else fallback to ~/.local/bin
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LOCAL_SCRIPT = os.path.join(_REPO_ROOT, "hypr-opaque-media.py")
_DEFAULT_SCRIPT = (
    _LOCAL_SCRIPT if os.path.exists(_LOCAL_SCRIPT) else "~/.local/bin/hypr-opaque-media.py"
)

MODULE_PATH = os.path.expanduser(os.environ.get("HYPRO_MODULE_PATH", _DEFAULT_SCRIPT))
spec = importlib.util.spec_from_file_location("hypr_opaque_media_runtime", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["hypr_opaque_media_runtime"] = mod  # register to allow relative imports if any
assert spec and spec.loader
spec.loader.exec_module(mod)  # type: ignore


class TestMatcherAndHelpers(unittest.TestCase):
    def setUp(self):
        """Reset global metrics state before each test for proper isolation."""
        mod._METRICS_ENABLED = False
        # Reset all metrics to their initial values
        mod._METRICS.update(
            {
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
        )
        # Clean up logger handlers to avoid interference between tests
        logger = logging.getLogger("hypr-opaque")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def test_parse_event(self):
        ev, parts = mod.parse_event(b"openwindow>>address:0x1,class:mpv,title:Video")
        self.assertEqual(ev, "openwindow")
        self.assertEqual(parts, {"address": "0x1", "class": "mpv", "title": "Video"})

        ev, parts = mod.parse_event(b"windowtitle>>address:0x2,title:YouTube - Firefox")
        self.assertEqual(ev, "windowtitle")
        self.assertEqual(parts["address"], "0x2")
        self.assertIn("title", parts)

        ev, parts = mod.parse_event(b"workspace>>name:1")
        self.assertEqual(ev, "workspace")
        self.assertIn("name", parts)

        for ev_name in (b"monitoradded", b"monitorremoved"):
            evv, parts = mod.parse_event(ev_name + b">>name:monitor-1")
            self.assertIn(evv, ["monitoradded", "monitorremoved"])
            self.assertIn("name", parts)

        ev, parts = mod.parse_event(b"activewindow>>address:0x3,class:mpv,title:Video")
        self.assertEqual(ev, "activewindow")
        self.assertEqual(parts["address"], "0x3")

        ev, parts = mod.parse_event(b"windowtagdel>>address:0x4")
        self.assertEqual(ev, "windowtagdel")
        self.assertEqual(parts["address"], "0x4")

        ev, parts = mod.parse_event(b"corrupt line without delimiter")
        self.assertIsNone(ev)
        self.assertEqual(parts, {})

    def test_matcher_and_invalid_regex_metric(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update({"invalid_regex_patterns": 0})
        cfg = mod.RuleConfig(
            classes=["mpv"],
            title_patterns=["(", "YouTube"],  # invalid + valid
            class_title_rules=[{"class_regex": "(", "title_regex": "("}],  # both invalid
            title_patterns_localized={"en": ["Vimeo"]},
        )
        m = mod.Matcher(cfg)
        # 2 invalid regex increments (1 title + 1 class/title rule)
        self.assertGreaterEqual(mod._METRICS["invalid_regex_patterns"], 2)
        self.assertTrue(m.should_be_opaque(mod.ClientInfo(address="0x1", cls="mpv", title="x")))

    def test_ensure_tag_and_metric(self):
        calls = []

        def fake_toggle(addr, tag):
            calls.append((addr, tag))

        original = mod.toggle_tag
        try:
            mod.toggle_tag = fake_toggle  # type: ignore
            mod._METRICS_ENABLED = True
            mod._METRICS.update({"tag_operations": 0})
            tags = set()
            changed = mod.ensure_tag("0x1", "opaque", True, tags)
            self.assertTrue(changed)
            self.assertIn("opaque", tags)
            self.assertEqual(calls[-1], ("0x1", "opaque"))
            self.assertEqual(mod._METRICS["tag_operations"], 1)
        finally:
            mod.toggle_tag = original

    def test_hypr_client_by_address(self):
        with patch("hypr_opaque_media_runtime.sh_json") as mock_sh_json:
            mock_sh_json.return_value = {
                "address": "0x1",
                "class": "mpv",
                "title": "Video",
                "fullscreen": False,
                "minimized": False,
                "urgent": False,
                "tags": [],
            }
            info = mod.hypr_client_by_address("0x1")
            self.assertIsNotNone(info)
            assert info
            self.assertEqual(info.address, "0x1")
            self.assertEqual(info.cls, "mpv")
            self.assertEqual(info.title, "Video")

        with patch("hypr_opaque_media_runtime.sh_json") as mock_sh_json:
            mock_sh_json.side_effect = [
                [
                    {
                        "address": "0x2",
                        "class": "vlc",
                        "title": "Movie",
                        "fullscreen": True,
                        "minimized": False,
                        "urgent": False,
                        "tags": ["opaque"],
                    }
                ]
            ]
            info = mod.hypr_client_by_address("0x2")
            self.assertIsNotNone(info)
            assert info
            self.assertEqual(info.cls, "vlc")
            self.assertTrue(info.fullscreen)

        with patch("hypr_opaque_media_runtime.sh_json") as mock_sh_json:
            mock_sh_json.side_effect = [
                None,
                [
                    {
                        "address": "0x3",
                        "class": "imv",
                        "title": "Image",
                        "fullscreen": False,
                        "minimized": True,
                        "urgent": True,
                        "tags": [],
                    }
                ],
            ]
            info = mod.hypr_client_by_address("0x3")
            self.assertIsNotNone(info)
            assert info
            self.assertEqual(info.cls, "imv")
            self.assertTrue(info.minimized)
            self.assertTrue(info.urgent)

    def test_clean_stale_clients(self):
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.log") as mock_log,
        ):
            clients = {
                "0x1": mod.ClientInfo(address="0x1", cls="mpv"),
                "0x2": mod.ClientInfo(address="0x2", cls="vlc"),
            }
            mock_hcli.side_effect = [None, mod.ClientInfo(address="0x2", cls="vlc")]
            removed = mod.clean_stale_clients(clients, b"abcd")
            self.assertEqual(removed, 1)
            self.assertEqual(list(clients.keys()), ["0x2"])
            # Check that log.debug was called with the expected buffer size message
            self.assertTrue(mock_log.debug.called)
            # Find the call about buffer size
            buffer_size_logged = False
            for call in mock_log.debug.call_args_list:
                if len(call[0]) >= 2 and "Event buffer size before cache cleanup:" in call[0][0]:
                    self.assertEqual(call[0][1], 4)  # buffer size should be 4 bytes
                    buffer_size_logged = True
                    break
            self.assertTrue(buffer_size_logged)

    def test_load_config_errors_and_clamps_and_metrics(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update({"config_reload_time_ms": 0, "config_reloads": 0})
        with (
            patch("builtins.open", side_effect=FileNotFoundError),
            patch.dict(mod.DEFAULT_CONFIG, {"enable_metrics": True}),
        ):
            # Mock the config to have metrics enabled so _metrics_inc() will work
            cfg, matcher, mtime = mod.load_config("/nonexistent.json")
            self.assertEqual(cfg.tag, "opaque")
            self.assertEqual(mtime, 0.0)
            self.assertGreater(mod._METRICS["config_reload_time_ms"], 0)
            self.assertEqual(mod._METRICS["config_reloads"], 1)
        with patch("json.load", side_effect=ValueError):

            class _Dummy:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return "{}"

            with patch("builtins.open", return_value=_Dummy()):
                cfg, matcher, mtime = mod.load_config("/dummy.json")
                self.assertEqual(cfg.tag, "opaque")
        bad_cfg = json.dumps(
            {
                "cache_clean_interval_sec": -1.0,
                "heartbeat_interval_sec": -5.0,
                "socket_buffer_size_bytes": 512,
                "max_log_file_size_bytes": 512,
                "buffer_log_interval_sec": 0.5,
                "safe_close_check_delay_sec": 0.001,
            }
        )

        class _Dummy2:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return bad_cfg

        with patch("builtins.open", return_value=_Dummy2()):
            cfg, matcher, mtime = mod.load_config("/dummy.json")
            self.assertEqual(cfg.cache_clean_interval_sec, 300.0)
            self.assertEqual(cfg.heartbeat_interval_sec, 600.0)
            self.assertEqual(cfg.socket_buffer_size_bytes, 4096)
            self.assertEqual(cfg.max_log_file_size_bytes, 1048576)
            self.assertEqual(cfg.buffer_log_interval_sec, 600.0)
            self.assertEqual(cfg.safe_close_check_delay_sec, 0.1)

    def test_check_hyprland_version(self):
        with patch("hypr_opaque_media_runtime.sh_json") as mock_sh_json:
            mock_sh_json.return_value = {"version": "0.42.0", "features": {"address_filter": True}}
            mod.check_hyprland_version()
            mock_sh_json.assert_called_with(["version"])
        with patch("hypr_opaque_media_runtime.sh_json", return_value=None):
            mod.check_hyprland_version()

    @pytest.mark.integration
    @pytest.mark.linux
    @pytest.mark.requires_wayland
    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")
    @pytest.mark.skipif(os.environ.get("XDG_SESSION_TYPE") != "wayland", reason="Requires Wayland")
    @pytest.mark.skipif(
        not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"), reason="Requires Hyprland"
    )
    def test_main_buffer_log_and_slow_event_warning(self):
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "test"
        os.environ["XDG_RUNTIME_DIR"] = "/tmp"

        mod._METRICS_ENABLED = True

        cfg = mod.RuleConfig(
            enable_metrics=True,
            config_poll_interval_sec=999,
            cache_clean_interval_sec=999,
            heartbeat_interval_sec=999,
            buffer_log_interval_sec=1.0,
        )
        matcher = mod.Matcher(cfg)

        # Patch handle_event to sleep >100ms to trigger slow event warning
        def slow_handle(ev, parts, clients, cfg, matcher):
            _time.sleep(0.12)

        # Prepare a controllable socket mock
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = False
        mock_sock.recv.side_effect = [b"openwindow>>address:0x1\n", KeyboardInterrupt()]

        # Make the first connect succeed, the second raise OSError to break the outer loop
        connect_calls = {"n": 0}

        def fake_connect(sock_path, timeout_sec, max_attempts, notify_on_errors):
            connect_calls["n"] += 1
            if connect_calls["n"] == 1:
                return mock_sock
            raise OSError("stop outer loop")

        with (
            patch("hypr_opaque_media_runtime.load_config", return_value=(cfg, matcher, 0.0)),
            patch("hypr_opaque_media_runtime._connect_with_backoff", side_effect=fake_connect),
            patch("hypr_opaque_media_runtime.sh_json") as mock_sh_json,
            patch("hypr_opaque_media_runtime.handle_event", side_effect=slow_handle),
            patch("hypr_opaque_media_runtime.time.monotonic") as mock_time,
            patch("hypr_opaque_media_runtime.time.sleep", return_value=None),
            patch("hypr_opaque_media_runtime.log") as mock_log,
            patch("hypr_opaque_media_runtime.subprocess.run") as mock_run,
        ):

            class P:
                def __init__(self):
                    self.returncode = 0
                    self.stderr = ""
                    self.stdout = ""

            mock_run.return_value = P()

            mock_sh_json.side_effect = [
                {"version": "0.42.0", "features": {"address_filter": True}},
                [
                    {
                        "address": "0x1",
                        "class": "mpv",
                        "title": "Video",
                        "fullscreen": False,
                        "minimized": False,
                        "urgent": False,
                        "tags": [],
                    }
                ],
            ]

            # Ensure: initial now=0.0, then 2.0 to trigger buffer log,
            # then start=2.0, end=2.2 -> 200ms
            mock_time.side_effect = chain([0.0, 2.0, 2.0, 2.0, 2.0, 2.2], repeat(2.2))

            with contextlib.suppress(SystemExit, KeyboardInterrupt):
                mod.main()

            self.assertTrue(
                any("Current event buffer size:" in str(c) for c in mock_log.debug.mock_calls)
            )
            self.assertTrue(any("Slow event" in str(c) for c in mock_log.warning.mock_calls))

    def test_safe_close_check_with_delay(self):
        cfg = mod.RuleConfig(safe_close_check=True, safe_close_check_delay_sec=0.05)
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv")}
        m = mod.Matcher(cfg)
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.time.sleep") as mock_sleep,
        ):
            mock_hcli.side_effect = [mod.ClientInfo(address="0x1", cls="mpv"), None]
            ev, parts = mod.parse_event(b"closewindow>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            mock_sleep.assert_called_with(0.05)
            self.assertEqual(len(clients), 0)

    def test_destroywindow_event(self):
        cfg = mod.RuleConfig(safe_close_check=False)
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv")}
        m = mod.Matcher(cfg)
        with patch("hypr_opaque_media_runtime.hypr_client_by_address", return_value=None):
            ev, parts = mod.parse_event(b"destroywindow>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertEqual(len(clients), 0)

    def test_windowtagdel_event(self):
        cfg = mod.RuleConfig()
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})}
        m = mod.Matcher(cfg)
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            mock_hcli.return_value = mod.ClientInfo(address="0x1", cls="mpv", tags=set())
            ev, parts = mod.parse_event(b"windowtagdel>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertEqual(clients["0x1"].tags, set())
            self.assertTrue(mock_ensure.called)
            args, kwargs = mock_ensure.call_args
            self.assertEqual(args[0], "0x1")

    def test_tagadded_event(self):
        cfg = mod.RuleConfig()
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags=set())}
        m = mod.Matcher(cfg)
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            mock_hcli.return_value = mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})
            ev, parts = mod.parse_event(b"tagadded>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertEqual(clients["0x1"].tags, {"opaque"})
            self.assertTrue(mock_ensure.called)
            args, kwargs = mock_ensure.call_args
            self.assertEqual(args[0], "0x1")

    def test_windowmoved_event(self):
        cfg = mod.RuleConfig()
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})}
        m = mod.Matcher(cfg)
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            mock_hcli.return_value = mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})
            ev, parts = mod.parse_event(b"windowmoved>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertTrue(mock_ensure.called)
            args, kwargs = mock_ensure.call_args
            self.assertEqual(args[0], "0x1")

    def test_windowresized_event(self):
        cfg = mod.RuleConfig()
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})}
        m = mod.Matcher(cfg)
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            mock_hcli.return_value = mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})
            ev, parts = mod.parse_event(b"windowresized>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertTrue(mock_ensure.called)
            args, kwargs = mock_ensure.call_args
            self.assertEqual(args[0], "0x1")

    def test_float_event(self):
        cfg = mod.RuleConfig()
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags=set())}
        m = mod.Matcher(cfg)
        with (
            patch(
                "hypr_opaque_media_runtime.hypr_client_by_address",
                return_value=mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"}),
            ),
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            ev, parts = mod.parse_event(b"float>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertTrue(mock_ensure.called)
            args, kwargs = mock_ensure.call_args
            self.assertEqual(args[0], "0x1")

    def test_screencopy_event(self):
        cfg = mod.RuleConfig()
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags=set())}
        m = mod.Matcher(cfg)
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            mock_hcli.return_value = mod.ClientInfo(address="0x1", cls="mpv", tags={"opaque"})
            ev, parts = mod.parse_event(b"screencopy>>address:0x1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertEqual(clients["0x1"].tags, {"opaque"})
            self.assertTrue(mock_ensure.called)
            args, kwargs = mock_ensure.call_args
            self.assertEqual(args[0], "0x1")

    def test_minimized_and_urgent_events_and_state(self):
        cfg = mod.RuleConfig(minimized_is_opaque=True, urgent_is_opaque=True)
        clients = {"0x1": mod.ClientInfo(address="0x1", cls="mpv", tags=set())}
        m = mod.Matcher(cfg)
        updated = mod.ClientInfo(
            address="0x1", cls="mpv", minimized=False, urgent=False, tags=set()
        )
        with (
            patch("hypr_opaque_media_runtime.hypr_client_by_address", return_value=updated),
            patch("hypr_opaque_media_runtime.ensure_tag") as mock_ensure,
        ):
            ev, parts = mod.parse_event(b"minimized>>address:0x1,state:1")
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertTrue(clients["0x1"].minimized)
            ev2, parts2 = mod.parse_event(b"urgent>>address:0x1,state:1")
            mod.handle_event(ev2, parts2, clients, cfg, m)
            self.assertTrue(clients["0x1"].urgent)
            self.assertTrue(mock_ensure.called)

    def test_enforce_buffer_limit_and_metric(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update({"buffer_size_exceeded": 0})
        with patch("hypr_opaque_media_runtime.log") as mock_log:
            buf = b"a" * 101
            limited = mod.enforce_buffer_limit(buf, 100)
            self.assertEqual(limited, b"")
            # Check that log.warning was called with the expected arguments
            self.assertTrue(mock_log.warning.called)
            # Check the warning call arguments - format has "was %s bytes" and 101 as second arg
            call_args = mock_log.warning.call_args
            self.assertIn("was %s bytes", call_args[0][0])  # format string
            self.assertEqual(call_args[0][2], 101)  # third argument should be 101 (buffer size)
            self.assertEqual(mod._METRICS["buffer_size_exceeded"], 1)

    def test_unsupported_event_warning_and_metric(self):
        cfg = mod.RuleConfig()
        m = mod.Matcher(cfg)
        clients = {}
        # Надежный способ: вешаем временный handler и ловим запись WARNING
        records = []

        class _ListHandler(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = mod.log
        lh = _ListHandler()
        old_level = logger.level
        try:
            logger.addHandler(lh)
            logger.setLevel(logging.DEBUG)
            mod._METRICS_ENABLED = True
            mod._METRICS.update({"unsupported_events": 0})
            ev, parts = "unknown_event", {"foo": "bar"}
            mod.handle_event(ev, parts, clients, cfg, m)
            self.assertTrue(any("Unsupported event" in r.getMessage() for r in records))
            self.assertEqual(mod._METRICS["unsupported_events"], 1)
        finally:
            logger.removeHandler(lh)
            logger.setLevel(old_level)

    @pytest.mark.integration
    @pytest.mark.linux
    @pytest.mark.requires_wayland
    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")
    @pytest.mark.skipif(os.environ.get("XDG_SESSION_TYPE") != "wayland", reason="Requires Wayland")
    @pytest.mark.skipif(
        not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"), reason="Requires Hyprland"
    )
    def test_cache_cleanup_in_main(self):
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "test"
        os.environ["XDG_RUNTIME_DIR"] = "/tmp"

        cfg = mod.RuleConfig(
            enable_metrics=False,
            config_poll_interval_sec=999,
            cache_clean_interval_sec=300.0,
            heartbeat_interval_sec=999,
            buffer_log_interval_sec=999,
        )
        matcher = mod.Matcher(cfg)

        with (
            patch("hypr_opaque_media_runtime.load_config", return_value=(cfg, matcher, 0.0)),
            patch("socket.socket") as mock_socket,
            patch("hypr_opaque_media_runtime.sh_json") as mock_sh_json,
            patch("hypr_opaque_media_runtime.clean_stale_clients") as mock_clean,
            patch("hypr_opaque_media_runtime.time.monotonic") as mock_time,
            patch("hypr_opaque_media_runtime.log"),
            patch("hypr_opaque_media_runtime.subprocess.run") as mock_run,
        ):

            class P:
                def __init__(self):
                    self.returncode = 0
                    self.stderr = ""
                    self.stdout = ""

            mock_run.return_value = P()

            mock_sh_json.side_effect = [
                {"version": "0.42.0", "features": {"address_filter": True}},
                [
                    {
                        "address": "0x1",
                        "class": "mpv",
                        "title": "Video",
                        "fullscreen": False,
                        "minimized": False,
                        "urgent": False,
                        "tags": [],
                    }
                ],
            ]
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock
            mock_sock.__enter__.return_value = mock_sock
            mock_sock.__exit__.return_value = False
            mock_sock.recv.side_effect = [b"", KeyboardInterrupt()]
            mock_time.side_effect = [0.0, 0.0, 301.0]

            with contextlib.suppress(KeyboardInterrupt, SystemExit):
                mod.main()

            self.assertTrue(mock_clean.called)

    def test_file_logging_setup_rotation_success_and_error(self):
        with (
            patch("logging.FileHandler") as mock_fh,
            patch("logging.getLogger") as mock_get_logger,
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=2_000_000),
            patch("os.listdir", return_value=["hypr-opaque-test.log.1.bak", "other.txt"]),
            patch("os.path.getmtime", side_effect=[1.0, 2.0]),
            patch("os.remove") as mock_remove,
            patch("os.rename") as mock_rename,
            patch("os.access", return_value=True),
        ):
            # Mock the logger to avoid handler complications
            mock_logger = MagicMock()
            mock_logger.handlers = []  # No existing handlers
            mock_get_logger.return_value = mock_logger

            # Test successful setup
            mod._ensure_file_logging(
                "/tmp/hypr-opaque-test.log", 1024, 1, "[%(levelname)s] %(message)s"
            )
            self.assertTrue(mock_rename.called)
            self.assertTrue(mock_remove.called)
            self.assertTrue(mock_fh.called)
            self.assertTrue(mock_logger.addHandler.called)

        # Test error case
        with (
            patch("logging.FileHandler", side_effect=OSError("Permission denied")),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=2_000_000),
            patch("os.rename", side_effect=OSError("Permission denied")),
            patch("os.access", return_value=True),
        ):
            # This should not raise an exception, just log warnings
            mod._ensure_file_logging(
                "/tmp/hypr-opaque-test.log", 1024, 2, "[%(levelname)s] %(message)s"
            )

    def test_file_logging_no_write_access(self):
        with (
            patch("os.access", return_value=False),
            patch("hypr_opaque_media_runtime.log") as mock_log,
        ):
            mod._ensure_file_logging(
                "/tmp/readonly/hypr-opaque-test.log", 1024, 5, "[%(levelname)s] %(message)s"
            )
            # Check that log.warning was called with the expected no write access message
            self.assertTrue(mock_log.warning.called)
            # Find the call about directory not writable
            no_write_logged = False
            for call in mock_log.warning.call_args_list:
                if len(call[0]) >= 2 and "is not writable" in call[0][0]:
                    self.assertEqual(call[0][1], "/tmp/readonly")  # directory path
                    no_write_logged = True
                    break
            self.assertTrue(no_write_logged)

    def test_custom_log_format(self):
        with (
            patch("logging.FileHandler") as mock_fh,
            patch("hypr_opaque_media_runtime.log"),
            patch("os.access", return_value=True),
        ):
            fmt = "%(asctime)s [%(levelname)s] %(message)s"
            mod._ensure_file_logging("/tmp/hypr-opaque-test.log", 1024 * 1024, 5, fmt)
            self.assertTrue(mock_fh.return_value.setFormatter.called)
            formatter_arg = mock_fh.return_value.setFormatter.call_args[0][0]
            self.assertIsInstance(formatter_arg, logging.Formatter)
            self.assertIn("%(asctime)s", formatter_arg._fmt)

    def test_invalid_log_format_fallback(self):
        with patch("hypr_opaque_media_runtime.log") as mock_log:
            # Use a format that causes an exception during Formatter creation
            mod._apply_log_format("%(levelname")  # Incomplete format
            # Check for "Invalid log_format" message in warning logs
            invalid_format_logged = False
            for call in mock_log.warning.call_args_list:
                if len(call[0]) >= 1 and "Invalid log_format" in call[0][0]:
                    invalid_format_logged = True
                    break
            self.assertTrue(invalid_format_logged)
            # The function should complete without raising an exception

    def test_hyprctl_errors_metric(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update({"hyprctl_errors": 0})
        with patch("hypr_opaque_media_runtime.subprocess.run", side_effect=FileNotFoundError):
            result = mod.sh_json(["clients"])
            self.assertIsNone(result)
            self.assertEqual(mod._METRICS["hyprctl_errors"], 1)

        class P:
            def __init__(self):
                self.returncode = 1
                self.stderr = "err"
                self.stdout = ""

        with patch("hypr_opaque_media_runtime.subprocess.run", return_value=P()):
            result = mod.sh_json(["clients"])
            self.assertIsNone(result)
            self.assertEqual(mod._METRICS["hyprctl_errors"], 2)

        class P2:
            def __init__(self):
                self.returncode = 0
                self.stderr = ""
                self.stdout = "{bad"

        with patch("hypr_opaque_media_runtime.subprocess.run", return_value=P2()):
            result = mod.sh_json(["clients"])
            self.assertIsNone(result)
            self.assertEqual(mod._METRICS["hyprctl_errors"], 3)

    def test_connect_with_backoff_error_logging(self):
        with (
            patch("socket.socket") as mock_socket,
            patch("hypr_opaque_media_runtime.log") as mock_log,
        ):
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock
            mock_sock.connect.side_effect = OSError("Permission denied")
            with self.assertRaises(OSError):
                mod._connect_with_backoff("/tmp/test.sock", 1.0, 1, False)
            # Check that log.warning was called with the expected connect failure message
            self.assertTrue(mock_log.warning.called)
            # Find the call about socket connect failure
            connect_failure_logged = False
            for call in mock_log.warning.call_args_list:
                if len(call[0]) >= 4 and "Socket connect failed" in call[0][0]:
                    # Check that the exception type is mentioned as OSError
                    self.assertEqual(call[0][3], "OSError")  # type(e).__name__ should be "OSError"
                    connect_failure_logged = True
                    break
            self.assertTrue(connect_failure_logged)

    def test_notifications_sent_metric_and_dynamic_check(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update({"notifications_sent": 0})
        # when notify-send available
        with (
            patch("hypr_opaque_media_runtime._has_notify_send", return_value=True),
            patch("hypr_opaque_media_runtime.subprocess.run") as mock_run,
        ):

            class P:
                def __init__(self):
                    self.returncode = 0
                    self.stderr = ""
                    self.stdout = ""

            mock_run.return_value = P()
            mod.notify_error("Test error", True)
            self.assertEqual(mod._METRICS["notifications_sent"], 1)
        # when notify-send unavailable
        with patch("hypr_opaque_media_runtime._has_notify_send", return_value=False):
            before = mod._METRICS["notifications_sent"]
            mod.notify_error("Test error", True)
            self.assertEqual(mod._METRICS["notifications_sent"], before)

    def test_current_cache_size_metric_helper(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update({"current_cache_size": 0, "max_cache_size": 0})
        mod._metrics_update_max_cache(3)
        self.assertEqual(mod._METRICS["current_cache_size"], 3)
        self.assertEqual(mod._METRICS["max_cache_size"], 3)


if __name__ == "__main__":
    unittest.main()
