"""Patch 8.4 - KR multi-symbol data acquisition & quality diagnostics
acceptance test.

Reproduces the real production repeated-cycle scenario through the REAL
Telegram -> LLMConversationBrain -> multi_symbol_research stack (mocking
only the true external boundary - the market data provider, same
convention as tests/integration/test_strategy_centric_autonomous_research.py):

Cycle 1: a market-wide strategy candidate's breadth evaluation samples a
universe where most symbols have isolated zero-volume bars (must now be
research-eligible) and one symbol has a sustained zero-volume run reaching
the end of the requested period (must still be excluded, honestly labeled
stale_data).

Cycle 2 ("연구 계속해주세요"): the SAME strategy candidate and mission
scope continue (Patch 8.2/8.3 principle unchanged - symbols are evidence
samples, never the candidate's identity), and the symbol already confirmed
unusable in cycle 1 is not spent research budget on again.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import MissionUniverseScope, candidate_records
from gaon.research.krx_real_pipeline import KRXFixtureMarketDataProvider
from gaon.research.real_research import MarketBar, MarketSymbol
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import _config, _update, _RecordingTelegramClient, _baseline

_UNIVERSE: tuple[tuple[str, str], ...] = (
    ("005930", "KOSPI"),
    ("000660", "KOSPI"),
    ("005380", "KOSPI"),
    ("051910", "KOSPI"),
    ("105560", "KOSPI"),
    ("473050", "KOSDAQ"),
    ("068270", "KOSDAQ"),
    ("035720", "KOSDAQ"),
    ("086520", "KOSDAQ"),
    ("STALE01", "KOSDAQ"),  # the one tail-stale symbol
)


class _ZeroVolumeShapedProvider:
    """Fixture-backed, network-free stand-in that injects the exact
    zero-volume patterns a real production investigation confirmed:
    isolated scattered zero-volume bars for most symbols (must not
    exclude), a sustained tail-stale run for one symbol (must still
    exclude, as stale_data)."""

    source = "fixture:mission-test-universe"
    market_agnostic = True

    def __init__(self) -> None:
        self._fixture = KRXFixtureMarketDataProvider()

    @classmethod
    def from_env(cls, env=None):
        return cls()

    def fetch_universe(self, market):
        return tuple(MarketSymbol(code, code, "KR", exchange) for code, exchange in _UNIVERSE)

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily"):
        dataset = self._fixture.fetch_bars(symbol, start_date=start_date, end_date=end_date, timeframe=timeframe)
        bars = list(dataset.bars)
        if symbol.upper() == "STALE01":
            for index in range(max(0, len(bars) - 10), len(bars)):
                bar = bars[index]
                bars[index] = MarketBar(bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, 0, 0)
        else:
            for index in (5, 20):
                if index < len(bars):
                    bar = bars[index]
                    bars[index] = MarketBar(bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, 0, 0)
        from gaon.research.real_research import MarketDataset

        return MarketDataset(dataset.dataset_id, dataset.symbols, tuple(bars), dataset.metadata)

    def validate_dataset(self, dataset):
        return self._fixture.validate_dataset(dataset)


class KRMultiSymbolDataAcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str) -> str:
        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        received_at = f"2026-08-17T00:{update_id:02d}:00Z"
        with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline), patch(
            "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
            return_value={"state": "content_unavailable"},
        ), patch(
            "gaon.research.multi_symbol.build_market_data_provider_from_env",
            return_value=_ZeroVolumeShapedProvider(),
        ):
            result = process_update(
                parse_update_result(_update(update_id, update_id, text), received_at=received_at),
                self.runtime,
                self.client,
            )
        self.assertEqual(result.status, "sent", f"turn {update_id} failed: {result}")
        return self.client.sent[-1][1]

    def _mission(self):
        return self.agent._brain._mission_for("telegram:100")

    def test_isolated_zero_volume_symbols_become_eligible_and_stale_symbol_is_excluded(self) -> None:
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        turn2 = self._send(2, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()
        candidate = candidate_records(mission)[0]
        # Real production defect this proves fixed: isolated zero-volume
        # bars no longer wipe out almost the entire universe.
        self.assertGreater(candidate.valid_symbols, 0)
        self.assertIn("stale_data", turn2)
        fingerprint_after_cycle_1 = candidate.strategy_fingerprint

        # Patch 8.2/8.3 principle unchanged by this patch: the SAME
        # strategy candidate (same fingerprint) and the SAME market-wide
        # mission scope continue across the continuation turn - symbols
        # remain evidence samples, never the candidate's identity.
        self._send(3, "연구 계속해주세요")
        mission_after = self._mission()
        candidate_after = candidate_records(mission_after)[0]
        self.assertEqual(mission_after.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertEqual(candidate_after.candidate_id, candidate.candidate_id)
        self.assertEqual(candidate_after.strategy_fingerprint, fingerprint_after_cycle_1)

    def test_breadth_cycle_passes_previously_excluded_symbols_as_avoid_list(self) -> None:
        # Direct wiring check (Section 6 bounded-avoidance requirement):
        # once a candidate has confirmed-excluded symbols tracked, the next
        # breadth cycle's multi_symbol_research call must carry them as
        # avoid_symbols - verified by calling the real conversation brain's
        # breadth-cycle path with a candidate that already has
        # excluded_symbols populated, rather than relying on a second
        # adaptive round happening to be needed (with only 10 fixture
        # symbols, cycle 1 alone already reaches sufficient evidence, which
        # is itself evidence the fix works - see the test above).
        self._send(1, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
        self._send(2, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()
        candidate = candidate_records(mission)[0]
        self.assertIn("STALE01", candidate.excluded_symbols)

        request = self.agent._brain
        from gaon.runtime.llm_conversation import LLMConversationRequest

        req = LLMConversationRequest(
            session_id="telegram:100", user_ref="user:release-check", source="telegram",
            text="probe", received_at="2026-08-17T00:05:00Z", message_id="probe:1",
        )
        with patch(
            "gaon.research.multi_symbol.build_market_data_provider_from_env",
            return_value=_ZeroVolumeShapedProvider(),
        ):
            result = request._execute_mvp_multi_symbol_research(
                req, (), "국내 주식 코스피 코스닥 전체를 대상으로 단타 전략을 연구해줘 (probe:cycle:99)", None, None,
                candidate_spec=candidate.spec_rules, avoid_symbols=candidate.excluded_symbols,
            )
        self.assertEqual(result.status, "success")
        audits = self.store.tool_audit.list(tool_name="multi_symbol_research")
        probed_args = audits[-1].request["arguments"]
        self.assertIn("avoid_symbols", probed_args)
        self.assertIn("STALE01", probed_args["avoid_symbols"])


if __name__ == "__main__":
    unittest.main()
