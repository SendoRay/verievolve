import sys
from pathlib import Path
import unittest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

import run_m4_hierarchical_pilot as hierarchical


class HierarchicalPilotTests(unittest.TestCase):
    def test_parse_action_accepts_plain_and_fenced_json(self):
        self.assertEqual(
            hierarchical.parse_action('{"action":"increase_precision","reason":"x"}'),
            "increase_precision",
        )
        self.assertEqual(
            hierarchical.parse_action('```json\n{"action":"change_rounding"}\n```'),
            "change_rounding",
        )
        self.assertIsNone(hierarchical.parse_action('{"candidate_index": 7}'))

    def test_repeated_action_expands_next_unvisited_candidate(self):
        spec = hierarchical.TASKS["fir"]
        rows, _, graph, _ = hierarchical.load_frozen_task(spec)
        counts = {action: 0 for action in spec.actions}
        visited = [spec.initial_index]
        first = hierarchical.normalize_and_expand(
            spec, "decrease_precision", visited, counts, rows, graph
        )
        visited.append(first["candidate_index"])
        counts["decrease_precision"] += 1
        second = hierarchical.normalize_and_expand(
            spec, "decrease_precision", visited, counts, rows, graph
        )
        self.assertNotEqual(first["candidate_index"], second["candidate_index"])
        self.assertIsNone(second["fallback_reason"])
        self.assertEqual(second["executed_action"], "decrease_precision")

    def test_invalid_action_uses_recorded_deterministic_fallback(self):
        spec = hierarchical.TASKS["fir"]
        rows, _, graph, _ = hierarchical.load_frozen_task(spec)
        counts = {action: 0 for action in spec.actions}
        result = hierarchical.normalize_and_expand(
            spec, "candidate-9", [spec.initial_index], counts, rows, graph
        )
        self.assertEqual(result["fallback_reason"], "invalid_or_unparseable_action")
        self.assertEqual(result["executed_action"], "switch_architecture")
        self.assertNotEqual(result["candidate_index"], spec.initial_index)

    def test_all_frozen_graph_edges_have_exactly_one_action(self):
        for spec in hierarchical.TASKS.values():
            rows, _, graph, _ = hierarchical.load_frozen_task(spec)
            for parent, children in graph.items():
                for child in children:
                    action = spec.classify_edge(
                        rows[parent]["params"], rows[child]["params"]
                    )
                    self.assertIn(action, spec.actions)

    def test_nco_primary_utility_is_defined_without_feasible_candidate(self):
        spec = hierarchical.TASKS["nco"]
        rows, areas, _, _ = hierarchical.load_frozen_task(spec)
        terminal = spec.terminal([spec.initial_index], rows, areas)
        self.assertIsNone(terminal["relative_area_loss"])
        self.assertIsInstance(spec.primary_utility(terminal), float)


if __name__ == "__main__":
    unittest.main()
