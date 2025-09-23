import os
import sys
import logging
import importlib.util
import unittest
from unittest.mock import patch, MagicMock

# Загружаем локальный скрипт из репозитория и регистрируем модуль (для корректной работы dataclass на Py 3.13)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LOCAL_SCRIPT = os.path.join(_REPO_ROOT, "hypr-opaque-media.py")
MODULE_PATH = os.path.expanduser(os.environ.get("HYPRO_MODULE_PATH", _LOCAL_SCRIPT))

spec = importlib.util.spec_from_file_location("hypr_opaque_media_runtime_extra", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["hypr_opaque_media_runtime_extra"] = mod
spec.loader.exec_module(mod)  # type: ignore


class TestCoreExtra(unittest.TestCase):
    def setUp(self):
        # Сброс ключевых метрик
        mod._METRICS_ENABLED = True
        mod._METRICS.update(
            {
                "hyprctl_errors": 0,
                "buffer_size_exceeded": 0,
                "unsupported_events": 0,
                "tag_operations": 0,
                "notifications_sent": 0,
            }
        )
        # Базовый handler у логгера
        logger = logging.getLogger("hypr-opaque")
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())

    def test__has_notify_send_paths(self):
        # Успешный путь
        with patch("hypr_opaque_media_runtime_extra.subprocess.run") as mock_run:
            mod._has_notify_send()
            self.assertTrue(mock_run.called)

        # FileNotFoundError
        with patch("hypr_opaque_media_runtime_extra.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(mod._has_notify_send())

        # Другая ошибка
        with patch("hypr_opaque_media_runtime_extra.subprocess.run", side_effect=RuntimeError("x")):
            self.assertFalse(mod._has_notify_send())

    def test_toggle_tag_success_and_failure(self):
        class P:
            def __init__(self, rc):
                self.returncode = rc
                self.stdout = ""
                self.stderr = ""

        # rc=0 (успех)
        with patch("hypr_opaque_media_runtime_extra.subprocess.run", return_value=P(0)) as mock_run:
            mod.toggle_tag("0x1", "opaque")
            self.assertTrue(mock_run.called)

        # rc!=0 (ошибка, но не исключение)
        with patch("hypr_opaque_media_runtime_extra.subprocess.run", return_value=P(1)) as mock_run:
            mod.toggle_tag("0x2", "opaque")
            self.assertTrue(mock_run.called)

    def test_parse_event_empty_line(self):
        ev, parts = mod.parse_event(b"")
        self.assertIsNone(ev)
        self.assertEqual(parts, {})

    def test_hypr_clients_skips_without_address_and_uses_initial_fields(self):
        with patch("hypr_opaque_media_runtime_extra.sh_json") as mock_json:
            mock_json.return_value = [
                {"class": "mpv", "title": "Video"},  # без address -> должен быть пропущен
                {"address": "0x1", "initialClass": "IMV", "initialTitle": "IMG", "tags": []},
            ]
            out = mod.hypr_clients()
            self.assertEqual(list(out.keys()), ["0x1"])
            self.assertEqual(out["0x1"].cls, "imv")
            self.assertEqual(out["0x1"].title, "IMG")

    def test_hypr_client_by_address_not_found(self):
        # address фильтр -> пусто, полный список -> пусто
        with patch("hypr_opaque_media_runtime_extra.sh_json", side_effect=[[], []]):
            info = mod.hypr_client_by_address("0xdead")
            self.assertIsNone(info)

    def test__apply_log_format_handler_setFormatter_exception(self):
        # Handler, у которого setFormatter бросает исключение
        class BadHandler(logging.StreamHandler):
            def setFormatter(self, formatter):
                raise RuntimeError("cannot set formatter")

        logger = logging.getLogger("hypr-opaque")
        bad = BadHandler()
        logger.addHandler(bad)

        with patch("hypr_opaque_media_runtime_extra.log") as mock_log:
            mod._apply_log_format("%(levelname)s: %(message)s")
            self.assertTrue(mock_log.warning.called)

        logger.removeHandler(bad)

    def test__make_logger_updates_existing_handlers(self):
        logger = logging.getLogger("hypr-opaque")
        h = logging.StreamHandler()
        logger.addHandler(h)
        lg = mod._make_logger("DEBUG", "[X] %(levelname)s: %(message)s")
        self.assertEqual(lg.level, logging.DEBUG)
        # Хэндлеры не должны дублироваться
        self.assertGreaterEqual(len(lg.handlers), 1)

    def test_sh_json_generic_exception_in_run(self):
        with patch("hypr_opaque_media_runtime_extra.subprocess.run", side_effect=RuntimeError("boom")):
            res = mod.sh_json(["clients"])
            self.assertIsNone(res)
            self.assertGreaterEqual(mod._METRICS["hyprctl_errors"], 1)

    def test_clean_stale_clients_none_removed(self):
        clients = {
            "0x1": mod.ClientInfo(address="0x1"),
            "0x2": mod.ClientInfo(address="0x2"),
        }
        with (
            patch("hypr_opaque_media_runtime_extra.hypr_client_by_address") as mock_hcli,
            patch("hypr_opaque_media_runtime_extra.log") as mock_log,
        ):
            mock_hcli.side_effect = [
                mod.ClientInfo(address="0x1"),
                mod.ClientInfo(address="0x2"),
            ]
            removed = mod.clean_stale_clients(clients, b"")
            self.assertEqual(removed, 0)
            self.assertTrue(any("No stale clients found" in str(c) for c in mock_log.debug.mock_calls))

    def test_main_early_exit_when_hyprctl_missing(self):
        # hyprctl --version бросит FileNotFoundError => sys.exit(1)
        with patch("hypr_opaque_media_runtime_extra.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(SystemExit):
                mod.main()

    def test_config_watcher_on_modified_triggers_callback(self):
        called = {"n": 0}

        def on_change():
            called["n"] += 1

        watch = mod._ConfigWatcher(_LOCAL_SCRIPT, on_change)

        class Evt:
            def __init__(self, path, is_dir=False):
                self.src_path = path
                self.is_directory = is_dir

        # Неподходящее событие — не должен вызывать
        watch.on_modified(Evt("/tmp/other.json"))
        # Подходящее — путь совпадает
        watch.on_modified(Evt(_LOCAL_SCRIPT))
        self.assertEqual(called["n"], 1)


if __name__ == "__main__":
    unittest.main()