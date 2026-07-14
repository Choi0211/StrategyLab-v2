# StrategyLab v2 System Architecture

Status: Sprint 1 Foundation

## Overview

StrategyLab v2 is organized as a modular research platform. Sprint 1 creates package boundaries only; domain behavior will be implemented in later sprints according to the Master Blueprint.

## Module Boundaries

- `strategylab.core`: configuration, logging, module registry, plugin discovery
- `strategylab.market`: market data interfaces
- `strategylab.strategies`: strategy plugin framework
- `strategylab.portfolio`: portfolio state and allocation
- `strategylab.risk`: risk controls and metrics
- `strategylab.backtest`: backtest workflows
- `strategylab.research`: AI-assisted research review
- `strategylab.broker`: broker abstractions
- `strategylab.dashboard`: research dashboard
- `strategylab.reports`: report generation
- `strategylab.notification`: notification interfaces

## Public / Private Boundary

This repository contains research platform code and example configuration only. MyMoneyGuard remains the private system for live trading, credentials, account data, execution state, operational logs, and deployment-specific configuration.

## Sprint 1 Non-Goals

Sprint 1 does not implement market downloads, strategy logic, backtest execution, broker calls, dashboard UI, notifications, or AI API calls.

