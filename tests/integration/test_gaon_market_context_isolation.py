"""Acceptance tests for feature/gaon-market-context-and-strategy-rollback-contract.

Problem A: Web/Telegram Gaon must explicitly distinguish BINANCE_CRYPTO,
KR_STOCK, US_STOCK, and GLOBAL_STOCK, persist a request's market durably so
a generic follow-up ("계속 연구해줘") keeps it, and never let a different
market's ResearchMission/candidate/context be silently continued
(fail-closed on ambiguity).

Both Telegram (``TelegramConversationAgent``) and Web
(``GaonWebChatAdapter``) are exercised here against the exact same
``LLMConversationBrain.respond()`` path - see
``docs/architecture/GaonBinanceConversationDashboardIntegration.md`` - so a
policy proven for one transport is proven for both by construction; the
parity test below additionally proves it empirically.
"""

from __future__ import annotations

import unittest

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import extract_or_update_mission
from gaon.research.global_market import GaonMarketContext
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.gaon_market_context import read_market_context
from gaon.runtime.llm_conversation import LLMConversationRequest
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-14T00:00:00Z"
OWNER_CHAT_ID = "8767020479"
OWNER_WEB_REF = "the-owner-web-ref"


def _owner_config(**overrides) -> GaonRuntimeConfig:
    defaults = dict(
        telegram_allowed_chat_ids=(OWNER_CHAT_ID,),
        owner_ref="younghwa",
        owner_telegram_chat_ids=(OWNER_CHAT_ID,),
        owner_web_user_refs=(OWNER_WEB_REF,),
        assistant_enabled=True,
        assistant_provider="deterministic",
    )
    defaults.update(overrides)
    return GaonRuntimeConfig(**defaults)


def _no_owner_config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


def _telegram_update(update_id: int, text: str, *, chat_id: str) -> dict:
    return {
        "update_id": update_id,
        "message": {"message_id": update_id, "chat": {"id": int(chat_id)}, "from": {"id": int(chat_id) + 1}, "text": text},
    }


def _telegram_send(config: GaonRuntimeConfig, connection, text: str, *, chat_id: str = OWNER_CHAT_ID, update_id: int = 1) -> tuple[str, TelegramConversationAgent]:
    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(chat_id,))
    client = _FakeTelegramClient()
    process_update(parse_update_result(_telegram_update(update_id, text, chat_id=chat_id), received_at=NOW), runtime, client)
    return client.sent[-1][1], agent


def _web_send(config: GaonRuntimeConfig, connection, text: str, *, session_ref: str = "browser:abc", user_ref: str = OWNER_WEB_REF) -> tuple[dict, GaonWebChatAdapter]:
    adapter = GaonWebChatAdapter(config, connection)
    return adapter.handle(message=text, session_ref=session_ref, user_ref=user_ref, read_only=False, received_at=NOW), adapter


def _telegram_stored_context(connection, *, chat_id: str = OWNER_CHAT_ID):
    from gaon.runtime.llm_conversation import SQLiteConversationRepository

    repo = SQLiteConversationRepository(connection)
    session = repo.get_session(f"telegram:{chat_id}")
    return read_market_context(session.metadata)


def _web_stored_context(connection, *, session_ref: str = "browser:abc"):
    from gaon.runtime.llm_conversation import SQLiteConversationRepository

    repo = SQLiteConversationRepository(connection)
    session = repo.get_session(f"web:{session_ref}")
    return read_market_context(session.metadata)


class MarketContextResolverAcceptanceTests(unittest.TestCase):
    """Direct acceptance checks on the shared resolver required by Problem A."""

    def test_binance_terms_resolve_to_binance_crypto(self) -> None:
        from gaon.research.global_market import resolve_gaon_market_context

        for text in ("바이낸스 전략 연구해줘", "코인 시장 리서치 해줘", "암호화폐 리서치 해줘", "BTCUSDT 전략 연구해줘", "ETHUSDT 분석해줘"):
            with self.subTest(text=text):
                self.assertEqual(resolve_gaon_market_context(text), GaonMarketContext.BINANCE_CRYPTO)

    def test_kr_terms_resolve_to_kr_stock(self) -> None:
        from gaon.research.global_market import resolve_gaon_market_context

        for text in ("국내 주식 연구해줘", "코스피 전체를 연구해줘", "코스닥 상장 종목 분석해줘", "삼성전자 연구해줘"):
            with self.subTest(text=text):
                self.assertEqual(resolve_gaon_market_context(text), GaonMarketContext.KR_STOCK)

    def test_us_terms_resolve_to_us_stock(self) -> None:
        from gaon.research.global_market import resolve_gaon_market_context

        for text in ("미국 주식 연구해줘", "나스닥 전체를 연구해줘", "NYSE 상장 종목 알려줘", "AAPL 분석해줘"):
            with self.subTest(text=text):
                self.assertEqual(resolve_gaon_market_context(text), GaonMarketContext.US_STOCK)

    def test_global_terms_resolve_to_global_stock(self) -> None:
        from gaon.research.global_market import resolve_gaon_market_context

        self.assertEqual(resolve_gaon_market_context("전세계주식 전체를 연구해줘"), GaonMarketContext.GLOBAL_STOCK)
        self.assertEqual(resolve_gaon_market_context("한국과 미국 주식 전체를 비교 연구해줘"), GaonMarketContext.GLOBAL_STOCK)

    def test_ambiguous_mixed_market_signal_fails_closed_to_none(self) -> None:
        """A request naming signals for MORE THAN ONE market must never be
        guessed - the resolver returns None, matching the same
        never-guess contract ``resolve_market_scope`` already uses for an
        unrecognized market."""
        from gaon.research.global_market import resolve_gaon_market_context

        self.assertIsNone(resolve_gaon_market_context("국내에서 바이낸스 코인 연구해줘"))

    def test_no_market_named_resolves_to_none(self) -> None:
        from gaon.research.global_market import resolve_gaon_market_context

        for text in ("계속 연구해줘", "이 전략은 어때?", "안녕", ""):
            with self.subTest(text=text):
                self.assertIsNone(resolve_gaon_market_context(text))

    def test_domain_acronyms_do_not_false_positive_as_us_tickers(self) -> None:
        """OOS/MDD/candidate labels like "후보 A" are common vocabulary in
        this codebase's own KR research flow - none may be misread as a US
        ticker (regression coverage for the false positive found and fixed
        while building this resolver)."""
        from gaon.research.global_market import resolve_gaon_market_context

        for text in ("후보 A를 유지한 상태에서 OOS 검증해줘", "MDD와 KPI를 알려줘", "Out-of-Sample, Walk-Forward, Monte Carlo 검증까지 진행해주세요"):
            with self.subTest(text=text):
                self.assertIsNone(resolve_gaon_market_context(text))


class WebTelegramParityTests(unittest.TestCase):
    """Same input text must resolve/persist the identical market context
    through either transport, since both flow through the exact same
    LLMConversationBrain.respond()."""

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)

    def test_binance_request_persists_identically_on_both_transports(self) -> None:
        config = _no_owner_config()
        _telegram_send(config, self.store._connection, "바이낸스 코인 전략 연구해줘", chat_id="111")
        _web_send(config, self.store._connection, "바이낸스 코인 전략 연구해줘", session_ref="parity-web-1")

        telegram_context = _telegram_stored_context(self.store._connection, chat_id="111")
        web_context = _web_stored_context(self.store._connection, session_ref="parity-web-1")

        self.assertEqual(telegram_context, GaonMarketContext.BINANCE_CRYPTO)
        self.assertEqual(web_context, GaonMarketContext.BINANCE_CRYPTO)
        self.assertEqual(telegram_context, web_context)

    def test_kr_request_persists_identically_on_both_transports(self) -> None:
        config = _no_owner_config()
        _telegram_send(config, self.store._connection, "국내 주식 전체를 대상으로 연구해줘", chat_id="222")
        _web_send(config, self.store._connection, "국내 주식 전체를 대상으로 연구해줘", session_ref="parity-web-2")

        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="222"), GaonMarketContext.KR_STOCK)
        self.assertEqual(_web_stored_context(self.store._connection, session_ref="parity-web-2"), GaonMarketContext.KR_STOCK)


class MarketContextFollowUpPersistenceTests(unittest.TestCase):
    """A market explicitly named in one turn must survive a later generic
    follow-up ("계속 연구해줘") that names no market of its own."""

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)

    def test_kr_context_survives_generic_follow_up(self) -> None:
        config = _no_owner_config()
        _telegram_send(config, self.store._connection, "국내 주식 전체를 대상으로 연구해줘", chat_id="333", update_id=1)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="333"), GaonMarketContext.KR_STOCK)
        _telegram_send(config, self.store._connection, "계속 연구해줘", chat_id="333", update_id=2)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="333"), GaonMarketContext.KR_STOCK)

    def test_binance_context_survives_generic_follow_up(self) -> None:
        config = _no_owner_config()
        _telegram_send(config, self.store._connection, "바이낸스 코인 전략 연구해줘", chat_id="444", update_id=1)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="444"), GaonMarketContext.BINANCE_CRYPTO)
        _telegram_send(config, self.store._connection, "계속 연구해줘", chat_id="444", update_id=2)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="444"), GaonMarketContext.BINANCE_CRYPTO)

    def test_us_context_survives_generic_follow_up(self) -> None:
        config = _no_owner_config()
        _telegram_send(config, self.store._connection, "미국 나스닥 주식 전체를 연구해줘", chat_id="555", update_id=1)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="555"), GaonMarketContext.US_STOCK)
        _telegram_send(config, self.store._connection, "계속 연구해줘", chat_id="555", update_id=2)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id="555"), GaonMarketContext.US_STOCK)


class KrBinanceContaminationTests(unittest.TestCase):
    """A KR ResearchMission established in a chat must never be silently
    continued/answered for a later Binance-scoped turn in the SAME
    session, and the KR mission's own data must be left untouched."""

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)

    def test_binance_turn_after_kr_mission_does_not_reuse_kr_mission(self) -> None:
        config = _no_owner_config()
        chat_id = "666"
        _telegram_send(config, self.store._connection, "국내 주식 전체를 대상으로 단타 전략을 연구해줘", chat_id=chat_id, update_id=1)

        from gaon.runtime.llm_conversation import SQLiteConversationRepository

        repo = SQLiteConversationRepository(self.store._connection)
        session_id = f"telegram:{chat_id}"
        session_before = repo.get_session(session_id)
        kr_mission_before = session_before.metadata["conversation_mvp"]["research_mission"]
        self.assertEqual(kr_mission_before["market"], "KR")

        agent = TelegramConversationAgent(config, self.store._connection)
        request = LLMConversationRequest(
            session_id=session_id, user_ref=f"telegram-user:{chat_id}", source="telegram",
            text="바이낸스 코인 전략 계속 연구해줘", received_at=NOW, message_id=f"telegram:{chat_id}:binance-turn",
        )
        response = agent._brain.respond(request)

        # The KR mission itself must be byte-identical after the Binance
        # turn - this turn must never mutate/extend it (no candidate
        # cycle run against it), which is the concrete "ResearchMission/
        # candidate/context must never wrongly carry over" guarantee.
        session_after = repo.get_session(session_id)
        kr_mission_after = session_after.metadata["conversation_mvp"]["research_mission"]
        self.assertEqual(kr_mission_before, kr_mission_after)

        # No KR research tool ran for this Binance-scoped turn - the KR
        # mission-driven candidate cycle must never fire for it.
        self.assertEqual(response.tool_calls, ())

    def test_kr_turn_after_binance_context_does_not_inherit_binance_context(self) -> None:
        config = _no_owner_config()
        chat_id = "777"
        _telegram_send(config, self.store._connection, "바이낸스 코인 전략 연구해줘", chat_id=chat_id, update_id=1)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id=chat_id), GaonMarketContext.BINANCE_CRYPTO)

        _telegram_send(config, self.store._connection, "국내 코스피 전체를 대상으로 연구해줘", chat_id=chat_id, update_id=2)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id=chat_id), GaonMarketContext.KR_STOCK)

    def test_cross_transport_owner_kr_mission_not_returned_for_binance_request(self) -> None:
        """Same scenario as above, but across the durable OWNER-scoped
        lookup (Telegram establishes a KR mission; a later Web turn under
        the SAME configured owner, in a DIFFERENT session, asks about
        Binance) - is_mission_compatible_with_request's market_context
        guard must reject the KR mission as a continuation target."""
        config = _owner_config()
        _telegram_send(config, self.store._connection, "국내 주식 전체를 대상으로 단타 전략을 연구해줘", chat_id=OWNER_CHAT_ID, update_id=1)

        adapter = GaonWebChatAdapter(config, self.store._connection)
        request = LLMConversationRequest(
            session_id="web:fresh-browser-session", user_ref=f"web-user:{OWNER_WEB_REF}", source="web",
            text="바이낸스 코인 전략은 어때?", received_at=NOW, message_id="web:fresh-browser-session:binance-turn",
        )
        durable_mission, ambiguous = adapter._brain._resolve_durable_owner_mission(request)
        self.assertIsNone(durable_mission)
        self.assertFalse(ambiguous)


class UnsupportedMarketFreshResearchDoesNotCreateKrMissionTests(unittest.TestCase):
    """PR #225 closed cross-market CONTINUATION contamination, but
    ``extract_or_update_mission`` itself has no market-context awareness:
    a FRESH instruction (no existing mission) that names both an explicit
    non-KR market and a strategy family in the same turn (e.g. "미국 나스닥
    단타 전략 연구해줘") satisfies that function's verb+family research-
    intent signal on its own and would otherwise silently manufacture a
    brand-new ``market="KR"`` placeholder ResearchMission with an empty
    symbol set - never what was asked, and never something a later "계속
    연구해줘" should be able to inherit as if it were real KR research."""

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)

    def test_binance_family_request_does_not_create_kr_mission(self) -> None:
        config = _no_owner_config()
        chat_id = "1001"
        _telegram_send(config, self.store._connection, "바이낸스 단타 전략 연구해줘", chat_id=chat_id, update_id=1)

        from gaon.runtime.llm_conversation import SQLiteConversationRepository

        repo = SQLiteConversationRepository(self.store._connection)
        session = repo.get_session(f"telegram:{chat_id}")
        self.assertIsNone(session.metadata.get("conversation_mvp"))

    def test_us_family_request_does_not_create_kr_mission(self) -> None:
        config = _no_owner_config()
        chat_id = "1002"
        _telegram_send(config, self.store._connection, "미국 나스닥 단타 전략 연구해줘", chat_id=chat_id, update_id=1)

        from gaon.runtime.llm_conversation import SQLiteConversationRepository

        repo = SQLiteConversationRepository(self.store._connection)
        session = repo.get_session(f"telegram:{chat_id}")
        conversation_mvp = session.metadata.get("conversation_mvp")
        research_mission = (conversation_mvp or {}).get("research_mission")
        self.assertIsNone(research_mission)

    def test_kr_family_request_still_creates_kr_mission_unaffected(self) -> None:
        """Same verb+family signal, but with no non-KR market named (today's
        supported default) - unaffected by the new guard."""
        config = _no_owner_config()
        chat_id = "1003"
        _telegram_send(config, self.store._connection, "삼성전자 단타 전략 연구해줘", chat_id=chat_id, update_id=1)

        from gaon.runtime.llm_conversation import SQLiteConversationRepository

        repo = SQLiteConversationRepository(self.store._connection)
        session = repo.get_session(f"telegram:{chat_id}")
        research_mission = session.metadata["conversation_mvp"]["research_mission"]
        self.assertEqual(research_mission["market"], "KR")

    def test_binance_family_follow_up_does_not_inherit_a_kr_mission(self) -> None:
        """A generic follow-up after the suppressed Binance turn must not
        resume/see any KR mission either - none exists to resume."""
        config = _no_owner_config()
        chat_id = "1004"
        _telegram_send(config, self.store._connection, "바이낸스 단타 전략 연구해줘", chat_id=chat_id, update_id=1)
        reply, _agent = _telegram_send(config, self.store._connection, "계속 연구해줘", chat_id=chat_id, update_id=2)

        from gaon.runtime.llm_conversation import SQLiteConversationRepository

        repo = SQLiteConversationRepository(self.store._connection)
        session = repo.get_session(f"telegram:{chat_id}")
        conversation_mvp = session.metadata.get("conversation_mvp")
        research_mission = (conversation_mvp or {}).get("research_mission") if conversation_mvp else None
        self.assertIsNone(research_mission)


class AmbiguousNoContextFailClosedTests(unittest.TestCase):
    """A genuinely ambiguous request (signals for more than one market at
    once) must never be silently resolved to any one of them, and must
    never be stored as durable context."""

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)

    def test_mixed_market_signal_is_not_stored_as_any_market(self) -> None:
        config = _no_owner_config()
        chat_id = "888"
        _telegram_send(config, self.store._connection, "국내에서 바이낸스 코인 연구해줘", chat_id=chat_id, update_id=1)
        self.assertIsNone(_telegram_stored_context(self.store._connection, chat_id=chat_id))

    def test_mixed_market_signal_does_not_override_a_previously_stored_context(self) -> None:
        """Once a market IS durably established, a later merely-ambiguous
        turn must not clobber it with a guess (nor with nothing) - the
        stored context is left exactly as it was."""
        config = _no_owner_config()
        chat_id = "999"
        _telegram_send(config, self.store._connection, "바이낸스 코인 전략 연구해줘", chat_id=chat_id, update_id=1)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id=chat_id), GaonMarketContext.BINANCE_CRYPTO)
        _telegram_send(config, self.store._connection, "국내에서 바이낸스 코인 연구해줘", chat_id=chat_id, update_id=2)
        self.assertEqual(_telegram_stored_context(self.store._connection, chat_id=chat_id), GaonMarketContext.BINANCE_CRYPTO)


if __name__ == "__main__":
    unittest.main()
