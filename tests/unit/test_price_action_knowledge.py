from __future__ import annotations

import tempfile
import unittest

from gaon.knowledge.evidence_hypothesis import StrategyHypothesisStatus
from gaon.knowledge.price_action_knowledge import (
    BINANCE_CONTEXTUAL_SETUPS,
    BROOKS_CONCEPTS,
    NISON_CONCEPTS,
    PriceActionMarket,
    build_contextual_setup,
    production_price_action_knowledge_seed_release_check,
    seed_binance_price_action_hypotheses,
)
from gaon.storage.foundation import GaonStorage


class ContextualSetupShapeTests(unittest.TestCase):
    """The product requirement this guards: a bare rule like "Hammer = BUY"
    must never be stored - every setup must combine regime + structure +
    location + signal candle + confirmation."""

    def test_every_seed_setup_has_all_five_contextual_fields(self) -> None:
        for setup in BINANCE_CONTEXTUAL_SETUPS:
            self.assertTrue(setup.regime.strip())
            self.assertTrue(setup.structure.strip())
            self.assertTrue(setup.location.strip())
            self.assertTrue(setup.signal_candle.strip())
            self.assertTrue(setup.confirmation.strip())

    def test_unknown_concept_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_contextual_setup(
                setup_id="bad",
                market=PriceActionMarket.BINANCE,
                regime="1H bullish trend",
                structure="x",
                location="y",
                signal_candle="z",
                confirmation="w",
                concept_ids=("does_not_exist",),
            )

    def test_covers_all_four_bin_pa_families_and_one_novel_combination(self) -> None:
        families = {s.bin_pa_family for s in BINANCE_CONTEXTUAL_SETUPS}
        self.assertTrue({"BIN-PA-01", "BIN-PA-02", "BIN-PA-03", "BIN-PA-04"}.issubset(families))
        self.assertIn(None, families, "at least one setup must be a novel, non-BIN-PA combination")


class MarketIsolationTests(unittest.TestCase):
    def test_every_binance_setup_topic_key_is_binance_namespaced(self) -> None:
        for setup in BINANCE_CONTEXTUAL_SETUPS:
            self.assertTrue(setup.topic_key.startswith("priceaction.binance."))
            self.assertNotIn("priceaction.kr.", setup.topic_key)

    def test_kr_scoped_setup_gets_a_kr_topic_key_not_binance(self) -> None:
        kr_setup = build_contextual_setup(
            setup_id="kr_probe",
            market=PriceActionMarket.KR,
            regime="1H bullish trend",
            structure="a two-legged pullback",
            location="support",
            signal_candle="bullish engulfing",
            confirmation="next-bar confirmation",
            concept_ids=("two_legged_pullback", "bullish_engulfing", "confirmation"),
        )
        self.assertTrue(kr_setup.topic_key.startswith("priceaction.kr."))
        self.assertNotIn("priceaction.binance.", kr_setup.topic_key)


class ConceptCatalogTests(unittest.TestCase):
    def test_nison_and_brooks_concept_lists_are_non_empty_and_distinct(self) -> None:
        nison_ids = {c.concept_id for c in NISON_CONCEPTS}
        brooks_ids = {c.concept_id for c in BROOKS_CONCEPTS}
        self.assertTrue(nison_ids)
        self.assertTrue(brooks_ids)
        self.assertEqual(set(), nison_ids & brooks_ids)

    def test_no_concept_definition_contains_a_fabricated_performance_token(self) -> None:
        for concept in (*NISON_CONCEPTS, *BROOKS_CONCEPTS):
            self.assertNotIn("%", concept.definition)
            self.assertNotIn("win_rate=", concept.definition)
            self.assertNotIn("return=", concept.definition)


class SeedBinancePriceActionHypothesesTests(unittest.TestCase):
    def test_seeding_produces_one_proposed_hypothesis_per_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hypotheses = seed_binance_price_action_hypotheses(storage=GaonStorage(tmp))

        self.assertEqual(len(BINANCE_CONTEXTUAL_SETUPS), len(hypotheses))
        for hypothesis in hypotheses:
            self.assertEqual(StrategyHypothesisStatus.PROPOSED, hypothesis.status)
            self.assertTrue(hypothesis.claim_ids)
            self.assertTrue(hypothesis.evidence_memory_ids)
            self.assertFalse(hypothesis.tested)
            self.assertFalse(hypothesis.knowledge_validated)
            self.assertFalse(hypothesis.production_approved)
            self.assertFalse(hypothesis.strategy_mutated)
            self.assertFalse(hypothesis.order_executed)
            self.assertTrue(hypothesis.topic_key.startswith("priceaction.binance."))

    def test_seeding_is_deterministic_and_deduplicates_on_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = GaonStorage(tmp)
            first = seed_binance_price_action_hypotheses(storage=storage)
            second = seed_binance_price_action_hypotheses(storage=storage)

        self.assertEqual(
            [h.hypothesis_id for h in first],
            [h.hypothesis_id for h in second],
        )


class PriceActionKnowledgeSeedReleaseCheckTests(unittest.TestCase):
    """Following this codebase's caller-wiring convention (see
    EconomicViabilityGateReleaseCheckTests in test_strategy_candidate.py) -
    this test IS the caller, so the assertions actually execute under
    `python -m unittest discover` / scripts/verify_release.py."""

    def test_release_check_passes(self) -> None:
        payload = production_price_action_knowledge_seed_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual(len(BINANCE_CONTEXTUAL_SETUPS), payload["seeded_count"])
        self.assertTrue(payload["all_proposed"])
        self.assertTrue(payload["all_binance_scoped"])
        self.assertTrue(payload["no_kr_topic_present"])
        self.assertTrue(payload["covers_all_four_bin_pa_families"])
        self.assertTrue(payload["has_novel_non_bin_pa_combination"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])


class PriceActionKnowledgeSeedCliWiringTests(unittest.TestCase):
    """CLI wiring for production_price_action_knowledge_seed_release_check,
    following the exact existing gaon-*-release-check pattern. Calls the
    SAME existing implementation via the CLI - no parallel/duplicate
    release-check logic is introduced here."""

    def test_price_action_knowledge_seed_release_check_cli_passes(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["gaon-price-action-knowledge-seed-release-check"])
        self.assertEqual(exit_code, 0)
        printed = output.getvalue()
        self.assertIn("gaon-price-action-knowledge-seed-release-check: PASS", printed)
        self.assertIn("all_proposed=true", printed)
        self.assertIn("all_binance_scoped=true", printed)
        self.assertIn("strategy_mutated=false", printed)
        self.assertIn("order_executed=false", printed)
        self.assertIn("champion_promoted=false", printed)
        self.assertIn("approval_bypassed=false", printed)


if __name__ == "__main__":
    unittest.main()
