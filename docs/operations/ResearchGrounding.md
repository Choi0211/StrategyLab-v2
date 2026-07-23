# Research Grounding Operations

## Release Check

Windows PowerShell:

```powershell
$env:PYTHONPATH='src;tests/unit;tests/integration;tests/fixtures'
C:\Users\super\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m gaon.runtime.cli research-grounding-release-check --db .\gaon-runtime.sqlite
```

Linux systemd/VPS:

```bash
PYTHONPATH=src:tests/unit:tests/integration:tests/fixtures \
python -m gaon.runtime.cli research-grounding-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite
```

The check creates a unique run namespace by default and is safe to repeat on the same persistent SQLite database.

## Telegram Verification

Try these messages:

- `이 전략 약점과 리스크 분석해줘`
- `이 전략 개선해줘`
- `비슷한 전략 연구했어?`
- `전략 품질 점수 설명해줘`
- `백테스트 결과 보여줘`

Expected behavior:

- weakness and improvement requests use `strategy_critique`
- memory requests use `research_memory_search`
- empty memory says no stored match
- fixture-backed results disclose `fixture_backed=true`
- unavailable metrics are not fabricated

## Safety Notes

The research grounding hotfix is read-only. It does not place orders, approve promotions, access private repositories, expose secrets, or alter trading adapters.
