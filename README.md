# hypr-opaque-media

[![CI](https://github.com/WynonnaSR/hypr-opaque-media/actions/workflows/ci.yml/badge.svg)](https://github.com/WynonnaSR/hypr-opaque-media/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

English | [Русский](README.ru.md)

A small daemon that automatically tags “media” windows (video/images) so they are always opaque in Hyprland.

Requirement in Hyprland (your config is usually at `~/.config/hypr/hyprland.conf`):
```conf
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

<details>
<summary>Alternative: static rules in <code>hyprland.conf</code></summary>

<!-- alternative:start -->

## Alternative: static rules in `hyprland.conf`

Instead of using the `hypr-opaque-media` daemon, you can add static rules directly in Hyprland’s config (`hyprland.conf`). This approach works well for simple, stable setups.

Minimal rule for the daemon (recommended to keep even if you also use static rules as a safety net):
```conf
# One tag-based rule; the daemon toggles the 'opaque' tag on matching windows
windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
```

Example static rules (roughly mirroring the daemon’s effect):
```conf
# Media players/viewers — always opaque
windowrulev2 = opacity 1.0 override 1.0 override, class:^(mpv|vlc|Celluloid|io.github.celluloid_player.Celluloid)$
windowrulev2 = opacity 1.0 override 1.0 override, class:^(imv|swayimg|nsxiv|feh|loupe|Gwenview|ristretto|eog|eom)$

# Fullscreen windows — always opaque
windowrulev2 = opacity 1.0 override 1.0 override, fullscreen:1

# Picture-in-Picture (EN/RU)
windowrulev2 = opacity 1.0 override 1.0 override, title:.*(Picture[- ]in[- ]Picture|Picture in picture|Картинка в картинке).*

# Firefox: tabs showing video/images
windowrulev2 = opacity 1.0 override 1.0 override, class:^(firefox)$, title:.*(YouTube|Twitch|Vimeo).*
windowrulev2 = opacity 1.0 override 1.0 override, class:^(firefox)$, title:.*\.(png|jpg|jpeg|webp|gif|bmp|svg|tiff).*
```

More on syntax: [Hyprland Wiki — Window Rules](https://wiki.hyprland.org/Configuring/Window-Rules/).

### Comparison

#### `hypr-opaque-media` daemon
Pros:
- Flexible: complex rules (localized titles, AND rules `class + title`), JSON config, hot-reload without `hyprctl reload`.
- Dynamic: reacts to Hyprland events (`openwindow`, `windowtitle`, `fullscreen`, `minimized`, `urgent`, etc.).
- Diagnostics: logs, metrics, optional error notifications.
- Resilience: window cache, buffer guardrails, log rotation, socket reconnects.
- Extensible: easy to add new events/metrics; covered by unit tests.

Cons:
- Requires Python 3.9+ and `hyprctl`; optional `watchdog`.
- Small processing overhead for events and `hyprctl` calls.
- Extra process (low footprint but still a component).

#### Static rules in `hyprland.conf`
Pros:
- Simple: no external dependencies or extra process.
- Minimal: zero overhead beyond Hyprland.
- Immediate: rules applied by the compositor directly.

Cons:
- Static: edits require changing `hyprland.conf` and reloading.
- Less flexible: complex conditions and localization get verbose.
- No built-in diagnostics: no logs/metrics.

When to choose:
- Daemon — if you want “smart” behavior, metrics/logs, localization, PiP handling, `minimized/urgent` logic.
- Static rules — if a short, stable set of apps/titles is enough (including fullscreen).

<!-- alternative:end -->

</details>

---

## Dependencies

- Required: Hyprland with `hyprctl` in your `$PATH`.
- Python 3.9+ (validated on start).
- Optional: `watchdog` for instant config reloads
  - Arch Linux (recommended): `sudo pacman -S python-watchdog`
  - Via pip (preferably in a virtualenv): `pip install watchdog`

## Quick start (TL;DR)

```bash
# 1) Add the Hyprland rule (in your hyprland.conf)
# windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque

# 2) Install the config (a minimal example is in the repo)
mkdir -p ~/.config
cp ./configs/hypr-opaque-media.json ~/.config/hypr-opaque-media.json

# 3) Install and start the systemd user unit
mkdir -p ~/.config/systemd/user
cp ./packaging/systemd/user/hypr-opaque-media.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hypr-opaque-media.service

# 4) Tail logs
journalctl --user -u hypr-opaque-media.service -f
```

Minimal config example:
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

## Installation

1) Put the script at `~/.local/bin/hypr-opaque-media.py` and make it executable:
```bash
chmod +x ~/.local/bin/hypr-opaque-media.py
```

2) Place the service unit:
- `~/.config/systemd/user/hypr-opaque-media.service`

3) Configuration files:
- Main: `~/.config/hypr-opaque-media.json`
- Optional documented template: `~/.config/hypr-opaque-media.jsonc` — JSON with comments (JSONC).
  Note: JSONC isn’t standard JSON and depends on your editor (e.g., VS Code).
  The daemon reads the `.json` file.

4) Start:
```bash
systemctl --user daemon-reload
systemctl --user enable --now hypr-opaque-media.service
journalctl --user -u hypr-opaque-media.service -f
```

### Run without systemd (for a quick check)

```bash
HYPRO_CONFIG=~/.config/hypr-opaque-media.json HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```

### Verify that the tag is applied

```bash
hyprctl clients -j | jq '.[] | select(.tags!=null and (.tags|index("opaque"))) | {class, title, tags}'
```

How to discover an app’s class (to add into `classes`):
```bash
hyprctl clients -j | jq -r '.[] | "\(.class)\t|\t\(.title)"' | sort -u
```

## Configuration (JSON)

- `tag` — a tag to assign to windows (must match your hyprland.conf rule; cannot be empty and must not contain commas).
- `fullscreen_is_media` — treat fullscreen windows as “media”.
- `minimized_is_opaque` — treat minimized windows as opaque.
- `urgent_is_opaque` — treat windows with urgency flag as opaque.
- `case_insensitive` — make regex matching case-insensitive.
- `classes` — list of app classes (lowercase exact match) always treated as opaque (mpv/imv, etc.).
- `title_patterns` — list of regexes for titles (e.g., YouTube, image/video extensions, PiP).
- `title_patterns_localized` — additional localized title patterns per language; merged into `title_patterns`.
- `class_title_rules` — AND rules: both `class_regex` AND `title_regex` must match.
- `config_poll_interval_sec` — config mtime polling interval if watchdog isn’t used; min 0.1.
- `socket_timeout_sec` — socket read timeout in seconds; min 0.1.
- `use_watchdog` — if true and the watchdog library is available, reload config on file events (no polling).
- `notify_on_errors` — send critical `notify-send` notifications (checked dynamically before each send).
- `safe_close_check` — verify `closewindow`/`destroywindow` with a second check.
- `safe_close_check_delay_sec` — delay between repeated checks; min 0.01.
- `max_reconnect_attempts` — limit socket reconnect attempts (0 = infinite).
- `enable_metrics` — log counters:
  - `events_processed`, `hyprctl_calls`, `hyprctl_errors`, `bytes_read`,
  - `max_cache_size`, `current_cache_size`,
  - `avg_event_time_ms` (mean), `max_event_time_ms` (peak), WARN for slow events (>100 ms),
  - `unsupported_events`,
  - `buffer_size_exceeded`,
  - `tag_operations`,
  - `log_file_rotations`,
  - `config_reloads`, `config_reload_time_ms`,
  - `notifications_sent`,
  - `invalid_regex_patterns`.
- `metrics_log_every` — how often to log metrics (in events), range 1..1_000_000.
- `cache_clean_interval_sec` — periodic cleanup of stale clients; min 1.0.
- `heartbeat_interval_sec` — heartbeat log interval when idle; min 1.0.
- `buffer_log_interval_sec` — independent interval to log current buffer size; min 1.0.
- `max_buffer_size_bytes` — cap for incoming event buffer; min 4096. If exceeded, the buffer is cleared with a WARN including the actual size.
- `socket_buffer_size_bytes` — read chunk size from the socket; min 1024.
- `log_file` — path to a log file (if `null`, logs go to stdout).
- `max_log_file_size_bytes` — max log file size; min 1024. If exceeded, the file is rotated to `.bak` with a cap on backups.
- `max_log_rotations` — how many `.bak` files to keep; min 1.
- `log_format` — log line format for stdout and file logger.
- `log_level` — log level (DEBUG/INFO/WARNING/ERROR).

ENV:
- `HYPRO_CONFIG` — path to the JSON config.
- `HYPRO_LOG_LEVEL` — overrides `log_level` from config.
- `HYPRO_NOTIFY_ON_ERRORS=1` — forces notifications.

## Tips

- If rules don’t seem to apply, enable DEBUG:
```bash
HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```
- Add new sites via `title_patterns` or `class_title_rules`.
- Localization: add variants to `title_patterns_localized`.

## Tests

Local test workflow:

```bash
# 1) Create and activate a virtualenv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip

# 2) Install dev tools
pip install pytest ruff black watchdog

# 3) Run tests
pytest -q

# 4) Useful variations
pytest -vv                      # verbose
pytest tests/test_core.py -q    # a single file
pytest -k "matcher and not slow" -vv  # by expression

# 5) (Optional) Coverage
pip install pytest-cov
pytest --cov=. --cov-report=term-missing
```

Notes:
- CI runs on Python 3.9–3.12. To mirror locally, consider [pyenv](https://github.com/pyenv/pyenv) or multiple virtualenvs.
- Tests are designed to run without a live Hyprland session; calls to `hyprctl` and the socket are mocked/stubbed where needed.
- Lint/format before committing:
  ```bash
  ruff check .
  black --check .
  ```

## For developers

Architecture:
- `Matcher` — compiles config into checks (`classes`, `title_patterns`, `class_title_rules`, localized).
- `ClientInfo` — per-window cache (class/title/fullscreen/minimized/urgent/tags).
- Hyprland `socket2` events are processed by client address; events without `address` are skipped (DEBUG log).
- `hypr_client_by_address` first tries `address:<addr>` filtering; on failure, it falls back to full listing (DEBUG “falling back”).

Events:
- Handled: `openwindow`, `windowtitle`, `fullscreen`, `changetag`, `windowtag`, `windowtagdel`, `tagadded`, `tagremoved`, `movewindow`, `windowmoved`, `windowresized`, `float`, `focuswindow`, `activewindow`, `screencopy`, `minimized`, `urgent`, `workspace`, `monitoradded`, `monitorremoved`, `closewindow`, `destroywindow`.
- Unknown/unsupported events are logged as WARNING with parameters and counted in `unsupported_events`.

Cache and buffer maintenance:
- Periodic cleanup every `cache_clean_interval_sec` (also logs buffer size).
- Heartbeat logs every `heartbeat_interval_sec` when idle.
- Periodic DEBUG log of current buffer size (`buffer_log_interval_sec`).
- Incoming event buffer is capped by `max_buffer_size_bytes`; on overflow it’s cleared with WARN and actual size.

Metrics:
- `events_processed`, `hyprctl_calls`, `hyprctl_errors`, `bytes_read`, `max_cache_size`, `current_cache_size`,
  `avg_event_time_ms`, `max_event_time_ms`, WARN for events >100 ms,
  `unsupported_events`, `buffer_size_exceeded`, `tag_operations`, `log_file_rotations`,
  `config_reloads`, `config_reload_time_ms`, `notifications_sent`, `invalid_regex_patterns`.
- Periodic logs and a final summary on shutdown.