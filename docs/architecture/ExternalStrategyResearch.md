# External Strategy Research Architecture

Status: Sprint 61-70 implementation draft

Gaon external strategy research extends the existing conversation and safe-tool runtime with read-only external intelligence and bounded strategy research.

Implemented scope:

- External web research abstraction with normalized results.
- Structured read-only tools: `weather_current`, `weather_forecast`, `exchange_rate`, `market_data`, `news_search`, `web_search`.
- Source provenance with citation ID, canonical URL, domain, published timestamp, retrieved timestamp, trust classification, and freshness.
- SSRF guard for localhost, loopback, private networks, link-local networks, metadata hosts, credentials in URLs, and unsupported schemes.
- Bounded multi-tool planner support for market/news/FX research.
- Strategy research planner, challenger experiment fixture, deterministic backtest, validation, Champion comparison, and research report.
- SQLite persistence for strategy research plans, experiments, and reports.

Safety boundaries:

- External content is untrusted data.
- Webpage instructions are never treated as agent instructions.
- No shell, arbitrary SQL, local file access, secret access, broker order, live KIS, automatic approval, or automatic Champion promotion is implemented.
- Default external provider is fixture-only. Production network providers must be explicitly added behind the same URL and timeout policy.

Known limitations:

- Structured market, weather, and FX providers currently return `provider_not_configured` fixture payloads unless a future provider is configured.
- Intraday `1m`, `3m`, and `5m` research returns `data_unavailable` when verified minute data is absent.
- Research reports can recommend, reject, or request more validation, but cannot promote a Champion.
