"""Gaon capability registry - the single source of truth for what Gaon can
actually do right now.

Gaon must never guess at its own abilities. Every conversational path that
needs to know "can I do X?" asks this registry, and the LLM system prompt is
grounded in :func:`capability_prompt_summary` so a model cannot talk Gaon
into claiming an ability it does not have.

States (see :class:`CapabilityState`):

* ``AVAILABLE``           - implemented and usable now.
* ``UNAVAILABLE``         - not implemented yet (a future PR wires a provider).
* ``APPROVAL_REQUIRED``   - usable, but a human approval gate stands in front.
* ``FORBIDDEN``           - must never be performed from the conversational /
  agent layer; a deterministic safety boundary owns it.

A capability is *never* reported ``AVAILABLE`` unless it is genuinely wired.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# --- capability ids ---------------------------------------------------------
# Conversation / research (implemented today)
GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
RESEARCH_MISSION_READ = "RESEARCH_MISSION_READ"
RESEARCH_MISSION_RUN = "RESEARCH_MISSION_RUN"
STRATEGY_STATUS_READ = "STRATEGY_STATUS_READ"
MARKET_DATA_READ = "MARKET_DATA_READ"

# External read-only research tools (future - PR #217)
WEB_SEARCH = "WEB_SEARCH"
URL_FETCH = "URL_FETCH"
DOCUMENT_READ = "DOCUMENT_READ"

# Multimodal (future - PR #217)
IMAGE_VISION = "IMAGE_VISION"
VIDEO_METADATA = "VIDEO_METADATA"
VIDEO_TRANSCRIPT = "VIDEO_TRANSCRIPT"
VIDEO_FRAME_ANALYSIS = "VIDEO_FRAME_ANALYSIS"

# Evidence learning (future - PR #218)
EVIDENCE_INGEST = "EVIDENCE_INGEST"
EVIDENCE_VALIDATE = "EVIDENCE_VALIDATE"

# Developer agent (future - PR #216)
REPOSITORY_READ = "REPOSITORY_READ"
CODE_MODIFY_DEV = "CODE_MODIFY_DEV"
TEST_RUN = "TEST_RUN"
GIT_COMMIT = "GIT_COMMIT"
GIT_PUSH = "GIT_PUSH"
PULL_REQUEST_CREATE = "PULL_REQUEST_CREATE"

# Never allowed from this layer
PRODUCTION_DEPLOY = "PRODUCTION_DEPLOY"
MAIN_MERGE = "MAIN_MERGE"
PRODUCTION_DB_WRITE = "PRODUCTION_DB_WRITE"
SYSTEMD_CONTROL = "SYSTEMD_CONTROL"
ARBITRARY_SHELL = "ARBITRARY_SHELL"
TRADING_EXECUTION = "TRADING_EXECUTION"
LIVE_SWITCH = "LIVE_SWITCH"
CHAMPION_PROMOTION = "CHAMPION_PROMOTION"


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    APPROVAL_REQUIRED = "approval_required"
    FORBIDDEN = "forbidden"


class SafetyClass(str, Enum):
    READ_ONLY = "read_only"
    RESEARCH = "research"
    DEVELOPMENT = "development"
    PRIVILEGED = "privileged"


class CapabilityUnavailableError(RuntimeError):
    """Raised when code asks the registry to guarantee a capability that is
    not ``AVAILABLE``. Callers fail closed."""

    def __init__(self, capability_id: str) -> None:
        super().__init__(f"capability not available: {capability_id}")
        self.capability_id = capability_id


@dataclass(frozen=True)
class Capability:
    id: str
    state: CapabilityState
    read_only: bool
    requires_approval: bool
    safety_class: SafetyClass
    summary: str
    provider: str | None = None
    reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.state is CapabilityState.AVAILABLE


class CapabilityRegistry:
    """An immutable-after-construction lookup of :class:`Capability` records."""

    def __init__(self, capabilities: tuple[Capability, ...]) -> None:
        by_id: dict[str, Capability] = {}
        for capability in capabilities:
            if capability.id in by_id:
                raise ValueError(f"duplicate capability id: {capability.id}")
            by_id[capability.id] = capability
        self._by_id = by_id

    def get(self, capability_id: str) -> Capability | None:
        return self._by_id.get(capability_id)

    def state(self, capability_id: str) -> CapabilityState:
        capability = self._by_id.get(capability_id)
        # An unknown id is treated as UNAVAILABLE, never as AVAILABLE - a
        # typo must fail closed, not silently grant an ability.
        return capability.state if capability is not None else CapabilityState.UNAVAILABLE

    def is_available(self, capability_id: str) -> bool:
        return self.state(capability_id) is CapabilityState.AVAILABLE

    def require_available(self, capability_id: str) -> Capability:
        capability = self._by_id.get(capability_id)
        if capability is None or not capability.is_available:
            raise CapabilityUnavailableError(capability_id)
        return capability

    def all(self) -> tuple[Capability, ...]:
        return tuple(self._by_id.values())

    def by_state(self, state: CapabilityState) -> tuple[Capability, ...]:
        return tuple(c for c in self._by_id.values() if c.state is state)


def default_capability_registry() -> CapabilityRegistry:
    """The authoritative capability picture as of PR #214.

    Only ``GENERAL_CONVERSATION`` / mission & strategy reads / market-data
    reads are ``AVAILABLE``; running a research mission is
    ``APPROVAL_REQUIRED``; every external-web, multimodal, evidence and
    developer-agent capability is ``UNAVAILABLE`` (a later PR wires a real
    provider); production / trading / merge / shell capabilities are
    ``FORBIDDEN`` here and owned by their deterministic safety boundaries.
    """

    def cap(
        capability_id: str,
        state: CapabilityState,
        *,
        read_only: bool,
        requires_approval: bool,
        safety_class: SafetyClass,
        summary: str,
        provider: str | None = None,
        reason: str | None = None,
    ) -> Capability:
        return Capability(
            id=capability_id,
            state=state,
            read_only=read_only,
            requires_approval=requires_approval,
            safety_class=safety_class,
            summary=summary,
            provider=provider,
            reason=reason,
        )

    unavailable = CapabilityState.UNAVAILABLE
    return CapabilityRegistry(
        (
            cap(
                GENERAL_CONVERSATION,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Natural multi-turn conversation in Korean.",
                provider="assistant-provider (openai-compatible / deterministic fallback)",
            ),
            cap(
                RESEARCH_MISSION_READ,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Read the durable research mission, its candidates, progress and blockers.",
            ),
            cap(
                STRATEGY_STATUS_READ,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Read strategy version registry and champion / candidate status.",
            ),
            cap(
                MARKET_DATA_READ,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Read KRX / Yahoo real market data through the read-only research pipeline.",
                provider="krx_real_research / yahoo-chart",
            ),
            cap(
                RESEARCH_MISSION_RUN,
                CapabilityState.APPROVAL_REQUIRED,
                read_only=False,
                requires_approval=True,
                safety_class=SafetyClass.RESEARCH,
                summary="Run a research / validation cycle on an explicit request; promotion needs human approval.",
                reason="Explicit execution intent required; candidate promotion is human-gated.",
            ),
            cap(
                WEB_SEARCH,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Search the public web through a bounded live search provider.",
                provider="duckduckgo-html bounded search",
            ),
            cap(
                URL_FETCH,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Read HTML, text and PDF from allowlisted public HTTPS research sources (up to 5 MB).",
                provider="bounded allowlisted URL reader",
            ),
            cap(
                DOCUMENT_READ,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Read PDF, DOCX and text files staged in the authorized research input directory.",
                provider="bounded research document reader",
            ),
            cap(
                IMAGE_VISION,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Analyse bounded images, screenshots and charts with a dedicated vision model.",
                provider="Ollama qwen3-vl:4b",
            ),
            cap(
                VIDEO_METADATA,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Read bounded YouTube metadata without downloading the full video.",
                provider="yt-dlp + YouTube oEmbed metadata fallback",
            ),
            cap(
                VIDEO_TRANSCRIPT,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Retrieve bounded YouTube subtitles or automatic captions when available.",
                provider="yt-dlp caption metadata + HTTPS caption fetch; optional authorized cookie file",
            ),
            cap(
                VIDEO_FRAME_ANALYSIS,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.READ_ONLY,
                summary="Extract bounded YouTube frames with ffmpeg and analyse them with the vision model.",
                provider="yt-dlp + ffmpeg + qwen3-vl:4b; optional authorized cookie file",
            ),
            cap(
                EVIDENCE_INGEST,
                CapabilityState.AVAILABLE,
                read_only=False,
                requires_approval=False,
                safety_class=SafetyClass.RESEARCH,
                summary="Persist bounded external source text as provenance-tagged unvalidated research evidence.",
                provider="local append-only research evidence store",
            ),
            cap(
                EVIDENCE_VALIDATE,
                CapabilityState.AVAILABLE,
                read_only=False,
                requires_approval=False,
                safety_class=SafetyClass.RESEARCH,
                summary="Attach independent real-market or operational evidence to stored external research evidence.",
                provider="KRX/Yahoo research + Binance runtime evidence",
            ),
            cap(
                REPOSITORY_READ,
                CapabilityState.AVAILABLE,
                read_only=True,
                requires_approval=False,
                safety_class=SafetyClass.DEVELOPMENT,
                summary="Read allowlisted text files from Gaon's source repository.",
                provider="bounded repository reader",
            ),
            cap(
                CODE_MODIFY_DEV,
                CapabilityState.APPROVAL_REQUIRED,
                read_only=False,
                requires_approval=True,
                safety_class=SafetyClass.DEVELOPMENT,
                summary="Modify Gaon's code inside an isolated development worktree.",
                reason="Implemented only in isolated worktrees and requires a one-shot signed approval.",
            ),
            cap(
                TEST_RUN,
                CapabilityState.APPROVAL_REQUIRED,
                read_only=True,
                requires_approval=True,
                safety_class=SafetyClass.DEVELOPMENT,
                summary="Run the test suite inside an isolated development worktree.",
                reason="Implemented in an isolated worktree; write actions require a one-shot signed approval.",
            ),
            cap(
                GIT_COMMIT,
                CapabilityState.APPROVAL_REQUIRED,
                read_only=False,
                requires_approval=True,
                safety_class=SafetyClass.DEVELOPMENT,
                summary="Commit changes on a development branch.",
                reason="Implemented in an isolated worktree; write actions require a one-shot signed approval.",
            ),
            cap(
                GIT_PUSH,
                CapabilityState.APPROVAL_REQUIRED,
                read_only=False,
                requires_approval=True,
                safety_class=SafetyClass.DEVELOPMENT,
                summary="Push a development branch to the remote.",
                reason="Implemented in an isolated worktree; write actions require a one-shot signed approval.",
            ),
            cap(
                PULL_REQUEST_CREATE,
                CapabilityState.APPROVAL_REQUIRED,
                read_only=False,
                requires_approval=True,
                safety_class=SafetyClass.DEVELOPMENT,
                summary="Open a pull request for human review.",
                reason="PR creation is approval-gated; main merge remains forbidden and human-owned.",
            ),
            *(
                cap(
                    forbidden_id,
                    CapabilityState.FORBIDDEN,
                    read_only=False,
                    requires_approval=True,
                    safety_class=SafetyClass.PRIVILEGED,
                    summary=summary,
                    reason="Owned by a deterministic safety boundary; never performed from the conversational/agent layer.",
                )
                for forbidden_id, summary in (
                    (PRODUCTION_DEPLOY, "Deploy to production."),
                    (MAIN_MERGE, "Merge into the main branch."),
                    (PRODUCTION_DB_WRITE, "Mutate the production database."),
                    (SYSTEMD_CONTROL, "Control system services (systemctl / sudo)."),
                    (ARBITRARY_SHELL, "Execute arbitrary shell commands."),
                    (TRADING_EXECUTION, "Place real Binance / KIS orders."),
                    (LIVE_SWITCH, "Switch trading to LIVE mode."),
                    (CHAMPION_PROMOTION, "Promote a strategy to champion / ACTIVE."),
                )
            ),
        )
    )


def capability_prompt_summary(registry: CapabilityRegistry) -> str:
    """A compact, authoritative capability block for the LLM system prompt.

    Lists what Gaon *can* do and, explicitly, what it *cannot* do yet, so the
    model does not fabricate a URL read / image view / live data lookup or
    fall back to a generic apology. Never advertises an ``UNAVAILABLE`` or
    ``FORBIDDEN`` capability as usable.
    """
    can = [c.summary for c in registry.all() if c.state is CapabilityState.AVAILABLE]
    approval = [c.summary for c in registry.all() if c.state is CapabilityState.APPROVAL_REQUIRED]
    cannot_ids = (URL_FETCH, WEB_SEARCH, IMAGE_VISION, VIDEO_TRANSCRIPT, DOCUMENT_READ)
    cannot = [
        registry.get(cid).summary
        for cid in cannot_ids
        if registry.get(cid) is not None and not registry.is_available(cid)
    ]
    lines = [
        "Gaon capability status (authoritative - do not contradict, and do not claim anything outside this):",
        "CAN do now: " + " ".join(f"- {item}" for item in can),
    ]
    if approval:
        lines.append("CAN do with an explicit request and human approval: " + " ".join(f"- {item}" for item in approval))
    if cannot:
        lines.append(
            "CANNOT do yet (say so plainly and ask for the text instead; never pretend otherwise): "
            + " ".join(f"- {item}" for item in cannot)
        )
    lines.append(
        "Only claim a link/image/video/document was inspected when the corresponding tool actually returned evidence in this turn; never fabricate tool results."
    )
    return "\n".join(lines)
