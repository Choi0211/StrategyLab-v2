import json
import re
import sqlite3
import unittest
from urllib.request import Request

from gaon.research.krx_real_pipeline import (
    FieldProvenance,
    KRXDatasetBuilder,
    KRXFixtureMarketDataProvider,
    KRXTradingCalendar,
    RealAutonomousResearchPipeline,
    RealMarketDataUnavailable,
    RuleBasedBacktestEngine,
    UserStrategyParser,
    WalkForwardValidator,
    YahooKRXHistoricalDataProvider,
    YAHOO_KRX_ALL_ZERO_VOLUME_ANOMALY_DATES,
    YAHOO_KRX_RESEARCH_SYMBOLS,
    YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL,
    YAHOO_KRX_ANOMALY_POLICY,
    build_market_data_provider_from_env,
    default_execution_assumptions,
    historical_krx_data_quality_inspect,
    historical_krx_data_quality_release_check,
    historical_krx_calendar_release_check,
    krx_trading_calendar_release_check,
    provider_gap_release_check,
    real_krx_data_release_check,
    yahoo_krx_bar_debug,
    _blocking_quality_findings,
    _parse_yahoo_chart_payload,
)
from gaon.research.real_research import DataQualityEngine, DataQualityStatus, MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


STRATEGY_TEXT = "20일 고가 돌파 + 종가 > MA20 > MA60 + 거래량 >= 20일 평균 이상, 손절 -5%, 10일 저점 이탈 청산"


class KRXRealPipelineUnitTests(unittest.TestCase):
    def test_strategy_parser_tracks_user_provenance_without_fixture_leakage(self) -> None:
        spec = UserStrategyParser().parse(STRATEGY_TEXT, created_at="2026-07-25T00:00:00Z")
        self.assertEqual(spec.entry["breakout_lookback"].value, 20)
        self.assertEqual(spec.entry["breakout_lookback"].provenance, FieldProvenance.USER_PROVIDED)
        payload = str(spec.to_json())
        self.assertNotIn("volume_multiplier", payload)
        self.assertNotIn("max_risk_pct", payload)
        self.assertNotIn("regime_tags", payload)

    def test_dataset_builder_marks_fixture_source_and_reuses_cache(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        builder = KRXDatasetBuilder(connection, KRXFixtureMarketDataProvider())
        first, quality, inserted = builder.build("005930", start_date="2026-01-01", end_date="2026-07-10")
        second, _, inserted_again = builder.build("005930", start_date="2026-01-01", end_date="2026-07-10")
        self.assertTrue(inserted)
        self.assertFalse(inserted_again)
        self.assertTrue(first.metadata.fixture_backed)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(quality.status.value, "pass")

    def test_yahoo_provider_parses_real_response_with_provenance(self) -> None:
        provider = YahooKRXHistoricalDataProvider(opener=_opener(_sample_yahoo_payload()))
        dataset = provider.fetch_bars("005930", start_date="2026-01-01", end_date="2026-04-10")
        self.assertFalse(dataset.metadata.fixture_backed)
        self.assertEqual(dataset.metadata.source, "real:yahoo-chart")
        self.assertEqual(len(dataset.bars), 70)
        self.assertGreater(dataset.bars[-1].trading_value, 0)

    def test_yahoo_parser_normalizes_krx_won_float_drift(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1767225600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [70000.000004],
                                    "high": [69999.999996],
                                    "low": [69000.000004],
                                    "close": [70000.000003],
                                    "volume": [1_000_000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
        bars = _parse_yahoo_chart_payload(payload, "005930")
        self.assertEqual(bars[0].open, 70000.0)
        self.assertEqual(bars[0].high, 70000.0)
        self.assertEqual(bars[0].low, 69000.0)
        self.assertEqual(bars[0].close, 70000.0)
        dataset = MarketDataset("dataset:test:yahoo-float-drift", (MarketSymbol("005930", "005930", "KOSPI"),), bars, MarketDataMetadata("real:yahoo-chart", "KOSPI", "daily", bars[0].timestamp, bars[0].timestamp, False, "2026-07-25T00:00:00Z", False))
        self.assertEqual(DataQualityEngine().validate(dataset, min_bars=1).status, DataQualityStatus.PASS)

    def test_yahoo_parser_excludes_inconsistent_same_index_ohlc(self) -> None:
        bars = _parse_yahoo_chart_payload(_yahoo_ohlc_alignment_payload(), "005930")
        self.assertEqual(tuple(bar.timestamp for bar in bars), ("2024-10-11", "2024-10-15"))
        dataset = MarketDataset("dataset:test:yahoo-provider-ohlc-anomaly", (MarketSymbol("005930", "005930", "KOSPI"),), bars, MarketDataMetadata("real:yahoo-chart", "KOSPI", "daily", "2024-10-11", "2024-10-15", False, "2026-07-25T00:00:00Z", False))
        report = DataQualityEngine().validate(dataset, min_bars=1, calendar=KRXTradingCalendar(), missing_date_classifier=lambda day: YAHOO_KRX_ANOMALY_POLICY.classify_missing_date(day, symbol="005930"))
        self.assertTrue(any(item.code == "provider_ohlc_anomaly" and "2024-10-14" in item.message for item in report.findings))
        self.assertFalse(any(item.code == "invalid_ohlc" for item in report.findings))

    def test_yahoo_bar_debug_reports_raw_and_normalized_alignment(self) -> None:
        payload = _yahoo_ohlc_alignment_payload()
        debug = yahoo_krx_bar_debug("005930", "2024-10-14", opener=_opener(json.dumps(payload)))
        row = debug["rows"][0]
        self.assertEqual(row["index"], 1)
        self.assertEqual(row["date_kst"], "2024-10-14")
        self.assertEqual(row["raw"]["close"], 59300.0)
        self.assertEqual(row["raw"]["adjclose"], 57535.75)
        self.assertFalse(row["same_index_ohlc_consistent"])

    def test_data_quality_reports_invalid_ohlc_date_and_values(self) -> None:
        dataset = _quality_dataset("diagnostic-invalid", "2026-01-02", "2026-01-02", ("2026-01-02",), invalid_ohlc=True)
        report = DataQualityEngine().validate(dataset, min_bars=1, calendar=KRXTradingCalendar())
        finding = next(item for item in report.findings if item.code == "invalid_ohlc")
        self.assertIn("date=2026-01-02", finding.message)
        self.assertIn("open=", finding.message)
        self.assertIn("high=", finding.message)

    def test_krx_calendar_excludes_weekends_and_holidays_from_missing_dates(self) -> None:
        calendar = KRXTradingCalendar()
        self.assertNotIn("2026-07-04", calendar.expected_open_dates(start_date="2026-07-03", end_date="2026-07-06"))
        self.assertNotIn("2026-01-01", calendar.expected_open_dates(start_date="2026-01-01", end_date="2026-01-05"))
        self.assertIn("2026-01-02", calendar.expected_open_dates(start_date="2026-01-01", end_date="2026-01-05"))
        self.assertIn("2025-09-19", calendar.expected_open_dates(start_date="2025-09-19", end_date="2025-09-19"))
        self.assertEqual(len(calendar.expected_open_dates(start_date="2025-01-02", end_date="2026-07-24")), 379)
        weekend_report = DataQualityEngine().validate(_quality_dataset("weekend", "2026-07-03", "2026-07-06", ("2026-07-03", "2026-07-06")), min_bars=1, calendar=calendar)
        holiday_start_report = DataQualityEngine().validate(_quality_dataset("holiday-start", "2026-01-01", "2026-01-05", ("2026-01-02", "2026-01-05")), min_bars=1, calendar=calendar)
        weekend_end_report = DataQualityEngine().validate(_quality_dataset("weekend-end", "2026-07-03", "2026-07-05", ("2026-07-03",)), min_bars=1, calendar=calendar)
        self.assertEqual(weekend_report.status, DataQualityStatus.PASS)
        self.assertEqual(holiday_start_report.status, DataQualityStatus.PASS)
        self.assertEqual(weekend_end_report.status, DataQualityStatus.PASS)

    def test_krx_calendar_detects_missing_trading_day(self) -> None:
        report = DataQualityEngine().validate(_quality_dataset("missing", "2026-01-02", "2026-01-06", ("2026-01-02", "2026-01-06")), min_bars=1, calendar=KRXTradingCalendar())
        self.assertEqual(report.status, DataQualityStatus.PASS_WITH_WARNINGS)
        self.assertTrue(any(item.code == "missing_dates" and "trading dates" in item.message for item in report.findings))

    def test_krx_quality_keeps_malformed_and_duplicate_warnings(self) -> None:
        malformed = DataQualityEngine().validate(_quality_dataset("malformed", "2026-01-02", "2026-01-02", ("2026-01-02",), invalid_ohlc=True), min_bars=1, calendar=KRXTradingCalendar())
        duplicate = DataQualityEngine().validate(_quality_dataset("duplicate", "2026-01-02", "2026-01-02", ("2026-01-02", "2026-01-02")), min_bars=1, calendar=KRXTradingCalendar())
        self.assertEqual(malformed.status, DataQualityStatus.FAIL)
        self.assertTrue(any(item.code == "invalid_ohlc" for item in malformed.findings))
        self.assertEqual(duplicate.status, DataQualityStatus.FAIL)
        self.assertTrue(any(item.code == "duplicate_bars" for item in duplicate.findings))

    def test_yahoo_provider_gap_is_classified_without_changing_exchange_calendar(self) -> None:
        dataset = _large_yahoo_gap_dataset()
        report = KRXDatasetBuilder(None, _StaticProvider(dataset)).build("005930", start_date="2025-09-17", end_date="2025-09-23")[1]
        self.assertEqual(report.status, DataQualityStatus.PASS_WITH_WARNINGS)
        self.assertTrue(any(item.code == "provider_gap" and "2025-09-19" in item.message for item in report.findings))
        self.assertFalse(any(item.code == "unknown_missing_trading_day" for item in report.findings))

    def test_provider_anomaly_does_not_affect_other_provider(self) -> None:
        dataset = _quality_dataset("other-gap", "2025-09-17", "2025-09-23", ("2025-09-17", "2025-09-18", "2025-09-22", "2025-09-23"), source="real:other-provider")
        report = KRXDatasetBuilder(None, _StaticProvider(dataset)).build("005930", start_date="2025-09-17", end_date="2025-09-23")[1]
        self.assertTrue(any(item.code == "unknown_missing_trading_day" for item in report.findings))
        self.assertFalse(any(item.code == "provider_gap" for item in report.findings))

    def test_yahoo_known_ohlc_anomalies_are_provider_specific_non_blocking(self) -> None:
        calendar = KRXTradingCalendar()
        cases = {
            "005930": {"2024-10-14", "2025-09-19"},
            "000660": {"2024-10-14", "2025-09-19"},
            "005380": {"2024-01-15", "2025-09-19"},
            "035420": {"2025-09-19"},
            "051910": {"2024-10-14", "2024-11-07", "2025-09-19"},
        }
        for symbol, missing in cases.items():
            dates = tuple(day for day in calendar.expected_open_dates(start_date="2024-01-10", end_date="2025-09-23") if day not in missing)
            dataset = _quality_dataset(f"known-yahoo-anomaly-{symbol}", "2024-01-10", "2025-09-23", dates, source="real:yahoo-chart", symbol=symbol)
            report = KRXDatasetBuilder(None, _StaticProvider(dataset)).build(symbol, start_date=dataset.metadata.start_date, end_date=dataset.metadata.end_date)[1]
            self.assertFalse(any(item.code == "invalid_ohlc" for item in report.findings), symbol)
            self.assertFalse(any(item.code == "unknown_missing_trading_day" for item in report.findings), symbol)
            self.assertFalse(any(item.severity == "error" for item in report.findings), symbol)

    def test_real_release_check_allows_provider_gap_only(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        dataset = _large_yahoo_gap_dataset()
        result = real_krx_data_release_check(connection, symbol="005930", start_date=dataset.metadata.start_date, end_date=dataset.metadata.end_date, provider=_StaticProvider(dataset))
        self.assertEqual(result["quality"], "pass_with_warnings")
        self.assertEqual(result["provider_gaps"], 1)
        self.assertEqual(result["provider_gap_dates"], ("2025-09-19",))
        self.assertEqual(result["provider_ohlc_anomalies"], 0)
        self.assertEqual(result["blocking_findings"], 0)

    def test_real_release_check_blocks_unknown_gap(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        dates = tuple(day for day in KRXTradingCalendar().expected_open_dates(start_date="2025-09-17", end_date="2025-12-31") if day != "2025-09-19")
        dataset = _quality_dataset("unknown-large-gap", "2025-09-17", "2025-12-31", dates, source="real:other-provider")
        with self.assertRaises(RealMarketDataUnavailable):
            real_krx_data_release_check(connection, symbol="005930", start_date=dataset.metadata.start_date, end_date=dataset.metadata.end_date, provider=_StaticProvider(dataset))

    def test_real_release_check_reports_invalid_ohlc_detail(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        dates = KRXTradingCalendar().expected_open_dates(start_date="2026-01-02", end_date="2026-04-10")
        dataset = _quality_dataset("release-invalid-detail", "2026-01-02", "2026-04-10", dates, invalid_ohlc=True, source="real:yahoo-chart")
        with self.assertRaisesRegex(RealMarketDataUnavailable, r"invalid_ohlc:.*date=2026-01-02.*open=.*high="):
            real_krx_data_release_check(connection, symbol="005930", start_date=dataset.metadata.start_date, end_date=dataset.metadata.end_date, provider=_StaticProvider(dataset))

    def test_krx_trading_calendar_release_check_preserves_schema_and_provenance(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        result = krx_trading_calendar_release_check(connection)
        self.assertEqual(result["schema_version"], 33)
        self.assertFalse(result["fixture_backed"])
        self.assertEqual(result["source"], "real:test-calendar")
        self.assertTrue(result["weekend_excluded"])
        self.assertTrue(result["holiday_excluded"])
        self.assertTrue(result["missing_trading_day_detected"])

    def test_historical_krx_calendar_excludes_2023_2024_market_holidays(self) -> None:
        calendar = KRXTradingCalendar()
        historical_closed = (
            "2023-05-29",
            "2023-08-15",
            "2023-09-28",
            "2023-09-29",
            "2023-10-02",
            "2023-10-03",
            "2023-10-09",
            "2023-12-25",
            "2023-12-29",
            "2024-01-01",
            "2024-02-09",
            "2024-02-12",
            "2024-03-01",
            "2024-04-10",
            "2024-05-01",
            "2024-05-06",
            "2024-05-15",
            "2024-06-06",
            "2024-08-15",
            "2024-09-16",
            "2024-09-17",
            "2024-09-18",
            "2024-10-01",
            "2024-10-03",
            "2024-10-09",
            "2024-12-25",
            "2024-12-31",
        )
        for day in historical_closed:
            self.assertNotIn(day, calendar.expected_open_dates(start_date=day, end_date=day))
        self.assertIn("2025-09-19", calendar.expected_open_dates(start_date="2025-09-19", end_date="2025-09-19"))
        self.assertIn("2022-01-03", calendar.expected_open_dates(start_date="2022-01-03", end_date="2022-01-03"))
        self.assertIn("2022-05-09", calendar.expected_open_dates(start_date="2022-05-09", end_date="2022-05-09"))

    def test_historical_yahoo_3y_gap_is_only_provider_gap(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        result = historical_krx_calendar_release_check(connection)
        self.assertEqual(result["schema_version"], 33)
        self.assertEqual(result["provider_gap_dates"], ("2025-09-19",))
        self.assertEqual(result["blocking_findings"], 0)
        self.assertEqual(result["expected_3y"] - result["actual_3y_without_provider_gap"], 1)
        self.assertGreater(result["expected_5y"], result["expected_3y"])

    def test_historical_data_quality_release_check_classifies_known_provider_anomalies(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        result = historical_krx_data_quality_release_check(connection)
        self.assertEqual(result["schema_version"], 33)
        self.assertEqual(result["symbols_checked"], YAHOO_KRX_RESEARCH_SYMBOLS)
        self.assertEqual(result["provider_gap_dates"], ("2022-01-03", "2022-05-09", "2023-02-01", "2023-02-02", "2023-02-09", "2025-09-19"))
        self.assertEqual(result["provider_ohlc_anomaly_dates"], ("2024-01-15", "2024-10-14", "2024-11-07"))
        self.assertEqual(result["provider_zero_volume_anomaly_dates"], tuple(sorted(YAHOO_KRX_ALL_ZERO_VOLUME_ANOMALY_DATES)))
        symbol_results = result["symbol_results"]
        self.assertEqual(symbol_results["000660"]["provider_gap_dates"], ("2022-01-03", "2022-05-09", "2023-02-02", "2023-02-09", "2025-09-19"))
        self.assertEqual(symbol_results["005380"]["provider_gap_dates"], ("2022-01-03", "2022-05-09", "2023-02-01", "2025-09-19"))
        self.assertEqual(symbol_results["035420"]["provider_gap_dates"], ("2022-01-03", "2022-05-09", "2023-02-02", "2025-09-19"))
        self.assertEqual(symbol_results["051910"]["provider_gap_dates"], ("2022-01-03", "2022-05-09", "2025-09-19"))
        self.assertEqual(symbol_results["005930"]["provider_zero_volume_anomaly_dates"], tuple(sorted(YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL["005930"])))
        self.assertEqual(symbol_results["000660"]["provider_zero_volume_anomaly_dates"], tuple(sorted(YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL["000660"])))
        self.assertEqual(symbol_results["005380"]["provider_zero_volume_anomaly_dates"], tuple(sorted(YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL["005380"])))
        self.assertEqual(symbol_results["035420"]["provider_zero_volume_anomaly_dates"], tuple(sorted(YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL["035420"])))
        self.assertEqual(symbol_results["051910"]["provider_zero_volume_anomaly_dates"], tuple(sorted(YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL["051910"])))
        self.assertEqual(result["zero_volume_policy"], "registered_zero_volume_excluded_unregistered_blocks")
        self.assertEqual(result["blocking_findings"], 0)
        self.assertTrue(result["symbol_specific_gap_isolated"])

    def test_yahoo_symbol_specific_research_gaps_do_not_leak_to_unregistered_symbols(self) -> None:
        calendar = KRXTradingCalendar()
        dates = tuple(day for day in calendar.expected_open_dates(start_date="2022-01-03", end_date="2022-01-05") if day != "2022-01-03")
        samsung = _quality_dataset("samsung-symbol-gap", "2022-01-03", "2022-01-05", dates, source="real:yahoo-chart", symbol="005930")
        unregistered = _quality_dataset("unregistered-symbol-gap", "2022-01-03", "2022-01-05", dates, source="real:yahoo-chart", symbol="068270")
        samsung_report = KRXDatasetBuilder(None, _StaticProvider(samsung)).build("005930", start_date="2022-01-03", end_date="2022-01-05")[1]
        unregistered_report = KRXDatasetBuilder(None, _StaticProvider(unregistered)).build("068270", start_date="2022-01-03", end_date="2022-01-05")[1]
        self.assertTrue(any(item.code == "provider_gap" and "2022-01-03" in item.message for item in samsung_report.findings))
        self.assertFalse(any(item.code == "unknown_missing_trading_day" for item in samsung_report.findings))
        self.assertTrue(any(item.code == "unknown_missing_trading_day" and "2022-01-03" in item.message for item in unregistered_report.findings))

    def test_yahoo_research_symbols_classify_production_zero_volume_anomalies(self) -> None:
        dates = KRXTradingCalendar().expected_open_dates(start_date="2022-01-24", end_date="2022-06-30")
        for symbol in YAHOO_KRX_RESEARCH_SYMBOLS:
            with self.subTest(symbol=symbol):
                zero_volume_dates = YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL[symbol]
                dataset = _quality_dataset(
                    f"registered-zero-volume-{symbol}",
                    "2022-01-24",
                    "2022-06-30",
                    dates,
                    source="real:yahoo-chart",
                    symbol=symbol,
                    zero_volume_dates=zero_volume_dates,
                )
                normalized, report, _inserted = KRXDatasetBuilder(None, _StaticProvider(dataset)).build(symbol, start_date="2022-01-24", end_date="2022-06-30")
                normalized_dates = tuple(bar.timestamp for bar in normalized.bars)
                for anomaly_date in zero_volume_dates:
                    self.assertNotIn(anomaly_date, normalized_dates)
                self.assertEqual(_finding_dates_for_test(report, "provider_zero_volume_anomaly"), tuple(sorted(zero_volume_dates)))
                self.assertFalse(any(item.code == "zero_volume" for item in report.findings))
                self.assertFalse(_blocking_quality_findings(report))

    def test_production_inspect_path_normalizes_yahoo_suffix_symbols(self) -> None:
        dates = KRXTradingCalendar().expected_open_dates(start_date="2022-01-03", end_date="2022-06-30")
        zero_volume_dates = YAHOO_KRX_ZERO_VOLUME_ANOMALY_DATES_BY_SYMBOL["000660"]
        dataset = _quality_dataset(
            "hynix-production-suffix",
            "2022-01-03",
            "2022-06-30",
            tuple(day for day in dates if day not in {"2022-01-03", "2022-05-09"}),
            source="real:yahoo-chart",
            symbol="000660.KS",
            zero_volume_dates=zero_volume_dates,
        )
        inspection = historical_krx_data_quality_inspect("000660.KS", "2022-01-03", "2022-06-30", provider=_StaticProvider(dataset))
        self.assertIn("2022-01-03", inspection["provider_gap_dates"])
        self.assertIn("2022-05-09", inspection["provider_gap_dates"])
        self.assertEqual(inspection["provider_zero_volume_anomaly_dates"], tuple(sorted(zero_volume_dates)))
        self.assertEqual(inspection["unknown_missing_trading_dates"], ())
        self.assertEqual(inspection["zero_volume_dates"], ())
        self.assertEqual(inspection["blocking_findings"], ())

    def test_unregistered_zero_volume_remains_blocking_and_inspectable(self) -> None:
        dates = KRXTradingCalendar().expected_open_dates(start_date="2026-01-02", end_date="2026-01-06")
        dataset = _quality_dataset("zero-volume-inspect", "2026-01-02", "2026-01-06", dates, source="real:yahoo-chart", zero_volume_dates=frozenset({"2026-01-05"}))
        report = KRXDatasetBuilder(None, _StaticProvider(dataset)).build("005930", start_date="2026-01-02", end_date="2026-01-06")[1]
        self.assertTrue(any(item.code == "zero_volume" and "2026-01-05" in item.message for item in report.findings))
        self.assertTrue(any(item.code == "zero_volume" for item in _blocking_quality_findings(report)))
        inspection = historical_krx_data_quality_inspect("005930", "2026-01-02", "2026-01-06", provider=_StaticProvider(dataset))
        self.assertEqual(inspection["zero_volume_dates"], ("2026-01-05",))
        self.assertTrue(any(item["code"] == "zero_volume" for item in inspection["blocking_findings"]))

    def test_registered_zero_volume_anomaly_is_excluded_and_reported(self) -> None:
        dates = KRXTradingCalendar().expected_open_dates(start_date="2022-01-24", end_date="2022-04-29")
        dataset = _quality_dataset("registered-zero-volume", "2022-01-24", "2022-04-29", dates, source="real:yahoo-chart", zero_volume_dates=frozenset({"2022-01-26"}))
        normalized, report, _inserted = KRXDatasetBuilder(None, _StaticProvider(dataset)).build("005930", start_date="2022-01-24", end_date="2022-04-29")
        self.assertNotIn("2022-01-26", tuple(bar.timestamp for bar in normalized.bars))
        self.assertTrue(any(item.code == "provider_zero_volume_anomaly" and "2022-01-26" in item.message for item in report.findings))
        self.assertFalse(any(item.code == "zero_volume" for item in report.findings))
        self.assertFalse(_blocking_quality_findings(report))
        inspection = historical_krx_data_quality_inspect("005930", "2022-01-24", "2022-04-29", provider=_StaticProvider(dataset))
        self.assertEqual(tuple(item["date"] for item in inspection["registered_provider_zero_volume_bars"]), ("2022-01-26",))
        self.assertEqual(inspection["zero_volume_dates"], ())

    def test_provider_gap_release_check_preserves_schema_and_provenance(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        result = provider_gap_release_check(connection)
        self.assertEqual(result["schema_version"], 33)
        self.assertFalse(result["fixture_backed"])
        self.assertEqual(result["provider"], "real:yahoo-chart")
        self.assertEqual(result["quality"], "pass_with_warnings")
        self.assertEqual(result["provider_gap_dates"], ("2025-09-19",))
        self.assertEqual(result["blocking_findings"], 0)

    def test_yahoo_provider_empty_malformed_and_failure_are_unavailable(self) -> None:
        with self.assertRaises(RealMarketDataUnavailable):
            YahooKRXHistoricalDataProvider(opener=_opener('{"chart":{"result":[],"error":null}}')).fetch_bars("005930", start_date="2026-01-01", end_date="2026-01-10")
        with self.assertRaises(RealMarketDataUnavailable):
            YahooKRXHistoricalDataProvider(opener=_opener("{bad")).fetch_bars("005930", start_date="2026-01-01", end_date="2026-01-10")
        with self.assertRaises(RealMarketDataUnavailable):
            YahooKRXHistoricalDataProvider(opener=_failing_opener).fetch_bars("005930", start_date="2026-01-01", end_date="2026-01-10")

    def test_real_release_check_rejects_fixture_and_accepts_fake_real_data(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        with self.assertRaises(RealMarketDataUnavailable):
            real_krx_data_release_check(connection, symbol="005930", start_date="2026-01-01", end_date="2026-04-10", provider=KRXFixtureMarketDataProvider())
        provider = YahooKRXHistoricalDataProvider(opener=_opener(_sample_yahoo_payload()))
        result = real_krx_data_release_check(connection, symbol="005930", start_date="2026-01-01", end_date="2026-04-10", provider=provider)
        self.assertEqual(result["source"], "real")
        self.assertFalse(result["fixture_backed"])
        self.assertEqual(result["quality"], "pass")

    def test_env_provider_selection_requires_explicit_real_provider(self) -> None:
        self.assertIsInstance(build_market_data_provider_from_env({}), KRXFixtureMarketDataProvider)
        with self.assertRaises(RealMarketDataUnavailable):
            build_market_data_provider_from_env({"GAON_REAL_MARKET_DATA_ENABLED": "true", "GAON_MARKET_DATA_PROVIDER": "fixture"})
        self.assertIsInstance(build_market_data_provider_from_env({"GAON_REAL_MARKET_DATA_ENABLED": "true", "GAON_MARKET_DATA_PROVIDER": "yahoo-chart"}), YahooKRXHistoricalDataProvider)

    def test_rule_backtest_is_deterministic_and_applies_costs(self) -> None:
        dataset = KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")
        spec = UserStrategyParser().parse(STRATEGY_TEXT, created_at="2026-07-25T00:00:00Z")
        assumptions = default_execution_assumptions()
        engine = RuleBasedBacktestEngine()
        first = engine.run("unit-run", spec, dataset, assumptions, generated_at="2026-07-25T00:00:00Z")
        second = engine.run("unit-run", spec, dataset, assumptions, generated_at="2026-07-25T00:00:00Z")
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertGreaterEqual(first.metrics.trade_count, 1)
        self.assertLess(first.trades[0].entry_price, first.trades[0].exit_price)
        self.assertGreater(first.trades[0].entry_price, dataset.bars[65].close)
        self.assertIsNotNone(first.metrics.sharpe)

    def test_walk_forward_uses_chronological_split(self) -> None:
        dataset = KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")
        spec = UserStrategyParser().parse(STRATEGY_TEXT, created_at="2026-07-25T00:00:00Z")
        report = WalkForwardValidator().validate(spec, dataset, default_execution_assumptions(), run_id="unit-wf", generated_at="2026-07-25T00:00:00Z")
        self.assertEqual(report.validation_id, "validation:unit-wf")
        self.assertGreaterEqual(report.train_metrics.trade_count, 1)
        self.assertGreaterEqual(report.test_metrics.trade_count, 0)

    def test_pipeline_report_is_korean_and_persists_memory(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        report = RealAutonomousResearchPipeline(connection).run(STRATEGY_TEXT, run_id="unit-pipeline", generated_at="2026-07-25T00:00:00Z")
        self.assertIn("[분석 기준]", report.korean_report)
        self.assertIn("source=fixture", report.korean_report)
        self.assertEqual(len(report.candidates), 3)
        self.assertIsNotNone(report.memory_id)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM krx_real_research_memories").fetchone()[0], 1)
        self.assertGreaterEqual(SCHEMA_VERSION, 33)

    def test_hotfix2402_pipeline_exposes_validation_horizon_and_signal_diagnostics(self) -> None:
        report = RealAutonomousResearchPipeline(None).run(STRATEGY_TEXT, run_id="unit-validation-coverage", generated_at="2026-07-25T00:00:00Z")
        payload = report.to_json()
        coverage = payload["validation_coverage"]

        self.assertGreaterEqual(coverage["raw_bars"], 365)
        self.assertNotEqual("unknown", coverage["actual_start"])
        self.assertEqual(60, coverage["warmup_bars"])
        self.assertIn("entry_signal_count", coverage)
        self.assertIn("combined_entry_signals", coverage["signal_diagnostics"])
        self.assertEqual(30, coverage["minimum_required_trades"])
        self.assertIn(coverage["sample_sufficiency_status"], {"sufficient", "insufficient_trades", "insufficient_signals"})
        self.assertTrue(coverage["window_fingerprint"])
        self.assertTrue(coverage["comparison_window_compatible"])
        self.assertIn("horizon_attempts", payload)

    def test_real_pipeline_report_discloses_provider_gap(self) -> None:
        report = RealAutonomousResearchPipeline(None, _StaticProvider(_large_yahoo_gap_dataset())).run(STRATEGY_TEXT, run_id="unit-provider-gap", generated_at="2026-07-25T00:00:00Z")
        self.assertEqual(report.quality.status, DataQualityStatus.PASS_WITH_WARNINGS)
        self.assertIn("데이터 공급자 경고", report.korean_report)
        self.assertIn("2025-09-19", report.korean_report)
        self.assertIn("공급자 데이터 누락", report.korean_report)


def _quality_dataset(name: str, start: str, end: str, dates: tuple[str, ...], *, invalid_ohlc: bool = False, source: str = "real:test-calendar", symbol: str = "005930", zero_volume_dates: frozenset[str] = frozenset()) -> MarketDataset:
    bars = []
    for index, day in enumerate(dates):
        close = 100.0 + index
        high = close + 1.0
        low = close - 1.0
        if invalid_ohlc:
            high = close - 2.0
        volume = 0 if day in zero_volume_dates else 1_000_000 + index
        bars.append(MarketBar(day, symbol, close, high, low, close, volume, int(close * volume)))
    metadata = MarketDataMetadata(source, "KOSPI", "daily", start, end, True, "2026-07-25T00:00:00Z", False)
    return MarketDataset(f"dataset:test:{name}:{start}:{end}", (MarketSymbol(symbol, symbol, "KOSPI"),), tuple(bars), metadata)


def _large_yahoo_gap_dataset() -> MarketDataset:
    dates = tuple(day for day in KRXTradingCalendar().expected_open_dates(start_date="2025-09-17", end_date="2025-12-31") if day != "2025-09-19")
    return _quality_dataset("large-yahoo-gap", "2025-09-17", "2025-12-31", dates, source="real:yahoo-chart")


class _StaticProvider:
    source = "real:static-test"

    def __init__(self, dataset: MarketDataset) -> None:
        self._dataset = dataset

    def fetch_bars(self, _symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        self.source = self._dataset.metadata.source
        return self._dataset


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def _opener(body: str):
    def open_(_request: Request, _timeout: float) -> _Response:
        return _Response(body)

    return open_


def _failing_opener(_request: Request, _timeout: float) -> object:
    raise TimeoutError("network timeout")


def _sample_yahoo_payload() -> str:
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    start = 1767225600
    for index in range(70):
        close = 100.0 + index * 0.25 + (4.0 if index == 64 else 0.0)
        timestamps.append(start + index * 86400)
        opens.append(round(close - 0.3, 4))
        highs.append(round(close + 0.9, 4))
        lows.append(round(close - 1.0, 4))
        closes.append(round(close, 4))
        volumes.append(1_000_000 + index * 10_000 + (500_000 if index == 64 else 0))
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": volumes,
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    return json.dumps(payload)


def _yahoo_ohlc_alignment_payload() -> dict[str, object]:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [1728604800, 1728864000, 1728950400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [59100.0, 59500.0, 61100.0],
                                "high": [60100.0, 61200.0, 61400.0],
                                "low": [59000.0, 59400.0, 60100.0],
                                "close": [59300.0, 59300.0, 61000.0],
                                "volume": [29623969, 20886249, 22715239],
                            }
                        ],
                        "adjclose": [
                            {
                                "adjclose": [57535.75, 57535.75, 59185.17578125],
                            }
                        ],
                    },
                }
            ],
            "error": None,
        }
    }


def _finding_dates_for_test(report, code: str) -> tuple[str, ...]:
    dates = []
    for finding in report.findings:
        if finding.code != code:
            continue
        match = re.search(r"\d{4}-\d{2}-\d{2}", finding.message)
        if match:
            dates.append(match.group(0))
    return tuple(sorted(dates))


if __name__ == "__main__":
    unittest.main()
