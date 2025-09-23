import importlib.util
import logging
import os
import sys
import unittest
from itertools import chain, repeat
from unittest.mock import MagicMock, patch

# Загружаем локальный скрипт из репозитория и регистрируем модуль
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LOCAL_SCRIPT = os.path.join(_REPO_ROOT, "hypr-opaque-media.py")
MODULE_PATH = os.path.expanduser(os.environ.get("HYPRO_MODULE_PATH", _LOCAL_SCRIPT))

spec = importlib.util.spec_from_file_location("hypr_opaque_media_runtime_more", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["hypr_opaque_media_runtime_more"] = mod
spec.loader.exec_module(mod)  # type: ignore


class TestCoreMore(unittest.TestCase):
    def setUp(self):
        mod._METRICS_ENABLED = True
        mod._METRICS.update(
            {
                "unsupported_events": 0,
                "buffer_size_exceeded": 0,
                "tag_operations": 0,
                "notifications_sent": 0,
                "hyprctl_errors": 0,
            }
        )
        lg = logging.getLogger("hypr-opaque")
        if not lg.handlers:
            lg.addHandler(logging.StreamHandler())

    def test_ensure_tag_noop_and_remove(self):
        # no-op: тег уже есть и want=True
        tags = {"opaque"}
        changed = mod.ensure_tag("0x1", "opaque", True, tags)
        self.assertFalse(changed)
        self.assertEqual(tags, {"opaque"})
        # remove: тега нет и want=False -> no-op
        tags = set()
        changed = mod.ensure_tag("0x1", "opaque", False, tags)
        self.assertFalse(changed)
        self.assertEqual(tags, set())
        # remove: тег есть и want=False -> вызов toggle_tag и инкремент метрики
        calls = []

        def fake_toggle(addr, tag):
            calls.append((addr, tag))

        try:
            original = mod.toggle_tag
            mod.toggle_tag = fake_toggle  # type: ignore
            tags = {"opaque"}
            changed = mod.ensure_tag("0x2", "opaque", False, tags)
            self.assertTrue(changed)
            self.assertEqual(tags, set())
            self.assertIn(("0x2", "opaque"), calls)
            self.assertGreaterEqual(mod._METRICS["tag_operations"], 1)
        finally:
            mod.toggle_tag = original  # type: ignore

    def test_matcher_case_sensitive_and_rules_and_localized(self):
        # case_insensitive=False не должен матчить "MPV" по классу "mpv"
        cfg = mod.RuleConfig(classes=["mpv"], case_insensitive=False)
        m = mod.Matcher(cfg)
        c = mod.ClientInfo(address="0x1", cls="MPV", title="x")
        self.assertFalse(m.should_be_opaque(c))

        # class_title_rules: позитивный матч по AND-условию
        cfg2 = mod.RuleConfig(
            classes=[],
            class_title_rules=[{"class_regex": "^mpv$", "title_regex": "Video"}],
            case_insensitive=True,
        )
        m2 = mod.Matcher(cfg2)
        c2 = mod.ClientInfo(address="0x2", cls="mpv", title="My Video")
        self.assertTrue(m2.should_be_opaque(c2))

        # локализованные title_patterns
        cfg3 = mod.RuleConfig(title_patterns_localized={"en": ["Tutorial"]}, case_insensitive=True)
        m3 = mod.Matcher(cfg3)
        c3 = mod.ClientInfo(address="0x3", cls="foo", title="Python Tutorial #1")
        self.assertTrue(m3.should_be_opaque(c3))

    def test_check_hyprland_version_without_features(self):
        with patch("hypr_opaque_media_runtime_more.sh_json", return_value={"version": "0.42.0"}):
            mod.check_hyprland_version()  # не должно падать

    def test_handle_event_workspace_and_monitor_cache_rebuild(self):
        cfg = mod.RuleConfig()
        m = mod.Matcher(cfg)
        clients = {}
        hc_out = {
            "0xA": mod.ClientInfo(address="0xA", cls="mpv", title="Video", tags=set()),
        }
        with (
            patch(
                "hypr_opaque_media_runtime_more.hypr_clients",
                return_value=hc_out,
            ),
            patch("hypr_opaque_media_runtime_more.ensure_tag"),
        ):
            # workspace -> пересобрать кэш
            mod.handle_event("workspace", {"name": "1"}, clients, cfg, m)
            self.assertIn("0xA", clients)
            # monitoradded/removed -> аналогично
            for mev in ("monitoradded", "monitorremoved"):
                mod.handle_event(mev, {"name": "DP-1"}, clients, cfg, m)
            self.assertTrue(isinstance(clients.get("0xA"), mod.ClientInfo))

    def test_connect_with_backoff_retry_success(self):
        # Первый connect кидает OSError, второй — успех
        class Sock:
            def __init__(self):
                self.connected = False
                self.timeout = None

            def settimeout(self, t):
                self.timeout = t

            def connect(self, addr):
                if not self.connected:
                    self.connected = True
                    raise OSError("first fail")
                # второй вызов — успех

            def close(self):
                pass

        with (
            patch("hypr_opaque_media_runtime_more.socket.socket") as mock_sock_cls,
            patch("hypr_opaque_media_runtime_more.time.sleep", return_value=None),
        ):
            mock_sock = Sock()
            mock_sock_cls.return_value = mock_sock  # type: ignore
            s = mod._connect_with_backoff(
                "/tmp/sock",
                timeout_sec=0.1,
                max_attempts=2,
                notify_on_errors=False,
            )
            self.assertIsNotNone(s)

    def test_toggle_tag_exception_path(self):
        # subprocess.run кидает исключение — toggle_tag пробрасывает его наружу
        with (
            patch(
                "hypr_opaque_media_runtime_more.subprocess.run",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            mod.toggle_tag("0x1", "opaque")

    def test_main_heartbeat_log_when_no_events(self):
        # Настроим heartbeat и отсутствие событий так, чтобы сработал "No events received..."
        os.environ["XDG_RUNTIME_DIR"] = "/tmp"
        cfg = mod.RuleConfig(
            enable_metrics=False,
            config_poll_interval_sec=999,
            cache_clean_interval_sec=999,
            heartbeat_interval_sec=1.0,  # частый heartbeat
            buffer_log_interval_sec=999,
        )
        matcher = mod.Matcher(cfg)

        # Сокет возвращает несколько пустых чтений, затем KeyboardInterrupt
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = False
        mock_sock.recv.side_effect = [b"", b"", b"", KeyboardInterrupt()]

        def fake_connect(sock_path, timeout_sec, max_attempts, notify_on_errors):
            return mock_sock

        with (
            patch(
                "hypr_opaque_media_runtime_more.load_config",
                return_value=(cfg, matcher, 0.0),
            ),
            patch(
                "hypr_opaque_media_runtime_more._connect_with_backoff",
                side_effect=fake_connect,
            ),
            patch("hypr_opaque_media_runtime_more.sh_json") as mock_sh_json,
            patch("hypr_opaque_media_runtime_more.time.monotonic") as mock_time,
            patch(
                "hypr_opaque_media_runtime_more.time.sleep",
                return_value=None,
            ),
            patch("hypr_opaque_media_runtime_more.log") as mock_log,
            patch("hypr_opaque_media_runtime_more.subprocess.run") as mock_run,
        ):

            class P:
                def __init__(self):
                    self.returncode = 0
                    self.stderr = ""
                    self.stdout = ""

            mock_run.return_value = P()
            # version + возможный clients внутри пересборки кэша
            mock_sh_json.side_effect = [
                {"version": "0.42.0", "features": {"address_filter": True}},
                [],
            ]

            # Эмулируем прогресс времени: t0=0.0, затем 0.5,
            # затем > heartbeat (1.5), далее стабильно
            mock_time.side_effect = chain([0.0, 0.5, 1.5, 1.5, 1.5], repeat(1.5))

            # main сам перехватывает KeyboardInterrupt и завершается
            mod.main()

            # Проверяем, что был лог про отсутствие событий (на любом уровне)
            calls_text = " | ".join(
                map(
                    str,
                    (
                        mock_log.info.mock_calls
                        + mock_log.warning.mock_calls
                        + mock_log.debug.mock_calls
                    ),
                )
            )
            self.assertIn("No events received", calls_text)


if __name__ == "__main__":
    unittest.main()
