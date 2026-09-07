"""Developer-agent capability boundary (foundation for PR #216).

This module draws the line the future safe developer agent must respect. It
adds *no* execution ability in PR #214 - it only names the two disjoint
sets so every other component can assert against them:

* :data:`DEVELOPER_AGENT_CAPABILITIES` - things a sandboxed developer agent
  may eventually do (inside an isolated worktree, ending at "open a PR").
* :data:`FORBIDDEN_IN_AGENT_LAYER` - things the conversational / research /
  developer agent layer must never do; a deterministic controller owns them.
"""

from __future__ import annotations

from gaon.runtime.gaon_agent.capabilities import (
    ARBITRARY_SHELL,
    CHAMPION_PROMOTION,
    CODE_MODIFY_DEV,
    GIT_COMMIT,
    GIT_PUSH,
    LIVE_SWITCH,
    MAIN_MERGE,
    PRODUCTION_DB_WRITE,
    PRODUCTION_DEPLOY,
    PULL_REQUEST_CREATE,
    REPOSITORY_READ,
    SYSTEMD_CONTROL,
    TEST_RUN,
    TRADING_EXECUTION,
)

DEVELOPER_AGENT_CAPABILITIES: frozenset[str] = frozenset(
    {
        REPOSITORY_READ,
        CODE_MODIFY_DEV,
        TEST_RUN,
        GIT_COMMIT,
        GIT_PUSH,
        PULL_REQUEST_CREATE,
    }
)

FORBIDDEN_IN_AGENT_LAYER: frozenset[str] = frozenset(
    {
        MAIN_MERGE,
        PRODUCTION_DEPLOY,
        PRODUCTION_DB_WRITE,
        SYSTEMD_CONTROL,
        ARBITRARY_SHELL,
        TRADING_EXECUTION,
        LIVE_SWITCH,
        CHAMPION_PROMOTION,
    }
)


class PrivilegedActionError(RuntimeError):
    """A privileged capability was requested from the agent layer."""

    def __init__(self, capability_id: str) -> None:
        super().__init__(
            f"{capability_id} is forbidden in the conversational/agent layer; "
            "a deterministic safety boundary owns it"
        )
        self.capability_id = capability_id


def assert_not_privileged(capability_id: str) -> None:
    """Fail closed if ``capability_id`` is one the agent layer must never run."""
    if capability_id in FORBIDDEN_IN_AGENT_LAYER:
        raise PrivilegedActionError(capability_id)
