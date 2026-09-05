"""Regression tests for fix/cross-transport-owner-research-mission.

Root cause (confirmed against production, read-only, before this branch):
ResearchMission is persisted per session_id in conversation_sessions.
metadata_json - telegram:{chat_id} vs web:{session_ref} are DIFFERENT
namespaces even for the identical human, so Telegram and Web could never
see each other's durable mission even though they share the exact same
SQLite file. Web, finding no local mission, then interpreted a bare
continuation phrase ("단타 연구 계속해줘") as license to manufacture a
brand-new, empty KR/single_symbol/short_term_daytrade placeholder mission
out of nowhere.

This suite runs Telegram and Web against a SINGLE SHARED
RuntimeStateStore/sqlite connection (the real production topology - every
other test file in this repo uses two SEPARATE stores, which is exactly
why this defect was never caught) with an explicit owner_ref mapping
configured (GaonRuntimeConfig.owner_ref/owner_telegram_chat_ids/
owner_web_user_refs) - the opt-in, config-only mechanism this fix adds.
No cross-transport sharing happens unless this mapping is explicitly
configured.
"""

from __future__ import annotations

import json
import unittest

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import extract_or_update_mission
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationRequest, LLMConversationSession, SQLiteConversationRepository
from gaon.runtime.research_grounding import is_strict_real_research_tool
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-05T00:00:00Z"
OWNER_CHAT_ID = "8767020479"
OWNER_WEB_REF = "the-owner-web-ref"

_STRICT_TOOLS = ("krx_real_research", "autonomous_research_cycle", "autonomous_learning_research", "research_retest", "multi_symbol_research")


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


def _strict_tool_call_counts(store: RuntimeStateStore) -> dict[str, int]:
    return {name: len(store.tool_audit.list(tool_name=name)) for name in _STRICT_TOOLS}


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


def _telegram_update(update_id: int, text: str, *, chat_id: str, user_id: str | None = None) -> dict:
    # Independent-review fix (Issue 1): chat_id (the CONVERSATION the
    # message arrived in - TelegramConversationAgent's session_id) and
    # user_id (the SENDER - TelegramConversationAgent's user_ref) are
    # deliberately DIFFERENT by default here (user_id defaults to a value
    # distinct from chat_id, never silently equal) so that a test using
    # the default never hides a chat_id/user_id identity mismatch the way
    # the original chat.id == from.id helper did.
    resolved_user_id = user_id if user_id is not None else f"{chat_id}9"
    return {
        "update_id": update_id,
        "message": {"message_id": update_id, "chat": {"id": int(chat_id)}, "from": {"id": int(resolved_user_id)}, "text": text},
    }


def _telegram_send(config: GaonRuntimeConfig, connection, text: str, *, chat_id: str = OWNER_CHAT_ID, user_id: str | None = None, update_id: int = 1, received_at: str = NOW) -> tuple[str, TelegramConversationAgent]:
    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(chat_id,))
    client = _FakeTelegramClient()
    process_update(parse_update_result(_telegram_update(update_id, text, chat_id=chat_id, user_id=user_id), received_at=received_at), runtime, client)
    return client.sent[-1][1], agent


def _web_send(config: GaonRuntimeConfig, connection, text: str, *, session_ref: str = "browser:abc", user_ref: str = OWNER_WEB_REF, received_at: str = NOW) -> dict:
    adapter = GaonWebChatAdapter(config, connection)
    return adapter.handle(message=text, session_ref=session_ref, user_ref=user_ref, read_only=False, received_at=received_at)


def _seed_telegram_market_wide_daytrade_mission(config: GaonRuntimeConfig, connection, *, chat_id: str = OWNER_CHAT_ID) -> tuple[TelegramConversationAgent, "ResearchMission"]:
    """Seeds a real, already-persisted KR/market-wide/short_term_daytrade
    mission with 10 real candidates under a Telegram session - reproducing
    the exact confirmed production state (KR-ST-001..010)."""
    from gaon.knowledge.research_mission import add_candidate, next_candidate_sequence
    from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, new_candidate

    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
    for index in range(10):
        template = ALL_STRATEGY_FAMILY_TEMPLATES[index % len(ALL_STRATEGY_FAMILY_TEMPLATES)]
        candidate = new_candidate(template.family, sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(chat_id,))
    client = _FakeTelegramClient()
    process_update(parse_update_result(_telegram_update(0, "안녕하세요", chat_id=chat_id), received_at=NOW), runtime, client)
    agent._brain._remember_mission(
        LLMConversationRequest(session_id=f"telegram:{chat_id}", user_ref=f"telegram-user:{chat_id}", source="telegram", text="x", received_at=NOW),
        mission,
    )
    return agent, mission


def _seed_web_mission(config: GaonRuntimeConfig, connection, mission, *, session_ref: str, user_ref: str) -> None:
    adapter = GaonWebChatAdapter(config, connection)
    adapter.handle(message="안녕하세요", session_ref=session_ref, user_ref=user_ref, read_only=False, received_at=NOW)
    adapter._brain._remember_mission(
        LLMConversationRequest(session_id=f"web:{session_ref}", user_ref=f"web-user:{user_ref}", source="web", text="x", received_at=NOW),
        mission,
    )


def _inject_unrelated_noise_sessions(connection, count: int, *, updated_at: str) -> None:
    """Directly inserts `count` unrelated conversation_sessions rows (no
    owner mission, no owner identity) all stamped with `updated_at` - used
    to reproduce the confirmed production condition where diagnostic/CLI/
    browser/binance-dashboard session volume vastly outnumbers, and is more
    recently updated than, the real owner's durable mission session. A
    LIMIT-based global scan ordered by updated_at DESC would push the real
    owner mission out of its window; an owner-identity-first SQL filter
    must not be affected by this volume at all."""
    repository = SQLiteConversationRepository(connection)
    sources = ("web", "cli", "diagnostic")
    for index in range(count):
        source = sources[index % len(sources)]
        session_id = f"{source}:noise-{index}" if source != "web" else f"web:browser:noise-{index}"
        repository.upsert_session(
            LLMConversationSession(
                session_id=session_id,
                user_ref=f"web-user:noise-{index}" if source == "web" else f"{source}-user:noise-{index}",
                source=source,
                status="active",
                created_at=updated_at,
                updated_at=updated_at,
                metadata={},
            )
        )


def _authoritative_mission_id(connection, session_id: str) -> str | None:
    """Precise dict-key inspection of the ONE authoritative mission field
    (conversation_mvp.research_mission.mission_id) for a session - never a
    LIKE-substring scan, which can also match unrelated session-local data
    such as ConversationalMVPContext's own JSON payload."""
    row = connection.execute("SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    metadata = json.loads(row[0])
    root = metadata.get("conversation_mvp")
    if not isinstance(root, dict):
        return None
    raw_mission = root.get("research_mission")
    if not isinstance(raw_mission, dict):
        return None
    return raw_mission.get("mission_id")


def _sessions_with_authoritative_mission(connection, mission_id: str) -> list[str]:
    """DB-wide scan (every session_id) using the same precise dict-key
    inspection, to prove exactly one session holds the authoritative copy
    of a given mission_id."""
    rows = connection.execute("SELECT session_id FROM conversation_sessions").fetchall()
    return [session_id for (session_id,) in rows if _authoritative_mission_id(connection, session_id) == mission_id]


class TelegramSeedWebReadTests(unittest.TestCase):
    """Requirement 1: Telegram seeds a market-wide short_term_daytrade
    mission + candidates; Web reads the SAME mission/candidate state,
    zero research tool calls."""

    def test_web_reads_the_same_telegram_mission_and_candidates(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _agent, mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            payload = _web_send(config, store._connection, "단타 연구 잘되고 있어?")
            self.assertEqual(payload["route"], "conversation_mission_status_read")
            for candidate in mission.candidates:
                self.assertIn(candidate["candidate_id"], payload["text"])
            self.assertEqual(payload["tool_calls"], [])
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()


class TelegramSeedWebExplicitContinuationTests(unittest.TestCase):
    """Requirement 2: Telegram mission; Web's EXPLICIT "단타 연구
    계속해줘" continues the SAME mission through the existing explicit-
    execution gate - not a new placeholder."""

    def test_web_explicit_continuation_continues_the_same_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _agent, mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            payload = _web_send(config, store._connection, "단타 연구 계속해줘")
            self.assertEqual(payload["tool_calls"], ["multi_symbol_research"])
            # Single source of truth: Web's own session must never fork a
            # duplicate authoritative copy of the mission.
            web_session = store._connection.execute(
                "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", ("web:browser:abc",)
            ).fetchone()
            import json as _json

            web_metadata = _json.loads(web_session[0])
            self.assertNotIn("research_mission", web_metadata.get("conversation_mvp", {}))
            telegram_session = store._connection.execute(
                "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", (f"telegram:{OWNER_CHAT_ID}",)
            ).fetchone()
            telegram_metadata = _json.loads(telegram_session[0])
            self.assertEqual(
                telegram_metadata["conversation_mvp"]["research_mission"]["mission_id"],
                mission.mission_id,
            )
        finally:
            store.close()


class WebSeedTelegramReadTests(unittest.TestCase):
    """Requirement 3: reverse direction - Web creates/progresses a
    mission, Telegram reads the SAME durable mission."""

    def test_telegram_reads_the_same_web_created_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
            _seed_web_mission(config, store._connection, mission, session_ref="browser:abc", user_ref=OWNER_WEB_REF)
            reply, _agent = _telegram_send(config, store._connection, "단타 연구 잘되고 있어?")
            self.assertIn("KOSPI", reply)
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()


class CrossSessionSubjectIsolationTests(unittest.TestCase):
    """Requirements 4 & 5: last_read_subject / pronoun context must NEVER
    cross sessions, even when a durable ResearchMission is shared. A
    candidate selected in one transport's session must not let "그거
    다시 연구해줘" in a brand-new session on the OTHER transport
    auto-execute against it."""

    def test_telegram_selected_candidate_does_not_leak_into_a_new_web_session(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            agent, mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            first_candidate_id = mission.candidates[0]["candidate_id"]
            # Telegram reads/selects a specific candidate by id (sets its
            # OWN session-local last_read_subject).
            _telegram_send(config, store._connection, f"{first_candidate_id} 설명해주세요", update_id=1)
            # A brand-new Web session (same owner) asks the ambiguous
            # pronoun form - must fail-closed, never resolve to the
            # Telegram session's selected candidate.
            payload = _web_send(config, store._connection, "그거 다시 연구해줘", session_ref="browser:new")
            self.assertEqual(payload["route"], "conversation_research_subject_unresolved")
            self.assertEqual(payload["tool_calls"], [])
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()

    def test_web_selected_candidate_does_not_leak_into_a_new_telegram_session(self) -> None:
        # A "new Telegram session" for the SAME owner means a different
        # chat_id also declared under owner_telegram_chat_ids (Telegram
        # has no browser-session equivalent - session identity IS the
        # chat_id) - this is the genuine cross-session case, distinct from
        # the SAME chat_id naturally continuing its own already-active
        # candidate (which is pre-existing, correct, unrelated behavior).
        SECOND_CHAT_ID = "8767020480"
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config(telegram_allowed_chat_ids=(OWNER_CHAT_ID, SECOND_CHAT_ID), owner_telegram_chat_ids=(OWNER_CHAT_ID, SECOND_CHAT_ID))
            _agent, mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            first_candidate_id = mission.candidates[0]["candidate_id"]
            _web_send(config, store._connection, f"{first_candidate_id} 설명해주세요", session_ref="browser:abc")
            reply, _agent2 = _telegram_send(config, store._connection, "그거 다시 연구해줘", chat_id=SECOND_CHAT_ID, update_id=1)
            self.assertIn("명확하지 않아", reply)
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()


class CrossOwnerIsolationTests(unittest.TestCase):
    """Requirement 6: two different configured owners must never see each
    other's missions."""

    def test_owner_b_never_reads_owner_a_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = GaonRuntimeConfig(
                telegram_allowed_chat_ids=("111", "222"),
                owner_ref="ownerA",
                owner_telegram_chat_ids=("111",),
                owner_web_user_refs=("web-A",),
                assistant_enabled=True,
                assistant_provider="deterministic",
            )
            _agent, _mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection, chat_id="111")
            # chat 222 is allowed to talk to the bot at all, but is NOT
            # declared as owner "ownerA" - must never see ownerA's mission.
            reply, _agent2 = _telegram_send(config, store._connection, "단타 연구 잘되고 있어?", chat_id="222", update_id=1)
            self.assertNotIn("KOSPI", reply)
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()

    def test_undeclared_web_user_ref_never_reads_the_owner_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _agent, _mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            payload = _web_send(config, store._connection, "단타 연구 잘되고 있어?", user_ref="some-unrelated-random-uuid")
            self.assertNotIn("KOSPI", payload["text"])
            self.assertEqual(payload["route"], "conversation_research_status_no_mission")
        finally:
            store.close()


class TelegramChatIdVsUserIdIdentityTests(unittest.TestCase):
    """Independent-review Issue 1: TelegramConversationAgent sets
    session_id=f"telegram:{message.conversation_id}" (the CHAT) and
    user_ref=f"telegram-user:{message.user_id}" (the SENDER) as two
    SEPARATE fields. owner_telegram_chat_ids is validated as a subset of
    telegram_allowed_chat_ids - the existing CHAT-level access allowlist -
    so owner membership must be judged by chat_id, never by whichever
    user happens to send the message. A test helper that always sets
    chat.id == from.id (as this file's own helpers originally did) hides
    this exact class of bug."""

    def test_configured_chat_id_resolves_as_owner_even_with_a_different_sender_user_id(self) -> None:
        # chat_id="111" IS declared as the owner's chat; the SENDER's own
        # user_id ("999") is unrelated and different - this must still
        # resolve to the configured owner.
        store = RuntimeStateStore(":memory:")
        try:
            config = GaonRuntimeConfig(
                telegram_allowed_chat_ids=("111",),
                owner_ref="ownerA",
                owner_telegram_chat_ids=("111",),
                owner_web_user_refs=("web-A",),
                assistant_enabled=True,
                assistant_provider="deterministic",
            )
            _agent, _mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection, chat_id="111")
            reply, _agent2 = _telegram_send(config, store._connection, "단타 연구 잘되고 있어?", chat_id="111", user_id="999", update_id=1)
            self.assertIn("KOSPI", reply)
        finally:
            store.close()

    def test_undeclared_chat_id_is_never_treated_as_owner_even_if_sender_user_id_coincides_with_a_configured_chat_id(self) -> None:
        # chat_id="222" is allowed to talk to the bot but is NOT declared
        # as the owner's chat. The sender's user_id ("111") happens to
        # equal a DIFFERENT, actually-configured owner chat_id purely by
        # coincidence - this must NEVER be treated as owner membership.
        store = RuntimeStateStore(":memory:")
        try:
            config = GaonRuntimeConfig(
                telegram_allowed_chat_ids=("111", "222"),
                owner_ref="ownerA",
                owner_telegram_chat_ids=("111",),
                owner_web_user_refs=("web-A",),
                assistant_enabled=True,
                assistant_provider="deterministic",
            )
            _agent, _mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection, chat_id="111")
            reply, _agent2 = _telegram_send(config, store._connection, "단타 연구 잘되고 있어?", chat_id="222", user_id="111", update_id=1)
            self.assertNotIn("KOSPI", reply)
        finally:
            store.close()


class DiagnosticSessionExclusionTests(unittest.TestCase):
    """Requirement 7: diagnostic/CLI/release-check sessions must never be
    treated as the operator's own durable mission (they resolve to no
    configured owner at all, so they are simply invisible to the scan's
    owner-match filter and never seeded as mission sources here)."""

    def test_release_check_style_session_is_never_used_as_a_durable_mission_source(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
            # A diagnostic-style session using an UNDECLARED user_ref, even
            # though it is source="web" like the real owner.
            _seed_web_mission(config, store._connection, mission, session_ref="release-check", user_ref="release-check-user")
            payload = _web_send(config, store._connection, "단타 연구 잘되고 있어?", session_ref="browser:real-owner")
            self.assertEqual(payload["route"], "conversation_research_status_no_mission")
        finally:
            store.close()


class MissionCompatibilityTests(unittest.TestCase):
    """Requirements 8 & 9: same owner, two different-domain missions - only
    the compatible one is selected when the request names a scope;
    ambiguous (no scope signal, multiple compatible) fails closed."""

    def test_compatible_domain_mission_is_selected_over_an_incompatible_one(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config(owner_web_user_refs=("web-ref-1", "web-ref-2"))
            daytrade_mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
            swing_mission = extract_or_update_mission("국내 주식 전체를 대상으로 스윙 전략을 연구해주세요", existing=None, now=NOW)
            _seed_web_mission(config, store._connection, daytrade_mission, session_ref="s1", user_ref="web-ref-1")
            _seed_web_mission(config, store._connection, swing_mission, session_ref="s2", user_ref="web-ref-2")
            reply, _agent = _telegram_send(config, store._connection, "단타 연구 잘되고 있어?", update_id=1)
            self.assertIn("단타", reply)
            self.assertNotIn("스윙", reply)
        finally:
            store.close()

    def test_ambiguous_multiple_compatible_missions_fail_closed_to_clarification(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config(owner_web_user_refs=("web-ref-1", "web-ref-2"))
            m1 = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
            m2 = extract_or_update_mission("국내 주식 전체를 대상으로 스윙 전략을 연구해주세요", existing=None, now=NOW)
            _seed_web_mission(config, store._connection, m1, session_ref="s1", user_ref="web-ref-1")
            _seed_web_mission(config, store._connection, m2, session_ref="s2", user_ref="web-ref-2")
            # No scope signal at all - ambiguous between the two missions.
            reply, _agent = _telegram_send(config, store._connection, "연구 잘되고 있어?", update_id=1)
            self.assertIn("명확하지 않습니다", reply)
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()


class NoPlaceholderMissionTests(unittest.TestCase):
    """Requirements 10 & 11: with truly no mission anywhere, a bare
    continuation phrase must fail closed instead of manufacturing an
    empty placeholder - but an explicit new-scope request still creates a
    mission normally."""

    def test_no_mission_anywhere_plus_continuation_never_creates_a_placeholder(self) -> None:
        # The user-facing text for this exact turn is unaffected by this
        # hotfix - it is the SAME pre-existing, honest legacy "no context,
        # name a target" fallback (conversation_autonomous_learning_
        # missing_target) production already showed for this turn. What
        # this hotfix actually fixes is the SILENT SIDE EFFECT: before
        # this fix, a placeholder ResearchMission was created and
        # persisted in the background regardless of what was said,
        # poisoning the NEXT turn's mission read - that persistence is
        # what this test verifies is now suppressed.
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            payload = _web_send(config, store._connection, "단타 연구 계속해줘")
            self.assertEqual(payload["tool_calls"], [])
            mission_raw = store._connection.execute(
                "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", ("web:browser:abc",)
            ).fetchone()
            import json as _json

            metadata = _json.loads(mission_raw[0]) if mission_raw else {}
            self.assertNotIn("research_mission", metadata.get("conversation_mvp", {}))
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
        finally:
            store.close()

    def test_explicit_new_scope_still_creates_a_mission_normally(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _web_send(config, store._connection, "국내 주식 전체를 대상으로 단타 전략을 연구해주세요")
            mission_raw = store._connection.execute(
                "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", ("web:browser:abc",)
            ).fetchone()
            import json as _json

            metadata = _json.loads(mission_raw[0]) if mission_raw else {}
            self.assertIn("research_mission", metadata.get("conversation_mvp", {}))
        finally:
            store.close()


class NoOwnerConfiguredRegressionTests(unittest.TestCase):
    """Baseline preservation: with no owner_ref configured at all (the
    default), behavior is byte-for-byte the same as before this hotfix -
    no cross-transport sharing happens."""

    def test_no_owner_configured_web_still_sees_no_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _no_owner_config()
            _agent, _mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            payload = _web_send(config, store._connection, "단타 연구 잘되고 있어?", user_ref="anything")
            self.assertEqual(payload["route"], "conversation_research_status_no_mission")
        finally:
            store.close()


class LargeUnrelatedSessionVolumeTests(unittest.TestCase):
    """Independent-review fix (Issue 2): the durable owner mission lookup
    must resolve correctly by OWNER IDENTITY, never by "most recently
    updated N sessions" - reproduced with hundreds of unrelated, more
    recently updated noise sessions (diagnostic/CLI/browser/binance-
    dashboard volume) that a LIMIT-based global scan would let crowd the
    real owner mission out of its window."""

    def _run_with_noise(self, noise_count: int) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _agent, mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            # All noise sessions are stamped strictly LATER than the owner's
            # Telegram session, so a naive "ORDER BY updated_at DESC LIMIT N"
            # scan would rank every one of them ahead of the real owner
            # mission once noise_count exceeds that limit.
            _inject_unrelated_noise_sessions(store._connection, noise_count, updated_at="2026-09-06T00:00:00Z")

            # Test A: a pure status-read from the owner's Web identity must
            # still find the Telegram-owned mission, with zero tool calls.
            payload = _web_send(config, store._connection, "단타 연구 잘되고 있어?")
            self.assertEqual(payload["route"], "conversation_mission_status_read")
            self.assertEqual(payload["tool_calls"], [])
            for candidate in mission.candidates:
                self.assertIn(candidate["candidate_id"], payload["text"])
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})

            # Test B: an EXPLICIT continuation must still resolve to, and
            # update, the SAME authoritative Telegram-owning row - not a
            # new/duplicate mission in Web's own session.
            payload = _web_send(config, store._connection, "단타 연구 계속해줘")
            self.assertEqual(payload["tool_calls"], ["multi_symbol_research"])

            web_mission_id = _authoritative_mission_id(store._connection, "web:browser:abc")
            self.assertIsNone(web_mission_id, "Web's own session must never hold a duplicate authoritative mission copy")

            telegram_mission_id = _authoritative_mission_id(store._connection, f"telegram:{OWNER_CHAT_ID}")
            self.assertEqual(telegram_mission_id, mission.mission_id)

            # Single source of truth, DB-wide: exactly one session row (out
            # of noise_count + 2) may hold this mission_id.
            owners = _sessions_with_authoritative_mission(store._connection, mission.mission_id)
            self.assertEqual(owners, [f"telegram:{OWNER_CHAT_ID}"])
        finally:
            store.close()

    def test_correct_with_200_unrelated_more_recently_updated_sessions(self) -> None:
        self._run_with_noise(200)

    def test_correct_with_500_unrelated_more_recently_updated_sessions(self) -> None:
        self._run_with_noise(500)


if __name__ == "__main__":
    unittest.main()
