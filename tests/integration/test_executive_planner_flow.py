import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import DeterministicExecutivePlanner, ExecutiveRequest, executive_plan_event
from gaon.runtime.storage import RuntimeStateStore


class ExecutivePlannerFlowTest(unittest.TestCase):
    def test_plan_event_store_and_cli_inspection(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            request = ExecutiveRequest("req-flow", "ORB 전략 연구해줘", "actor:redacted", "2026-07-18T00:00:00Z")
            plan = DeterministicExecutivePlanner().plan(request)
            event_store = SQLiteEventStore(store._connection)
            event_store.append(executive_plan_event(plan, actor_ref=request.actor_ref, appended_at=request.created_at))
            events = event_store.read_after()

            self.assertEqual(events[0].event_type, "ExecutivePlanCreated")
            self.assertEqual(events[0].payload["routing_decision"], "research")
        finally:
            store.close()

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["executive-plan", "--request", "ORB 전략 연구해줘"]), 0)
        self.assertIn("executive-plan: route=research", output.getvalue())

        json_output = StringIO()
        with redirect_stdout(json_output):
            self.assertEqual(cli_main(["executive-plan", "--request", "상태 알려줘", "--json"]), 0)
        self.assertIn('"routing_decision":"runtime"', json_output.getvalue())


if __name__ == "__main__":
    unittest.main()
