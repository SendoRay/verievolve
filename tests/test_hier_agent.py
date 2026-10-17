import unittest

from examples.comm_dsp_bench.dspgen.hier_agent.model import (
    ActionKind,
    Candidate,
    MacroAction,
    RootEvaluation,
    dominates,
)
from examples.comm_dsp_bench.dspgen.hier_agent.inspect_worker import _enter, _exit
from examples.comm_dsp_bench.dspgen.hier_agent.source import find_regions, instrument_source, tune_parameters
from examples.comm_dsp_bench.dspgraph.sdf import Sig


PROGRAM = '''
P = dict(width=16, taps=[1, 2, 1])

def build(g, spec):
    x = g.input()
    with g.scope("first"):
        y = g.q(x, P["width"], P["width"] - 1)
    with g.scope("second"):
        z = g.add(y, y)
    g.output(z)
'''


class SourceTest(unittest.TestCase):
    def test_region_boundaries(self):
        regions = find_regions(PROGRAM)
        self.assertEqual([row.name for row in regions], ["first", "second"])
        self.assertIn("x", regions[0].inputs)
        self.assertEqual(regions[0].outputs, ("y",))
        self.assertIn("y", regions[1].inputs)
        self.assertEqual(regions[1].outputs, ("z",))

    def test_redefinition_kills_false_boundary(self):
        program = '''
def build(g, spec):
    x = g.input()
    with g.scope("a"):
        y = g.add(x, x)
        scratch = g.delay_line(y, 2)
    with g.scope("b"):
        scratch = g.delay_line(y, 3)
        z = scratch[0]
    g.output(z)
'''
        regions = find_regions(program)
        self.assertEqual(regions[0].outputs, ("y",))
        self.assertIn("y", regions[1].inputs)

    def test_instrumentation_compiles(self):
        source, regions = instrument_source(PROGRAM)
        compile(source, "<test>", "exec")
        self.assertEqual(source.count("__hier_enter"), len(regions))
        self.assertEqual(source.count("__hier_exit"), len(regions))

    def test_entry_snapshot_survives_in_place_signal_redefinition(self):
        class Graph:
            pass

        graph = Graph()
        before = Sig(graph, "z0", 19, -4, lin=None, lat=16)
        after = Sig(graph, "z1", 16, 18, lin=None, lat=17)
        env = {"z": before}
        _enter(graph, "comb", ["z"], env)
        env["z"] = after
        _exit(graph, "comb", ["z"], env)
        capture = graph._hier_regions[0]
        self.assertEqual(capture["inputs"][0]["width"], 19)
        self.assertEqual(capture["outputs"][0]["width"], 16)

    def test_structured_tune(self):
        source = tune_parameters(PROGRAM, {"width": 14, "taps": [1, 0, 1]})
        namespace = {}
        exec(source, namespace)
        self.assertEqual(namespace["P"]["width"], 14)
        self.assertEqual(namespace["P"]["taps"], [1, 0, 1])


class ParetoTest(unittest.TestCase):
    @staticmethod
    def candidate(name, area, margin, ripple=0.1):
        return Candidate(
            name,
            f"{name}.py",
            name,
            None,
            MacroAction(ActionKind.ROOT, ["root"], "test"),
            RootEvaluation(True, True, margin, ripple, area),
        )

    def test_root_dominance_honors_margin_contract(self):
        cheap_under_margin = self.candidate("a", 8.0, 0.2)
        feasible = self.candidate("b", 10.0, 0.4)
        self.assertTrue(dominates(feasible, cheap_under_margin, 0.3))
        self.assertFalse(dominates(cheap_under_margin, feasible, 0.3))


if __name__ == "__main__":
    unittest.main()
