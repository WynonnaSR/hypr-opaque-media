# hypr-opaque-media

[![CI](https://github.com/WynonnaSR/hypr-opaque-media/actions/workflows/ci.yml/badge.svg)](https://github.com/WynonnaSR/hypr-opaque-media/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | Русский

Демон, который автоматически помечает «медийные» окна (видео/картинки) тегом, чтобы сделать их всегда непрозрачными в Hyprland.

Требование в Hyprland (ваш конфигурационный файл обычно находится по пути `~/.config/hypr/hyprland.conf`):
```conf
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

<details>
<summary>Альтернатива: статические правила в <code>hyprland.conf</code></summary>

<!-- alternative:start -->

## Альтернатива: статические правила в `hyprland.conf`

Вместо использования демона `hypr-opaque-media` можно задать статические правила в файле конфигурации Hyprland (`hyprland.conf`). Это альтернативный подход, который подходит для более простых сценариев.

Минимальное правило под демон (рекомендуется даже при статических правилах как «страховка»):
```conf
# Одно правило по тегу; демон переключает тег 'opaque' на подходящих окнах
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

Пример статических правил (близких по эффекту к логике демона):
```conf
# Медиа‑плееры/просмотрщики — всегда непрозрачные
windowrulev2 = opacity 1.0 override 1.0 override, class:^(mpv|vlc|Celluloid|io.github.celluloid_player.Celluloid)$
windowrulev2 = opacity 1.0 override 1.0 override, class:^(imv|swayimg|nsxiv|feh|loupe|Gwenview|ristretto|eog|eom)$

# Полноэкранные окна — всегда непрозрачные
windowrulev2 = opacity 1.0 override 1.0 override, fullscreen:1

# Picture‑in‑Picture (англ/рус)
windowrulev2 = opacity 1.0 override 1.0 override, title:.*(Picture[- ]in[- ]Picture|Picture in picture|Картинка в картинке).*

# Firefox: вкладки с видео/изображениями
windowrulev2 = opacity 1.0 override 1.0 override, class:^(firefox)$, title:.*(YouTube|Twitch|Vimeo).*
windowrulev2 = opacity 1.0 override 1.0 override, class:^(firefox)$, title:.*\.(png|jpg|jpeg|webp|gif|bmp|svg|tiff).*
```

Подробнее о синтаксисе правил: [Hyprland Wiki — Window Rules](https://wiki.hyprland.org/Configuring/Window-Rules/).

### Сравнение подходов

#### Скрипт `hypr-opaque-media`
Преимущества:
- Гибкость: сложные правила (локализованные заголовки, комбинации `class + title`), настройка через JSON, перезагрузка без `hyprctl reload`.
- Динамика: реакция на события Hyprland (`openwindow`, `windowtitle`, `fullscreen`, `minimized`, `urgent`, и др.).
- Диагностика: подробные логи, метрики, уведомления об ошибках.
- Надёжность: кэш окон, защита буфера, ротация логов, реконнект к сокету.
- Расширяемость: легко добавлять новые события/метрики; модульные тесты.

Недостатки:
- Требует Python 3.9+ и `hyprctl`, опционально `watchdog`.
- Небольшая задержка на обработку событий и вызовы `hyprctl`.
- Отдельный процесс (пусть и с малым потреблением).

#### Статические правила в `hyprland.conf`
Преимущества:
- Простота: не требует внешних зависимостей/процессов.
- Минимализм: нулевая нагрузка от дополнительного софта.
- Мгновенность: применяются композитором напрямую.

Недостатки:
- Статичность: правки требуют редактирования `hyprland.conf` и перезагрузки.
- Ограниченная гибкость: сложные условия и локализация выражаются громоздко.
- Нет встроенной диагностики: логи/метрики отсутствуют.

Когда выбирать:
- Скрипт — если нужен «умный» и гибкий подход, метрики/логи, локализация, PiP, обработка `minimized/urgent`.
- Статические правила — если хватает короткого стабильного списка приложений и простых матчей (включая fullscreen).

<!-- alternative:end -->

</details>

---

Требование в Hyprland (обычно файл конфигурации: `~/.config/hypr/hyprland.conf`):
```conf
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

## Зависимости

- Требуется: Hyprland с `hyprctl` (в `$PATH`).
- Python 3.9+ (проверяется при запуске).
- (Опционально) `watchdog` для мгновенной перезагрузки конфигурации:
  - Arch Linux (рекомендуется): `sudo pacman -S python-watchdog`
  - Через pip (лучше в виртуальном окружении): `pip install watchdog`

## Быстрый старт (TL;DR)

```bash
# 1) Добавьте правило в Hyprland (в hyprland.conf)
# windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque

# 2) Установите конфиг (минимальный пример есть в репозитории)
mkdir -p ~/.config
cp ./configs/hypr-opaque-media.json ~/.config/hypr-opaque-media.json

# 3) Установите и запустите systemd user-юнит
mkdir -p ~/.config/systemd/user
cp ./packaging/systemd/user/hypr-opaque-media.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hypr-opaque-media.service

# 4) Смотрите логи
journalctl --user -u hypr-opaque-media.service -f
```

Минимальный пример конфигурации:
```json
{
  "tag": "opaque",
  "fullscreen_is_media": true,
  "minimized_is_opaque": true,
  "urgent_is_opaque": true,
  "case_insensitive": true,

  "classes": [
    "mpv",
    "vlc",
    "io.github.celluloid_player.celluloid",
    "imv",
    "nsxiv",
    "feh",
    "gwenview",
    "ristretto",
    "eog",
    "eom",
    "loupe"
  ],

  "title_patterns": [
    "YouTube",
    "Twitch",
    "Vimeo",
    "\\.(png|jpe?g|webp|gif|bmp|svg|tiff)$",
    "(Picture[- ]in[- ]Picture|Picture in picture|Картинка в картинке)"
  ],

  "class_title_rules": [
    { "class_regex": "^(firefox)$", "title_regex": "(YouTube|Twitch|Vimeo)" }
  ],

  "use_watchdog": true,
  "enable_metrics": true,
  "log_level": "INFO"
}
```

## Установка

1) Сохраните скрипт в `~/.local/bin/hypr-opaque-media.py` и сделайте исполняемым:
```bash
chmod +x ~/.local/bin/hypr-opaque-media.py
```

2) Положите сервис:
- `~/.config/systemd/user/hypr-opaque-media.service`

3) Конфигурация:
- Основная: `~/.config/hypr-opaque-media.json`
- (Опционально) Документированная: `~/.config/hypr-opaque-media.jsonc` — JSON с комментариями (JSONC).
  Обратите внимание: JSONC не является стандартным JSON, его рендеринг зависит от редактора (например, VS Code).
  Скрипт читает именно `.json`.

4) Запуск:
```bash
systemctl --user daemon-reload
systemctl --user enable --now hypr-opaque-media.service
journalctl --user -u hypr-opaque-media.service -f
```

### Запуск без systemd (для быстрой проверки)

```bash
HYPRO_CONFIG=~/.config/hypr-opaque-media.json HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```

### Проверка, что тег применяется

```bash
hyprctl clients -j | jq '.[] | select(.tags!=null and (.tags|index("opaque"))) | {class, title, tags}'
```

Как узнать class приложения (подставляйте в `classes`):
```bash
hyprctl clients -j | jq -r '.[] | "\(.class)\t|\t\(.title)"' | sort -u
```

## Конфигурация (JSON)

- `tag` — тег, который присваивается окнам (должен совпадать с правилом в hyprland.conf; не может быть пустым и не должен содержать запятых).
- `fullscreen_is_media` — считать полноэкранные окна «медийными».
- `minimized_is_opaque` — считать минимизированные окна непрозрачными.
- `urgent_is_opaque` — считать окна с флагом urgency непрозрачными.
- `case_insensitive` — регистронезависимые регулярные выражения.
- `classes` — список классов приложений (точное совпадение, в нижнем регистре), всегда непрозрачных (mpv/imv и т.д.).
- `title_patterns` — список регулярных выражений для заголовков (например, YouTube, расширения файлов изображений/видео, PiP).
- `title_patterns_localized` — локализованные паттерны заголовков по языкам, добавляются к `title_patterns`.
- `class_title_rules` — AND‑правила: `class_regex` И `title_regex`.
- `config_poll_interval_sec` — интервал опроса mtime конфига (если watchdog не используется), минимум 0.1.
- `socket_timeout_sec` — таймаут чтения сокета (секунды), минимум 0.1.
- `use_watchdog` — если `true` и библиотека watchdog доступна, конфиг перечитывается по событию (без опроса).
- `notify_on_errors` — отправлять критические уведомления `notify-send` (проверяется динамически перед каждой отправкой).
- `safe_close_check` — верифицировать `closewindow`/`destroywindow` (двойная проверка).
- `safe_close_check_delay_sec` — задержка между повторными проверками (сек), минимум 0.01.
- `max_reconnect_attempts` — ограничение попыток реконнекта к сокету (0 = бесконечно).
- `enable_metrics` — логировать счётчики:
  - `events_processed`, `hyprctl_calls`, `hyprctl_errors`, `bytes_read`,
  - `max_cache_size`, `current_cache_size`,
  - `avg_event_time_ms` (среднее), `max_event_time_ms` (пиковое), WARN‑лог для медленных событий (>100 мс),
  - `unsupported_events` (неподдерживаемые события),
  - `buffer_size_exceeded` (сколько раз превышался лимит буфера),
  - `tag_operations` (сколько раз меняли тег),
  - `log_file_rotations` (сколько раз ротировался файл логов),
  - `config_reloads` (сколько раз грузили конфиг), `config_reload_time_ms` (суммарное время загрузок),
  - `notifications_sent` (сколько отправлено уведомлений),
  - `invalid_regex_patterns` (сколько невалидных регулярных выражений было отвергнуто).
- `metrics_log_every` — как часто логировать метрики (в событиях), допустимо 1..1_000_000.
- `cache_clean_interval_sec` — периодическая очистка кэша от «призрачных» клиентов (сек), минимум 1.0.
- `heartbeat_interval_sec` — интервал heartbeat‑лога при отсутствии событий (сек), минимум 1.0.
- `buffer_log_interval_sec` — независимый интервал логирования текущего размера буфера (сек), минимум 1.0.
- `max_buffer_size_bytes` — максимум для буфера входящих событий сокета (байт), минимум 4096; при превышении буфер очищается с WARN‑логом и указанием фактического размера.
- `socket_buffer_size_bytes` — размер блока чтения из сокета (байт), минимум 1024.
- `log_file` — путь до файла логов (если `null`, логи в stdout).
- `max_log_file_size_bytes` — максимальный размер файла логов (байт), минимум 1024; при превышении файл автоматически ротируется в `.bak` (с ограничением количества бэкапов).
- `max_log_rotations` — сколько файлов `.bak` хранить (минимум 1).
- `log_format` — формат строки логов для stdout и файлового логгера.
- `log_level` — уровень логов (DEBUG/INFO/WARNING/ERROR).

ENV:
- `HYPRO_CONFIG` — путь к конфигу JSON.
- `HYPRO_LOG_LEVEL` — перезаписывает `log_level` из конфига.
- `HYPRO_NOTIFY_ON_ERRORS=1` — форсит уведомления.

## Подсказки

- Если правила «не попадают», включите DEBUG:
```bash
HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```
- Для других сайтов добавляйте паттерны в `title_patterns` или `class_title_rules`.
- Локализация: добавляйте варианты в `title_patterns_localized`.

## Тесты

Локальный запуск тестов:

```bash
# 1) Создайте и активируйте виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip

# 2) Установите dev-инструменты
pip install pytest ruff black watchdog

# 3) Запустите тесты
pytest -q

# 4) Полезные варианты
pytest -vv                          # подробный вывод
pytest tests/test_core.py -q        # один файл
pytest -k "matcher and not slow" -vv  # по выражению

# 5) (Опционально) Покрытие
pip install pytest-cov
pytest --cov=. --cov-report=term-missing
```

Заметки:
- CI запускает тесты на Python 3.9–3.12. Чтобы повторить локально, используйте [pyenv](https://github.com/pyenv/pyenv) или несколько виртуальных окружений.
- Юнит‑тесты не требуют живого Hyprland: обращения к `hyprctl` и сокету замоканы/заглушены.
- Перед коммитом проверьте линтер/формат:
  ```bash
  ruff check .
  black --check .
  ```

## Для разработчиков

Архитектура:
- `Matcher` — компилирует конфиг в набор проверок (`classes`, `title_patterns`, `class_title_rules`, локализованные).
- `ClientInfo` — кэш состояния окна (class/title/fullscreen/minimized/urgent/tags).
- События из Hyprland (`socket2`) обрабатываются адресно; события без `address` пропускаются (DEBUG‑лог).
- `hypr_client_by_address` сначала пытается использовать фильтр `address:<addr>`, при неудаче — полный список (DEBUG‑лог «falling back»).

События:
- Обрабатываются: `openwindow`, `windowtitle`, `fullscreen`, `changetag`, `windowtag`, `windowtagdel`, `tagadded`, `tagremoved`, `movewindow`, `windowmoved`, `windowresized`, `float`, `focuswindow`, `activewindow`, `screencopy`, `minimized`, `urgent`, `workspace`, `monitoradded`, `monitorremoved`, `closewindow`, `destroywindow`.
- Неизвестные/неподдерживаемые события логируются как WARNING с параметрами и учитываются в метрике `unsupported_events`.

Обслуживание кэша и буфера:
- Периодическая очистка каждые `cache_clean_interval_sec` (лог размера буфера выполняется внутри очистки).
- Heartbeat‑лог каждые `heartbeat_interval_sec` при отсутствии событий.
- Периодический DEBUG‑лог текущего размера буфера (интервал `buffer_log_interval_sec`).
- Ограничение размера буфера входящих событий: `max_buffer_size_bytes`, очистка буфера при превышении (с указанием фактического размера).

Метрики:
- `events_processed`, `hyprctl_calls`, `hyprctl_errors`, `bytes_read`, `max_cache_size`, `current_cache_size`,
  `avg_event_time_ms`, `max_event_time_ms`, WARN‑лог медленных событий >100 мс,
  `unsupported_events`, `buffer_size_exceeded`, `tag_operations`, `log_file_rotations`,
  `config_reloads`, `config_reload_time_ms`, `notifications_sent`, `invalid_regex_patterns`.
- Периодические логи и итоговый лог при завершении работы.