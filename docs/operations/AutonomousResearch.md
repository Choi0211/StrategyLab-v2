# Autonomous Research Operations

Run the release check:

```bash
python -m gaon.runtime.cli self-improving-research-release-check --db runtime.sqlite
```

Run demos:

```bash
python -m gaon.runtime.cli research-critic-demo --db runtime.sqlite --scenario overfit
python -m gaon.runtime.cli research-iteration-demo --db runtime.sqlite
python -m gaon.runtime.cli research-tournament-demo --db runtime.sqlite --top-n 3
python -m gaon.runtime.cli autonomous-research-demo --db runtime.sqlite --request "Research a safer breakout strategy"
```

All commands are advisory. They do not place orders, promote Champions, change
live strategy settings, or modify source code.
