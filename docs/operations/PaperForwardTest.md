# Paper Forward-Test Operations

Sprint 45 commands operate in paper simulation only.

## Create And Start

```bash
python -m gaon.runtime.cli paper-session-create --db runtime.sqlite --session-id paper1
python -m gaon.runtime.cli paper-session-start --db runtime.sqlite paper1
```

Optional active Champion guards:

```bash
python -m gaon.runtime.cli paper-session-create --db runtime.sqlite --session-id paper1 --champion-version-id <active_version_id> --fingerprint <active_fingerprint>
```

## Simulate

```bash
python -m gaon.runtime.cli paper-session-simulate-order --db runtime.sqlite --session-id paper1 --symbol 005930 --quantity 1 --price 70000 --side buy
```

## Lifecycle

```bash
python -m gaon.runtime.cli paper-session-pause --db runtime.sqlite paper1
python -m gaon.runtime.cli paper-session-resume --db runtime.sqlite paper1
python -m gaon.runtime.cli paper-session-complete --db runtime.sqlite paper1
python -m gaon.runtime.cli paper-session-cancel --db runtime.sqlite paper1
```

## Inspect

```bash
python -m gaon.runtime.cli paper-session-show --db runtime.sqlite paper1
python -m gaon.runtime.cli paper-session-list --db runtime.sqlite
python -m gaon.runtime.cli paper-session-summary --db runtime.sqlite paper1
```

## Boundaries

Paper sessions are for forward-test tracking only. They do not place real orders, connect to KIS, access broker credentials, change the Champion automatically, or promote to live trading.
