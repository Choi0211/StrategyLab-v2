# Research Grounding Operations

## Release Checks

Windows PowerShell:

```powershell
$env:PYTHONPATH='src;tests/unit;tests/integration;tests/fixtures'
C:\Users\super\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m gaon.runtime.cli research-grounding-release-check --db .\gaon-runtime.sqlite
C:\Users\super\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m gaon.runtime.cli research-context-isolation-release-check --db .\gaon-runtime.sqlite
```

Linux systemd/VPS:

```bash
PYTHONPATH=src:tests/unit:tests/integration:tests/fixtures \
python -m gaon.runtime.cli research-grounding-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite

PYTHONPATH=src:tests/unit:tests/integration:tests/fixtures \
python -m gaon.runtime.cli research-context-isolation-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite
```

Both checks create unique run namespaces by default and are safe to repeat on the same persistent SQLite database.

## Telegram Verification

Try these messages:

- `이 전략 약점과 리스크 분석해줘`
- `이 전략 개선해줘`
- `비슷한 전략 연구했어?`
- `전략 품질 점수 설명해줘`
- `백테스트 결과 보여줘`

Context isolation verification:

```text
사용자 전략:
20일 고가 돌파
종가 > MA20 > MA60
거래량 >= 20일 평균
손절 -5%
10일 저점 이탈 청산

이 전략 약점과 리스크 분석해줘
```

Expected behavior:

- weakness and improvement requests use `strategy_critique`
- memory requests use `research_memory_search`
- empty memory says no stored match
- fixture-backed results disclose `fixture_backed=true`
- unavailable metrics are not fabricated
- fixture/default fields such as `volume_multiplier`, `max_risk_pct`, and `regime_tags` are not presented as user strategy values
- missing quality scores return a Korean deterministic missing-data response

## Safety Notes

The research grounding hotfixes are read-only. They do not place orders, approve promotions, access private repositories, expose secrets, run shell or SQL, or alter trading adapters.
