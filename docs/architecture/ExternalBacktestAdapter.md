# External Backtest Adapter

Sprint 106 keeps private engine integration behind an explicit adapter
boundary.

Supported boundary order:

1. JSON request/result file contract
2. fixed executable adapter contract, documented only
3. HTTP/local API adapter interface

The public repository does not import private repositories, hard-code private
paths, include secrets, or run arbitrary shell commands. Tests use a
deterministic fake adapter.
