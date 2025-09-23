# Architecture Diagram

```text
[Config: ~/.config/hypr-opaque-media.json]
               ↓
[load_config → RuleConfig → Matcher]
  - compiles classes, title_patterns, class_title_rules (with localized patterns)
  - sets metrics/logging and validates parameters
               ↓
[check_hyprland_version]
  - populates feature hints (e.g., address_filter support)
               ↓
[hypr_clients snapshot → ensure_tag]
  - apply tags to current clients on startup
               ↓
[Connect to Hyprland socket2 (Unix)]
  - _connect_with_backoff with timeouts and optional notifications
               ↓
[Main loop]
  - recv bytes → buffer (with enforce_buffer_limit)
  - split by newline → parse_event (JSON-first, legacy k:v fallback)
  - normalize_event_name (…v2 → base)
  - handle_event(ev, parts, clients, cfg, matcher)
        ├─ get_address_from_parts or hypr_active_window_address() fallback
        ├─ hypr_client_by_address(address)
        │     ├─ try `hyprctl clients address:<addr>` once
        │     └─ fallback: `hyprctl clients -j` (and disable filter for session)
        ├─ update cache (ClientInfo) and metrics
        └─ ensure_tag(address, cfg.tag, matcher.should_be_opaque(info), info.tags)
               ↓
[Periodic tasks]
  - cache cleanup (clean_stale_clients)
  - heartbeat logs (when idle)
  - buffer size logs
  - config reload (watchdog or polling)
       └─ reload config, rebuild Matcher, re-snapshot clients, re-apply tags
```

Key notes:
- Events without address (seen on Hyprland v0.50+): the daemon uses `hypr_active_window_address()` for key events like `windowtitle`, `activewindow`, `focuswindow`, `openwindow`, `minimized`, `urgent`.
- Address filtering: automatic detection; after first failure, the code stops using `address:<addr>` and relies on full client listing.
- Metrics include throughput, hyprctl usage, processing times, buffer exceed count, tag operations, config reload stats, invalid regexes, and more.
- Logging supports stdout and optional file logging with rotation.