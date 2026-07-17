import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main
from gaon.runtime.metrics import MetricsCollector


class RuntimeMetricsTest(unittest.TestCase):
    def test_counter_gauge_timing_snapshot(self) -> None:
        metrics = MetricsCollector()
        metrics.increment("runtime_loops", component="runtime")
        metrics.increment("runtime_loops", component="runtime")
        metrics.gauge("queue_depth", 3, component="queue")
        metrics.observe("provider_latency", 0.25, provider="deterministic")

        text = metrics.snapshot().to_text()

        self.assertIn("counter runtime_loops=2", text)
        self.assertIn("gauge queue_depth=3", text)
        self.assertIn("timing provider_latency.count=1", text)

    def test_bounded_cardinality_and_redaction_rejection(self) -> None:
        metrics = MetricsCollector()

        with self.assertRaises(ValueError):
            metrics.increment("bad name")
        with self.assertRaises(ValueError):
            metrics.increment("provider_request", chat_id="100")
        with self.assertRaises(ValueError):
            metrics.increment("provider_request", component="x" * 80)

    def test_concurrency_safety(self) -> None:
        metrics = MetricsCollector()

        def worker() -> None:
            for _ in range(100):
                metrics.increment("event_append", component="event_store")

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertIn("event_append=500", metrics.snapshot().to_text())

    def test_cli_metrics_output(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["metrics"]), 0)

        self.assertIn("runtime_loops", output.getvalue())
        self.assertIn("queue_depth", output.getvalue())


if __name__ == "__main__":
    unittest.main()
