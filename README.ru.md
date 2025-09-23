# hypr-opaque-media

[![CI](https://github.com/WynonnaSR/hypr-opaque-media/actions/workflows/ci.yml/badge.svg)](https://github.com/WynonnaSR/hypr-opaque-media/actions/workflows/ci.yml)
[![Лицензия: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | Русский

Небольшой демон, который автоматически помечает окна “медиа” (видео/изображения) тегом, чтобы они всегда были непрозрачными в Hyprland.

Требование в Hyprland (обычно конфиг — `~/.config/hypr/hyprland.conf`):
```conf
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

<details>
<summary>Альтернатива: статические правила в <code>hyprland.conf</code></summary>

<!-- alternative:start -->

## Альтернатива: статические правила в `hyprland.conf`

Вместо использования демона `hypr-opaque-media` вы можете добавить статические правила прямо в конфиг Hyprland (`hyprland.conf`). Этот подход удобен для простых и стабильных конфигураций.

Минимальное правило для демона (желательно оставить даже при использовании статических правил как «сетку безопасности»):
```conf
# Одно правило по тегу; демон переключает тег 'opaque' на подходящих окнах
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

Примеры статических правил (примерно повторяют поведение демона):
```conf
# Проигрыватели/просмотрщики — всегда непрозрачные
windowrulev2 = opacity 1.0 override 1.0 override, class:^(mpv|vlc|Celluloid|io.github.celluloid_player.Celluloid)$
windowrulev2 = opacity 1.0 override 1.0 override, class:^(imv|swayimg|nsxiv|feh|loupe|Gwenview|ristretto|eog|eom)$

# Полноэкранные окна — всегда непрозрачные
windowrulev2 = opacity 1.0 override 1.0 override, fullscreen:1

# Картинка-в-Картинке (EN/RU)
windowrulev2 = opacity 1.0 override 1.0 override, title:.*(Picture[- ]in[- ]Picture|Picture in picture|Картинка в картинке).*

# Firefox: вкладки с видео/изображениями
windowrulev2 = opacity 1.0 override 1.0 override, class:^(firefox)$, title:.*(YouTube|Twitch|Vimeo).*
windowrulev2 = opacity 1.0 override 1.0 override, class:^(firefox)$, title:.*\.(png|jpg|jpeg|webp|gif|bmp|svg|tiff).*
```

Больше о синтаксисе: [Hyprland Wiki — Window Rules](https://wiki.hyprland.org/Configuring/Window-Rules/).

### Сравнение

#### Демон `hypr-opaque-media`
Плюсы:
- Гибкость: сложные правила (локализованные заголовки, AND-правила `class + title`), JSON-конфиг, «горячая» перезагрузка без `hyprctl reload`.
- Динамика: реакции на события Hyprland (`openwindow`, `windowtitle`, `fullscreen`, `minimized`, `urgent` и пр.).
- Диагностика: логи, метрики, опциональные уведомления об ошибках.
- Надёжность: кэш окон, ограничения буфера, ротация логов, переподключение сокета.
- Расширяемость: легко добавить новые события/метрики; покрыто юнит-тестами.

Минусы:
- Требуются Python 3.9+ и `hyprctl`; опционально `watchdog`.
- Небольшие накладные расходы на обработку событий и вызовы `hyprctl`.
- Дополнительный процесс (небольшой footprint, но всё же компонент).

#### Статические правила в `hyprland.conf`
Плюсы:
- Простота: нет внешних зависимостей и процессов.
- Минимализм: нулевая нагрузка сверх Hyprland.
- Мгновенность: правила применяются самим композитором.

Минусы:
- Статичность: правки требуют изменения `hyprland.conf` и перезагрузки.
- Меньше гибкости: сложные условия и локализация становятся многословными.
- Нет диагностик из коробки: нет логов/метрик.

Когда выбирать:
- Демон — если нужны “умное” поведение, метрики/логи, локализация, PiP, логика `minimized/urgent`.
- Статика — если хватает короткого стабильного набора приложений/заголовков (включая fullscreen).

<!-- alternative:end -->

</details>

---

## Зависимости

- Обязательно: Hyprland с `hyprctl` в `$PATH`.
- Python 3.9+ (проверяется при старте).
- Опционально: `watchdog` для мгновенной перезагрузки конфига
  - Arch Linux (рекомендуется): `sudo pacman -S python-watchdog`
  - Через pip (желательно в venv): `pip install watchdog`

Пример окружения:
- ОС: Arch Linux
- Hyprland: v0.50.1
- Shell: fish

## Быстрый старт (TL;DR)

```bash
# 1) Добавьте правило Hyprland (в ваш hyprland.conf)
# windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque

# 2) Установите конфиг (минимальный пример есть в репозитории)
mkdir -p ~/.config
cp ./configs/hypr-opaque-media.json ~/.config/hypr-opaque-media.json

# 3) Установите и запустите systemd user unit
mkdir -p ~/.config/systemd/user
cp ./packaging/systemd/user/hypr-opaque-media.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hypr-opaque-media.service

# 4) Смотрите логи
journalctl --user -u hypr-opaque-media.service -f
```

Минимальный пример конфига:
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

1) Поместите скрипт в `~/.local/bin/hypr-opaque-media.py` и сделайте исполняемым:
```bash
chmod +x ~/.local/bin/hypr-opaque-media.py
```

2) Разместите unit:
- `~/.config/systemd/user/hypr-opaque-media.service`

3) Файлы конфигурации:
- Основной: `~/.config/hypr-opaque-media.json`
- Опциональный шаблон с комментариями: `~/.config/hypr-opaque-media.jsonc` (JSON с комментариями).
  Примечание: JSONC — не стандартный JSON и зависит от редактора (например, VS Code).
  Демон читает файл `.json`.

4) Запуск:
```bash
systemctl --user daemon-reload
systemctl --user enable --now hypr-opaque-media.service
journalctl --user -u hypr-opaque-media.service -f
```

Примечания для fish:
- Если используете fish и virtualenv, активируйте окружение так:
  ```bash
  source .venv/bin/activate.fish
  ```
  Скрипт `activate` для bash/zsh; fish требует `activate.fish`.

### Запуск без systemd (быстрая проверка)

```bash
HYPRO_CONFIG=~/.config/hypr-opaque-media.json HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```

### Проверка, что тег применён

```bash
hyprctl clients -j | jq '.[] | select(.tags!=null and (.tags|index("opaque"))) | {class, title, tags}'
```

Как узнать класс приложения (чтобы добавить в `classes`):
```bash
hyprctl clients -j | jq -r '.[] | "\(.class)\t|\t\(.title)"' | sort -u
```

Пример с кастомным тегом (например, “media”):
- Правило Hyprland:
  ```conf
  windowrulev2 = opacity 1.0 override 1.0 override, tag:media
  ```
- Конфиг:
  ```json
  { "tag": "media" }
  ```

## Конфигурация (JSON)

Демон читает `~/.config/hypr-opaque-media.json`. Ключи и поведение (см. актуальные значения в [configs/hypr-opaque-media.json](configs/hypr-opaque-media.json) и [configs/hypr-opaque-media.jsonc](configs/hypr-opaque-media.jsonc)):

- tag
  - Описание: Тег, присваиваемый подходящим окнам (должен совпадать с правилом в hyprland.conf). Не может быть пустым и не должен содержать запятых.
  - Тип: string
  - По умолчанию: "opaque"
- fullscreen_is_media
  - Описание: Считать полноэкранные окна «медиа».
  - Тип: bool
  - По умолчанию: true
- minimized_is_opaque
  - Описание: Свёрнутые окна непрозрачны.
  - Тип: bool
  - По умолчанию: true
- urgent_is_opaque
  - Описание: Окна с флагом срочности — непрозрачны.
  - Тип: bool
  - По умолчанию: true
- case_insensitive
  - Описание: Регулярные выражения без учёта регистра.
  - Тип: bool
  - По умолчанию: true
- classes
  - Описание: Список классов приложений (в нижнем регистре, точное совпадение), всегда непрозрачных.
  - Тип: list[string]
  - По умолчанию: см. конфиг
- title_patterns
  - Описание: Список regex-паттернов для заголовков окон (YouTube, расширения картинок/видео, фразы PiP).
  - Тип: list[string]
  - По умолчанию: см. конфиг
- title_patterns_localized
  - Описание: Локализованные паттерны заголовков по языкам; объединяются с `title_patterns`.
  - Тип: map[string, list[string]]
  - По умолчанию: {}
  - Пример:
    ```json
    {
      "title_patterns_localized": {
        "ru": ["Картинка в картинке"],
        "en": ["Picture in picture", "Picture-in-Picture"]
      }
    }
    ```
- class_title_rules
  - Описание: AND-правила: должны совпасть и `class_regex`, и `title_regex`.
  - Тип: list[object]
  - По умолчанию: см. конфиг
- config_poll_interval_sec
  - Описание: Период опроса mtime конфига при неиспользовании watchdog (мин. 0.1).
  - Тип: float
  - По умолчанию: 8.0
- socket_timeout_sec
  - Описание: Таймаут чтения сокета (мин. 0.1).
  - Тип: float
  - По умолчанию: 1.0
- use_watchdog
  - Описание: Использовать watchdog (если установлен) для мгновенного отслеживания изменений конфига (без опроса).
  - Тип: bool
  - По умолчанию: false
- notify_on_errors
  - Описание: Отправлять критические уведомления через `notify-send` (доступность проверяется).
  - Тип: bool
  - По умолчанию: false
- safe_close_check
  - Описание: Подтверждать `closewindow`/`destroywindow` перед удалением из кэша.
  - Тип: bool
  - По умолчанию: false (в шаблоне JSONC — true)
- safe_close_check_delay_sec
  - Описание: Задержка между повторными проверками (мин. 0.01).
  - Тип: float
  - По умолчанию: 0.1
- max_reconnect_attempts
  - Описание: Лимит попыток переподключения сокета (0 = бесконечно).
  - Тип: int
  - По умолчанию: 0
- enable_metrics
  - Описание: Включить метрики и периодические логи.
  - Тип: bool
  - По умолчанию: false
- metrics_log_every
  - Описание: Логировать метрики каждые N обработанных событий (1..1,000,000).
  - Тип: int
  - По умолчанию: 1000
- cache_clean_interval_sec
  - Описание: Периодическая очистка кэша клиентов (мин. 1.0).
  - Тип: float
  - По умолчанию: 300.0
- heartbeat_interval_sec
  - Описание: Период «пульса» в логах при простое (мин. 1.0).
  - Тип: float
  - По умолчанию: 600.0
- buffer_log_interval_sec
  - Описание: Независимый интервал логов размера буфера (мин. 1.0).
  - Тип: float
  - По умолчанию: 600.0
- max_buffer_size_bytes
  - Описание: Лимит входного буфера; при превышении — очистка с WARN и фактическим размером (мин. 4096).
  - Тип: int
  - По умолчанию: 1,048,576
- socket_buffer_size_bytes
  - Описание: Размер чтения из сокета (мин. 1024).
  - Тип: int
  - По умолчанию: 4096
- log_file
  - Описание: Путь к лог-файлу (если null — вывод в stdout).
  - Тип: string|null
  - По умолчанию: null
- max_log_file_size_bytes
  - Описание: Максимальный размер лог-файла (мин. 1024). При превышении — ротация в `.bak`.
  - Тип: int
  - По умолчанию: 1,048,576
- max_log_rotations
  - Описание: Сколько `.bak` хранить (мин. 1).
  - Тип: int
  - По умолчанию: 5
- log_format
  - Описание: Формат строк логов для stdout и файла.
  - Тип: string
  - По умолчанию: "[hypr-opaque] %(levelname)s: %(message)s"
- log_level
  - Описание: Уровень логирования: DEBUG/INFO/WARNING/ERROR.
  - Тип: string
  - По умолчанию: INFO

Переменные окружения:
- HYPRO_CONFIG — путь к JSON-конфигу.
- HYPRO_LOG_LEVEL — переопределяет `log_level`.
- HYPRO_NOTIFY_ON_ERRORS=1 — принудительные уведомления.

Поведение фильтра адреса:
- Демон автоматически определяет, работает ли фильтр `hyprctl clients address:<addr>`, и откатывается к полному списку после первой неудачи. Отдельного параметра `use_address_filter` в конфиге сейчас нет. Если он появится в будущих версиях, это будет выглядеть так:
  ```json
  { "use_address_filter": false }
  ```
  но в текущей версии опции нет.

Проверка локализации:
```bash
# Проверяет, что русская фраза «Картинка в картинке» (PiP) совпадает с вашими паттернами
hyprctl clients -j | jq '.[] | select(.title | test("Картинка в картинке")) | {class, title}'
```

## Подсказки

- Если правила не срабатывают, включите DEBUG:
```bash
HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```
- Добавляйте новые сайты через `title_patterns` или `class_title_rules`.
- Локализация: добавляйте варианты в `title_patterns_localized`.
- Убедитесь, что вы в сессии Hyprland (Wayland):
  ```bash
  echo "$HYPRLAND_INSTANCE_SIGNATURE"   # должен быть непустым
  echo "$XDG_RUNTIME_DIR"               # должен быть установлен
  ```

## Устранение неполадок / FAQ

- Тег не применяется
  - Проверьте наличие правила Hyprland и совпадение тега:
    ```conf
    windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
    ```
    В JSON должен быть `"tag": "opaque"`.
  - Проверьте логи:
    ```bash
    journalctl --user -u hypr-opaque-media.service -e -n 200
    ```
    Ищите предупреждения об ошибочных regex или `unsupported_events`.
- Фильтр адреса в hyprctl не работает
  - Симптом: логи показывают откат с `address:<addr>` к полному `hyprctl clients -j`; растёт `hyprctl_calls`.
  - Причина: возможные особенности IPC в Hyprland v0.50.1 или окружении; некоторые сборки не поддерживают фильтрацию по адресу.
  - Обход: демон сам отключает фильтр после первой неудачи. Следите за `hyprctl_calls` и `avg_event_time_ms`. Если будет добавлен `use_address_filter`, установите `"use_address_filter": false`.
- `hyprctl clients -j` пустой или с ошибкой
  - Убедитесь, что вы в Wayland-сессии Hyprland.
  - Проверьте IPC:
    ```bash
    hyprctl monitors -j
    hyprctl clients -j
    ```
  - При запуске вне systemd убедитесь, что окружение содержит `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`.
- Не получается активировать виртуальное окружение в fish
  - Симптом: `source .venv/bin/activate` падает с “case builtin not inside of switch block”.
  - Причина: `activate` для bash/zsh; fish требует `activate.fish`.
  - Решение:
    ```bash
    source .venv/bin/activate.fish
    ```
    Или добавьте алиас в `~/.config/fish/config.fish`:
    ```fish
    alias activate 'source .venv/bin/activate.fish'
    ```
- Git постоянно спрашивает пароль для SSH в Hyprland
  - Симптом: Git просит passphrase при каждом `git push`.
  - Причина: `ssh-agent` не запущен/не интегрирован с Hyprland.
  - Решение: добавьте в `~/.config/hypr/hyprland.conf`:
    ```bash
    exec-once = keychain --nogui --quiet ~/.ssh/id_ed25519
    ```
    И в `~/.config/fish/config.fish`:
    ```fish
    if status is-interactive
        keychain --nogui --quiet ~/.ssh/id_ed25519
        source ~/.ssh-agent.fish
    end
    ```
- Утечки памяти/высокая RAM в Firefox при видео
  - Демон не внедряется в приложения; он лишь помечает окна. Проблема в браузере.
  - Что попробовать:
    - Проверьте `about:memory` и расширения.
    - Переключите аппаратное ускорение в `about:config` (например, `gfx.webrender.all`).
    - Перезапустите вкладку/профиль; обновите Firefox.
- Слишком много уведомлений
  - Установите `"notify_on_errors": false` (или не задавайте).
- Предупреждения о переполнении буфера
  - Увеличьте `"max_buffer_size_bytes"` и проверьте, нет ли «бури» событий.
- Unit не запускается
  - Проверьте Python (3.9+), наличие `hyprctl`, и логи:
    ```bash
    systemctl --user status hypr-opaque-media.service
    journalctl --user -u hypr-opaque-media.service -e
    ```

## Тесты

Локальный цикл:
```bash
# 1) Создайте и активируйте виртуальное окружение
python -m venv .venv
# bash/zsh:
source .venv/bin/activate
# fish:
source .venv/bin/activate.fish
python -m pip install --upgrade pip

# 2) Инструменты разработчика
pip install pytest ruff black watchdog

# 3) Запуск тестов
pytest -q

# 4) Варианты
pytest -vv
pytest tests/test_core.py -q
pytest -k "matcher and not slow" -vv

# 5) (Опционально) Покрытие
pip install pytest-cov
pytest --cov=. --cov-report=term-missing
```

Заметки:
- Текущее покрытие тестами: ~92% (по последнему CI). Цель: ≥90%.
- CI запускается на Python 3.9–3.12 (см. [.github/workflows/ci.yml](.github/workflows/ci.yml)).
- Тесты не требуют живой сессии Hyprland; вызовы `hyprctl` и socket2 мокируются через `unittest.mock`.
- Линт/формат перед коммитом:
  ```bash
  ruff check .
  black --check .
  ```

Что покрывают тесты:
- Парсинг и конфиг:
  - Загрузка/слияние JSON, переопределения окружением, отчёт об ошибочных regex (`invalid_regex_patterns`).
- Сопоставление:
  - Точное соответствие `classes`, regex `title_patterns`, AND-логика `class_title_rules`.
  - Переключатель `case_insensitive`.
- События:
  - `openwindow`, `windowtitle`, `fullscreen`, `minimized`, `urgent`, изменения тегов (`windowtag`, `windowtagdel`, `tagadded`, `tagremoved`), перемещения/изменение размера, смена фокуса, `workspace`, `monitoradded/removed`, обработка событий без address через `hypr_active_window_address`.
  - Безопасная проверка закрытия (`safe_close_check`, `safe_close_check_delay_sec`).
- Метрики:
  - `events_processed`, `hyprctl_calls`/`hyprctl_errors`, время обработки, размеры кэша, переполнение буфера, перезагрузки конфига.
- Ошибки:
  - Переподключение к сокету, учёт `unsupported_events`, углы ротации логов.

Вклад (Contributing)
- Пожалуйста, сначала создайте GitHub Issue для бага/фичи, чтобы обсудить объём и дизайн.
- Критерии приёма PR:
  - Понятное описание и мотивация (что/почему).
  - CI зелёный (ruff, black, и тесты на 3.9–3.12).
  - Тесты обновлены/добавлены.
  - Приложите краткий отчёт о покрытии для существенных изменений:
    ```bash
    pytest --cov=. --cov-report=term-missing
    ```
  - Цель покрытия ≥90% локально.
- Процесс:
  ```bash
  git fork
  git checkout -b feat/my-improvement
  # изменения
  ruff check .
  black .
  pytest -q
  git push -u origin feat/my-improvement
  # откройте PR с деталями и логами/скриншотами при необходимости
  ```

## Для разработчиков

Архитектура (высокий уровень):
- См. диаграмму в [docs/architecture.md](docs/architecture.md)

Ключевые компоненты:
- Matcher — компилирует конфиг в проверки (`classes`, `title_patterns`, `class_title_rules`, локализация).
- ClientInfo — кэш на окно (class/title/fullscreen/minimized/urgent/tags).
- События без address:
  - Для ключевых событий (`windowtitle`, `activewindow`, `focuswindow`, `openwindow`, `minimized`, `urgent`) в Hyprland v0.50+ адрес иногда отсутствует; демон использует `hypr_active_window_address()` как резерв.
- Фильтр адреса:
  - `hypr_client_by_address()` предпочитает `hyprctl clients address:<addr>` и откатывается к полному списку; после первой неудачи фильтр отключается. `check_hyprland_version()` может заранее определить поддержку фичи.

Пример: использование Matcher (адаптируйте импорт под ваш путь)
```python
# Если переименовать hypr-opaque-media.py в модуль (например, hypro.py), можно импортировать напрямую:
# from hypro import RuleConfig, Matcher, ClientInfo

cfg = RuleConfig(
    tag="opaque",
    classes=["mpv", "vlc"],
    title_patterns=["YouTube", "Twitch"],
    class_title_rules=[{"class_regex": "^firefox$", "title_regex": "Netflix"}],
    case_insensitive=True,
)
matcher = Matcher(cfg)

info = ClientInfo(address="0x123", cls="firefox", title="Netflix")
print(matcher.should_be_opaque(info))  # True
```

Метрики (как читать):
- events_processed — обработано событий.
- hyprctl_calls — вызовов `hyprctl`.
- hyprctl_errors — ошибок `hyprctl`/JSON.
- bytes_read — байт прочитано из сокета.
- current_cache_size / max_cache_size — текущий/пиковый размер кэша окон.
- event_processing_time_ms / max_event_processing_time_ms — суммарное/пиковое время обработки; >100мс — WARN.
- unsupported_events — количество проигнорированных/неизвестных событий.
- buffer_size_exceeded — сколько раз входной буфер очищался из-за переполнения.
- tag_operations — операции переключения тега.
- log_file_rotations — ротации лог-файла.
- config_reloads / config_reload_time_ms — количество и время перезагрузок конфига.
- notifications_sent — отправленные `notify-send`.
- invalid_regex_patterns — невалидные regex при компиляции Matcher.

Производительность:
- Высокий `hyprctl_calls`:
  - Часто признак отката от фильтрации по адресу (старая/особенная сборка Hyprland).
  - Следите за `avg_event_time_ms` и `max_event_time_ms`; упростите правила (меньше regex, меньше AND-правил), снижайте объём событий.

Совместимость
- Требуется сессия Hyprland:
  - `HYPRLAND_INSTANCE_SIGNATURE` и `XDG_RUNTIME_DIR` должны быть установлены (main() это проверяет).
- Фильтрация по адресу:
  - Предпочтительно `hyprctl clients address:<addr>`. Если не поддерживается (например, на некоторых сборках Hyprland v0.50.1), демон автоматически откатится.
- Python: 3.9+.
- Система: Linux с Hyprland; есть systemd user unit (опционально).

## О проекте / Лицензия

[MIT License](LICENSE)