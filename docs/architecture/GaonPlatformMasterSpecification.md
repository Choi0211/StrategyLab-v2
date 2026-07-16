# Gaon Platform Master Development Specification

Project: Gaon Platform  
Version: 1.0  
Status: APPROVED  
Product Owner: Choi Youngha  
Chief AI Architect: ChatGPT  
AI Research Director: Gaon  

## 1. Project Vision

This project is not primarily an automated trading program.

The purpose of this project is to develop Youngha's AI Engineering Partner, Gaon.

Gaon is an AI partner that researches, develops, learns, and remembers project context together with the user.

StrategyLab is one research lab operated by Gaon.

## 2. Long-Term Vision

```text
Youngha
  -> Gaon
  -> StrategyLab
  -> MyMoneyGuard
  -> Production Trading
```

Future Gaon Platform structure:

```text
Gaon
  -> StrategyLab
  -> PluginLab
  -> AudioLab
  -> DevLab
  -> LearningLab
  -> Memory
```

StrategyLab is the first project inside the Gaon Platform.

## 3. Current Scope

The current development scope is StrategyLab only.

Out of scope until StrategyLab and the Gaon foundation are complete:

- PluginLab
- JUCE
- Unreal
- Wwise
- Other unrelated programs

These items must not be added to the active StrategyLab sprint scope.

## 4. Development Philosophy

```text
Question
  -> Research
  -> Evidence
  -> Validation
  -> Approval
  -> Production
```

Gaon does not guess. Gaon presents evidence and must pass validation.

## 5. Constitution

Gaon is not a yes-man.

Gaon must:

- suggest a different direction when necessary
- say "unknown" when evidence is insufficient
- investigate together with the user
- research together with the user
- develop together with the user
- learn together with the user

## 6. Repository Rules

Public repositories must never contain:

- secrets
- live trading code
- KIS API credentials or calls
- real broker execution
- account data
- tokens
- private operational state

Private repositories and systems own:

- live trading
- APIs
- accounts
- orders
- tokens
- MyMoneyGuard runtime state

## 7. V1 Compatibility

Existing MyMoneyGuard V1 must not be modified or redeveloped inside StrategyLab-v2.

StrategyLab may define adapter contracts only.

Reusable V1 capability targets:

- Backtest
- Optimizer
- WalkForward
- MonteCarlo
- Trading Engine

## 8. StrategyLab Sprint Plan

Sprint 11: Research Brain

- Research Goal
- Research Planner
- Research Session
- Research Interview
- Research Journal
- Memory Foundation

Sprint 12: Learning Memory and Evidence

- Learning Memory
- Knowledge
- Evidence
- Citation
- Duplicate Detection
- Research History

Sprint 13: Strategy Generator

- Hypothesis
- Experiment Queue
- Parameter Space
- Seed
- Deterministic generation

Sprint 14: V1 Adapter Contract

- BacktestPort
- OptimizerPort
- WalkForwardPort
- MonteCarloPort
- Golden Fixture
- Mock Adapter
- Version Check

Sprint 15: Validation

- Champion League
- Walk Forward
- Monte Carlo
- Overfitting checks
- Rejected, Champion, and Retired states

Sprint 16: AI Provider

- OpenAI
- Local LLM
- Knowledge Search
- Citation
- Hallucination Guard

Sprint 17: Telegram Research Interface

- Conversation
- Research Request
- Research Status
- Research Report
- No trading

Sprint 18: Dashboard

- Research Dashboard
- Experiment Dashboard
- Notion Sync
- Research Journal

Sprint 19: Research Loop

```text
Research
  -> Knowledge
  -> Strategy
  -> Experiment
  -> Validation
  -> Learning Memory
  -> Next Research
```

Sprint 20: Release Candidate

- Shadow Mode
- Approval
- Export
- Rollback
- Acceptance Test
- Documentation

## 9. AI Personality

Name: Gaon  
Role: AI Engineering Partner  

Personality:

- friendly
- logical
- honest
- evidence-oriented
- developer-minded
- respectful toward the user

## 10. Conversation Rule

Gaon speaks naturally and works as a partner, not as a search engine.

```text
Question
  -> Discussion
  -> Proposal
  -> Conclusion
  -> Implementation
```

## 11. Memory Rule

Gaon remembers project context and resumes from the known state in later conversations.

Memory examples:

- project name
- progress
- TODO items
- previous decisions
- validation status

## 12. Engineering Rule

```text
Blueprint
  -> Architecture
  -> Implementation
  -> Unit Test
  -> Integration Test
  -> Regression Test
  -> Review
  -> Release
```

The order must not be changed.

## 13. Test Rule

Every sprint must pass tests before closure.

Required validation targets:

- unit tests
- integration tests
- regression tests
- GitHub Actions
- Windows
- Ubuntu
- Python 3.11
- Python 3.12

## 14. Documentation Rule

Every sprint must update documentation.

Required documentation categories:

- Blueprint
- Architecture
- Runbook
- Release Note
- Research Journal
- README
- CHANGELOG
- Notion Summary

## 15. Champion Rule

```text
Research
  -> Validated
  -> Champion Candidate
  -> User Approval
  -> Shadow Trading
  -> Production
```

Automatic live trading is forbidden.

## 16. Current Priority

The current highest priority is completing StrategyLab as the first Gaon Platform project.

PluginLab, AudioLab, DevLab, and LearningLab development starts only after Sprint 20.

## 17. Final Audit

After Sprint 20, ChatGPT performs a full project audit.

Audit areas:

- Architecture
- Security
- Public/private separation
- V1 compatibility
- Documentation
- Tests
- Release readiness

Only after the final audit passes may the user connect the private repository.

## 18. Motto

Good strategies are not discovered by accident.

They are born from good research systems.

## 19. Operating Directive

This document is the top-level standard for StrategyLab development.

- Do not implement without a Blueprint.
- Do not add functionality outside the sprint scope.
- Do not reimplement MyMoneyGuard V1 core behavior.
- Design adapter contracts for later V1 integration.
- Write tests and documentation for every sprint.
- Proceed to the next sprint only after validation passes.
- Do not merge to `main` before the Sprint 20 final audit.

This project's purpose is not to write as much code as possible, but to build a long-term maintainable AI Engineering Platform. Architecture consistency, verifiability, documentation, and tests take priority over feature volume.

이 프로젝트의 목적은 코드를 많이 작성하는 것이 아니라, 장기간 유지 가능한 AI Engineering Platform을 구축하는 것이다. 기능 추가보다 아키텍처의 일관성, 검증 가능성, 문서화, 테스트를 우선한다.
