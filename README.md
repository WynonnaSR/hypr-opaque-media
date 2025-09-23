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

Tested environment example:
- OS: Arch Linux
- Hyprland: v0.50.1
- Shell: fish

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

Notes for fish shell:
- If you use fish and a virtualenv, activate with:
  ```bash
  source .venv/bin/activate.fish
  ```
  The generic `source .venv/bin/activate` is for bash/zsh; fish needs `activate.fish`.

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

Custom tag example (use a different tag, e.g., “media”):
- Hyprland rule:
  ```conf
  windowrulev2 = opacity 1.0 override 1.0 override, tag:media
  ```
- Config:
  ```json
  { "tag": "media" }
  ```

## Configuration (JSON)

This daemon reads `~/.config/hypr-opaque-media.json`. Keys and behavior (see [configs/hypr-opaque-media.json](configs/hypr-opaque-media.json) and [configs/hypr-opaque-media.jsonc](configs/hypr-opaque-media.jsonc) for current defaults):

- tag
  - Description: Tag to assign to matching windows (must match your hyprland.conf rule). Cannot be empty and must not contain commas.
  - Type: string
  - Default: "opaque"
  - Example: `"tag": "opaque"`
- fullscreen_is_media
  - Description: Treat fullscreen windows as “media”.
  - Type: bool
  - Default: true
- minimized_is_opaque
  - Description: Treat minimized windows as opaque.
  - Type: bool
  - Default: true
- urgent_is_opaque
  - Description: Treat urgency-flagged windows as opaque.
  - Type: bool
  - Default: true
- case_insensitive
  - Description: Make regex matching case-insensitive.
  - Type: bool
  - Default: true
- classes
  - Description: List of app classes (lowercase exact match) always treated as opaque.
  - Type: list[string]
  - Default: see config file
  - Example: `"classes": ["mpv", "imv", "vlc"]`
- title_patterns
  - Description: List of regex patterns for window titles (YouTube, image/video extensions, PiP phrases).
  - Type: list[string]
  - Default: see config file
  - Example: `"title_patterns": ["YouTube", "\\\\.(png|jpe?g)$"]`
- title_patterns_localized
  - Description: Localized title patterns per language; merged into `title_patterns`.
  - Type: map[string, list[string]]
  - Default: {}
  - Example:
    ```json
    {
      "title_patterns_localized": {
        "ru": ["Картинка в картинке"],
        "en": ["Picture in picture", "Picture-in-Picture"]
      }
    }
    ```
- class_title_rules
  - Description: AND rules: both `class_regex` and `title_regex` must match.
  - Type: list[object]
  - Default: see config file
  - Examples:
    ```json
    {
      "class_title_rules": [
        { "class_regex": "^(firefox)$", "title_regex": "(YouTube|Twitch|Vimeo|Netflix)" },
        { "class_regex": "(chromium|google-?chrome)", "title_regex": "Picture[- ]in[- ]Picture" }
      ]
    }
    ```
- config_poll_interval_sec
  - Description: Config mtime polling interval when watchdog is not used (min 0.1).
  - Type: float
  - Default: 8.0
- socket_timeout_sec
  - Description: Socket read timeout (min 0.1).
  - Type: float
  - Default: 1.0
- use_watchdog
  - Description: Use watchdog (if installed) to detect config changes instantly instead of polling.
  - Type: bool
  - Default: false
- notify_on_errors
  - Description: Send critical desktop notifications via `notify-send` on errors (auto-checks availability).
  - Type: bool
  - Default: false
- safe_close_check
  - Description: Verify `closewindow`/`destroywindow` before removing from cache.
  - Type: bool
  - Default: false (example JSONC uses true)
- safe_close_check_delay_sec
  - Description: Delay between verification retries (min 0.01).
  - Type: float
  - Default: 0.1
- max_reconnect_attempts
  - Description: Limit socket reconnect attempts (0 = infinite).
  - Type: int
  - Default: 0
- enable_metrics
  - Description: Enable metrics counters and periodic logs.
  - Type: bool
  - Default: false
- metrics_log_every
  - Description: Log metrics every N processed events (range 1..1,000,000).
  - Type: int
  - Default: 1000
- cache_clean_interval_sec
  - Description: Periodic cleanup of stale clients (min 1.0).
  - Type: float
  - Default: 300.0
- heartbeat_interval_sec
  - Description: Heartbeat log interval when idle (min 1.0).
  - Type: float
  - Default: 600.0
- buffer_log_interval_sec
  - Description: Independent interval for buffer size logs (min 1.0).
  - Type: float
  - Default: 600.0
- max_buffer_size_bytes
  - Description: Cap for incoming event buffer; if exceeded, clears with WARN and includes actual size (min 4096).
  - Type: int
  - Default: 1,048,576 (1 MiB)
- socket_buffer_size_bytes
  - Description: Read chunk size from the socket (min 1024).
  - Type: int
  - Default: 4096
- log_file
  - Description: Path to a log file (if null, logs go to stdout).
  - Type: string|null
  - Default: null
- max_log_file_size_bytes
  - Description: Max log file size (min 1024). Rotates to `.bak` when exceeded.
  - Type: int
  - Default: 1,048,576
- max_log_rotations
  - Description: How many rotated `.bak` files to keep (min 1).
  - Type: int
  - Default: 5
- log_format
  - Description: Log format string used for both stdout and file logger.
  - Type: string
  - Default: "[hypr-opaque] %(levelname)s: %(message)s"
- log_level
  - Description: Logging level: DEBUG/INFO/WARNING/ERROR.
  - Type: string
  - Default: INFO

Environment overrides:
- HYPRO_CONFIG — path to the JSON config.
- HYPRO_LOG_LEVEL — overrides `log_level` from config.
- HYPRO_NOTIFY_ON_ERRORS=1 — forces notifications.

Address filter behavior:
- The daemon auto-detects whether `hyprctl clients address:<addr>` filtering works and falls back to full listing after the first failed attempt. There is currently no `use_address_filter` toggle in the config; behavior is automatic. If a config flag is added in a future release, it would look like:
  ```json
  { "use_address_filter": false }
  ```
  but this option is not present in the current version.

Localization test command example:
```bash
# Verifies that Russian Picture‑in‑Picture titles match your patterns
hyprctl clients -j | jq '.[] | select(.title | test("Картинка в картинке")) | {class, title}'
```

Additional examples
- Add more sites/extensions:
  ```json
  {
    "title_patterns": [
      "YouTube",
      "Twitch",
      "Vimeo",
      "Netflix",
      "\\\\.(mp4|mkv|webm)$"
    ]
  }
  ```
- Combine class + title:
  ```json
  {
    "class_title_rules": [
      { "class_regex": "^(firefox)$", "title_regex": "Kaltura|Panopto" },
      { "class_regex": "^(mpv)$", "title_regex": "\\\\[HW Accel\\\\]" }
    ]
  }
  ```

## Tips

- If rules don’t seem to apply, enable DEBUG:
```bash
HYPRO_LOG_LEVEL=DEBUG ~/.local/bin/hypr-opaque-media.py
```
- Add new sites via `title_patterns` or `class_title_rules`.
- Localization: add variants to `title_patterns_localized`.
- Ensure you are in a Wayland Hyprland session. Check:
  ```bash
  echo "$HYPRLAND_INSTANCE_SIGNATURE"   # should be non-empty
  echo "$XDG_RUNTIME_DIR"               # should be set
  ```

## Troubleshooting / FAQ

- The tag is never applied
  - Verify Hyprland rule exists and matches your tag:
    ```conf
    windowrulev2 = opacity 1.0 override 1.0 override, tag:opaque
    ```
    The `tag` in JSON must be `"opaque"`.
  - Check logs:
    ```bash
    journalctl --user -u hypr-opaque-media.service -e -n 200
    ```
    Look for invalid regex warnings or `unsupported_events`.
- hyprctl address filter seems unsupported
  - Symptom: logs show fallback from `address:<addr>` to full `hyprctl clients -j`; `hyprctl_calls` spikes.
  - Cause: Possible IPC quirks in Hyprland v0.50.1 or environment issues; some builds don’t fully support address filtering.
  - Workaround: The daemon auto-disables the filter after the first failure. Monitor `hyprctl_calls` and `avg_event_time_ms`. If a `use_address_filter` config flag is introduced, set `"use_address_filter": false`.
- hyprctl clients -j returns empty or errors
  - Ensure you’re in a Hyprland Wayland session (not TTY/other compositor).
  - Test Hyprland IPC:
    ```bash
    hyprctl monitors -j
    hyprctl clients -j
    ```
  - If running the script outside systemd, ensure your environment has `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`, and `HYPRLAND_INSTANCE_SIGNATURE` set (inherit from your login shell).
- Virtual environment activation fails in fish shell
  - Symptom: `source .venv/bin/activate` fails with “case builtin not inside of switch block”.
  - Cause: The `activate` script is for bash/zsh; fish requires `activate.fish`.
  - Workaround:
    ```bash
    source .venv/bin/activate.fish
    ```
    Or add an alias in `~/.config/fish/config.fish`:
    ```fish
    alias activate 'source .venv/bin/activate.fish'
    ```
- Git passphrase prompt in Hyprland
  - Symptom: Git asks for SSH passphrase on every `git push`.
  - Cause: `ssh-agent` not running or not integrated with Hyprland.
  - Workaround: Add to `~/.config/hypr/hyprland.conf`:
    ```bash
    exec-once = keychain --nogui --quiet ~/.ssh/id_ed25519
    ```
    And in `~/.config/fish/config.fish`:
    ```fish
    if status is-interactive
        keychain --nogui --quiet ~/.ssh/id_ed25519
        source ~/.ssh-agent.fish
    end
    ```
- Firefox memory leak or high RAM when watching videos
  - The daemon does not inject into apps; it only tags windows. Memory issues are in the browser.
  - Workaround:
    - Check `about:memory` and extensions.
    - Toggle hardware acceleration in `about:config` (e.g., `gfx.webrender.all`).
    - Restart the tab/profile; upgrade Firefox.
- Too many notifications
  - Set `"notify_on_errors": false` (or leave unset) to avoid desktop notifications.
- Buffer overflow warnings
  - Increase `"max_buffer_size_bytes"`, and ensure no runaway event floods.
- Service won’t start
  - Check Python version (3.9+), `hyprctl` availability, and review:
    ```bash
    systemctl --user status hypr-opaque-media.service
    journalctl --user -u hypr-opaque-media.service -e
    ```

## Tests

Local test workflow:
```bash
# 1) Create and activate a virtualenv
python -m venv .venv
# bash/zsh:
source .venv/bin/activate
# fish:
source .venv/bin/activate.fish
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
- Current test coverage: ~92% (per last CI). Target coverage: ≥90%.
- CI runs on Python 3.9–3.12 (see [.github/workflows/ci.yml](.github/workflows/ci.yml)).
- Tests do not require a live Hyprland session; calls to `hyprctl` and the socket are mocked with `unittest.mock`.
- Lint/format before committing:
  ```bash
  ruff check .
  black --check .
  ```

Coverage highlights (what tests aim to verify):
- Parsing and config:
  - Load/merge JSON, env overrides, invalid regex reporting (`invalid_regex_patterns`).
- Matching:
  - `classes` exact match (lowercase), `title_patterns` regex, `class_title_rules` AND logic.
  - `case_insensitive` toggles.
- Events:
  - `openwindow`, `windowtitle`, `fullscreen`, `minimized`, `urgent`, tag changes (`windowtag`, `windowtagdel`, `tagadded`, `tagremoved`), moves/resizes, focus changes, `workspace`, `monitoradded/removed`, and handling events without address via `hypr_active_window_address` fallback.
  - Safe close verification (`safe_close_check`, `safe_close_check_delay_sec`).
- Metrics:
  - `events_processed`, `hyprctl_calls`/`hyprctl_errors`, time stats, cache size tracking, buffer overflow, config reload counts.
- Error paths:
  - Socket reconnect behavior, unsupported/unknown events counted in `unsupported_events`, log rotation edge cases.

Contributing
- Please open a GitHub Issue first for bugs or feature requests to discuss scope and design.
- PR acceptance criteria:
  - Clear description and rationale (what/why).
  - CI passing (ruff, black, and tests on 3.9–3.12).
  - Tests updated/added for new behavior.
  - Attach a coverage summary for significant changes:
    ```bash
    pytest --cov=. --cov-report=term-missing
    ```
  - Target coverage ≥90% locally.
- Workflow:
  ```bash
  git fork
  git checkout -b feat/my-improvement
  # make changes
  ruff check .
  black .
  pytest -q
  git push -u origin feat/my-improvement
  # open PR with details and logs/screenshots if relevant
  ```

## For developers

Architecture (high level):
- See the text diagram in [docs/architecture.md](docs/architecture.md)

Selected components:
- Matcher — compiles config into checks (`classes`, `title_patterns`, `class_title_rules`, localized).
- ClientInfo — per-window cache (class/title/fullscreen/minimized/urgent/tags).
- Events without address:
  - The daemon tries to infer the address of the active window via `hypr_active_window_address()` for key events (e.g., `windowtitle`, `activewindow`, `focuswindow`, `openwindow`, `minimized`, `urgent`) because Hyprland v0.50+ sometimes omits addresses in socket payloads.
- Address filter:
  - `hypr_client_by_address()` prefers `hyprctl clients address:<addr>` and falls back to a full list on failure; after the first failure, the filter is disabled for the session. `check_hyprland_version()` may detect features and pre-set support flags.

Example: using Matcher in code (adapt import to your setup)
```python
# If you rename hypr-opaque-media.py to a module (e.g., hypro.py), you can import directly:
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

Metrics (what they mean):
- events_processed — number of processed events.
- hyprctl_calls — total `hyprctl` invocations.
- hyprctl_errors — failed `hyprctl` runs or JSON parses.
- bytes_read — raw bytes read from the socket.
- current_cache_size / max_cache_size — live and peak window cache size.
- event_processing_time_ms / max_event_processing_time_ms — cumulative and peak per-event processing time; slow events (>100ms) WARN.
- unsupported_events — number of ignored/unknown events (for visibility).
- buffer_size_exceeded — how many times the incoming buffer was cleared due to overflow.
- tag_operations — tag toggles executed.
- log_file_rotations — count of log rotations due to size.
- config_reloads / config_reload_time_ms — number and time of config reloads.
- notifications_sent — notifications sent via `notify-send`.
- invalid_regex_patterns — invalid regex patterns encountered during Matcher compilation.

Performance notes:
- High hyprctl_calls:
  - Often indicates address filter fallback (older Hyprland or unsupported IPC features).
  - Monitor `avg_event_time_ms` and `max_event_time_ms`; if elevated, consider simplifying rules (e.g., fewer regexes, fewer class+title AND rules) or reducing event volume.

Compatibility notes
- Hyprland session required:
  - `HYPRLAND_INSTANCE_SIGNATURE` and `XDG_RUNTIME_DIR` must be set (main() enforces this).
- Address filtering:
  - Preferred path uses `hyprctl clients address:<addr>`. If unsupported (e.g., on some Hyprland v0.50.1 builds), the daemon detects and falls back automatically.
- Python: 3.9+.
- System: Linux with Hyprland; a systemd user unit is provided (optional).

## About / License

[MIT License](LICENSE)