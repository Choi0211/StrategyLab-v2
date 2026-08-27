# Cognitive Core / Unified Conversation v1 - Local Verification

Date: 2026-08-27. Environment: Windows, bundled Python 3.12.
Status: LOCAL VERIFICATION PASSED; not production acceptance or full capability completion.

## Repository boundaries

- StrategyLab base: bcdb0a0fba6c17f6a5c750e812a3249bcf074f3b.
- StrategyLab branch: feature/gaon-cognitive-core-unified-conversation-v1.
- Dashboard base: 596130dab26bae25ced497daff906d1a85c5d7dc.
- Dashboard branch: feature/gaon-unified-conversation-ui-v1.
- Dashboard local commit: bd33f12941738c20529cc996ade598f2b4555668.
- No push/PR/merge/deploy/service restart or production DB mutation.

## Verified

- Focused Cognitive/Web/conversation regression: 41 PASS.
- Full verify_release rerun: unit/integration/importability/required files PASS.
- Suite: 1,304 unit / 262 integration tests. The final message-provenance
  adjustment was additionally checked with 41 focused Cognitive/Web/conversation
  tests after the full run started; it did not receive another full-suite run.
- Cognitive and unified conversation deterministic release checks: PASS.
- deployment-import-path-check: PASS against this checkout's src/gaon.
- Existing web-chat, research-status, web-root, storage-status and canonical
  candidate-handoff release checks: PASS.
- Dashboard full suite: 20 PASS; py_compile and diff check PASS.
- StrategyLab git diff --check: PASS.
- Browser layout: 360x800, 390x844, 412x915, 1280x800 and 390x500 PASS for
  visible composer, send button, no horizontal overflow and long-message scroll.

The browser used an isolated static preview, so backend-disconnected rendering
was expected. It did not connect to trading services. Order logs in trading
tests are fake-client output. An existing unclosed log-file ResourceWarning
remains in Binance tests without failing assertions.

## Acceptance coverage

Implemented and exercised: feedback capture/retrieval/rendering across restart;
namespace isolation; proposed-only learning duplicate/conflict; goal persistence;
goal/planner scope; project dedupe; operational self-model scoping; proactive
proposal dedupe; additive v36-to-v37 migration preserving existing sessions;
worker-owned SQLite; health availability while chat busy; second chat rejected
without execution; bounded Binance snapshot; browser cookie continuity;
proxy errors and metadata; existing approval lifecycle unchanged.

Partial or pending: generic goal execution beyond canonical research; unified
access to every historical knowledge store; learning acquisition and trusted
claim promotion; broad proactive monitoring/cooldown; tool-need test planning;
cross-domain comparative risk analysis; new chat approval cards. These are not
represented as complete or validated production features.

## Files

StrategyLab new: cognitive/__init__.py, models.py, repository.py,
orchestrator.py, presentation.py, release_check.py; cognitive unit/Web integration
tests; architecture and this verification record.
Modified: README, CHANGELOG, ReleaseNotes, TestResults; runtime migrations, CLI,
conversation context, LLMConversationBrain, Web API; existing greeting route and
schema-version regression expectations.

Dashboard: dashboard.py, static/index.html, existing safety lifecycle tests,
new unified conversation tests, README and docs/UnifiedGaonConversationV1.md.
No trading engine, signal, sizing, protection or active settings modifications.

## Production acceptance / rollback

PENDING PRODUCTION VERIFICATION: actual Telegram/provider latency, physical
mobile keyboard, reverse-proxy cookie behavior and authenticated identity.
Schema v37 is additive; older v36 binaries require a pre-migration backup for
rollback. No data deletion or schema-version rewriting is a valid rollback.

UNRELATED PRODUCTION ISSUE: Binance final notional after quantity floor (-4164)
remains outside this feature. This project does not authorize orders or deployment.
