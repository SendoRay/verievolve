"""框架 v3 回归：记录层、ram 原语、契约工作区、候选档案、可证明性质检查、外部 Verilog 评价。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

PASS_TX = '''def build(g, spec):
    xi, xq = g.input()
    picks = list(range(spec.SLOTS))
    yi = g.q(xi, spec.output_bits, spec.output_bits - 1)
    yq = g.q(xq, spec.output_bits, spec.output_bits - 1)
    g.output(g.gather(yi, spec.SLOTS, picks), g.gather(yq, spec.SLOTS, picks))
'''

RAM_TX = '''def build(g, spec):
    xi, xq = g.input()
    k = g.counter(1, 7, like=xi, modulus=80)
    one = g.bits(g.const(1, 2, 0), 0, 0)
    wa = g.bits(k, 5, 0)
    ra = g.bits(g.sub(g.const(63, 8, 0), g.bits(k, 5, 0)), 5, 0)
    yi = g.q(g.ram(xi, wa, one, ra, 64), spec.output_bits, spec.output_bits - 1)
    yq = g.q(g.ram(xq, wa, one, ra, 64), spec.output_bits, spec.output_bits - 1)
    picks = list(range(spec.SLOTS))
    g.output(g.gather(yi, spec.SLOTS, picks), g.gather(yq, spec.SLOTS, picks))
'''


class FrameworkV3(unittest.TestCase):
    def test_record_matches_worker(self):
        from dspgen.record import build, export
        from dspgen.task import get, evaluate_program
        t = get("dev_r32_narrow")
        code = t.direct_start()
        g, task, _ = build(code, "dev_r32_narrow")
        r = evaluate_program(code, "dev_r32_narrow")
        self.assertAlmostEqual(task.score(0, g.y[0])["snr_db"], r["quality"]["scenarios"][0]["snr_db"], places=9)
        e = export(g)
        self.assertGreater(e["summary"]["nodes"], 3)
        self.assertEqual(len(e["semantic_hash"]), 16)

    def test_ram_rtl_equivalence(self):
        from dspgen.rtl import crosscheck
        from dspgen.task import get
        t = get("ofdm_tx64_q64")
        r = crosscheck(RAM_TX, "ofdm_tx64_q64", scenario=0, n_in=t.n_in())
        self.assertTrue(r["passed"], r)
        self.assertEqual(r["mismatches"], 0)

    def test_contract_workspace_and_archive(self):
        from dspgen.contract import CONTRACTS, make_workspace
        from dspgen import archive
        with tempfile.TemporaryDirectory() as d:
            ws = make_workspace(CONTRACTS["ofdm_tx64_q64"], Path(d))
            for f in ("CONTRACT.md", "spec.json", "PRIMITIVES.md", "LIBRARY.md", "direct_start.py", ".contract.json"):
                self.assertTrue((ws / f).exists(), f)
            self.assertIn("g.ram", (ws / "PRIMITIVES.md").read_text())
            self.assertNotIn("CIC 寄存器", (ws / "PRIMITIVES.md").read_text())
            p = Path(d) / "p.py"
            p.write_text(PASS_TX)
            rec = archive.add(ws, "ofdm_tx64_q64", p, None, "REWRITE", "直通")
            self.assertEqual(rec["status"], "OPEN")          # 直通不是 IDFT：合法但有质量缺口
            self.assertGreater(rec["v"], 0)
            sh = archive.show(ws)
            self.assertEqual(sh["near_feasible_front"][0]["id"], rec["id"])

    def test_sweep_direct_start(self):
        from dspgen import symbolic
        from dspgen.task import get
        r = symbolic.sweep(get("dev_r32_narrow").direct_start(), "dev_r32_narrow", nf=96, amp_pass=0.1)
        self.assertGreater(r["worst_alias_rejection_db"], 60)
        self.assertLess(r["passband_ripple_db"], 0.5)

    def test_verdict_search(self):
        from dspgen import verdict
        from dspgen.task import get
        r = verdict.search(get("dev_r32_narrow").direct_start(), "dev_r32_narrow")
        self.assertEqual(r["verdict"], "FEASIBLE")
        names = {(k["name"], k["source"]) for k in r["constraints"]}
        self.assertEqual(names, {("snr", "sim:search"), ("alias_rejection", "sweep"), ("ripple", "sweep")})
        self.assertIn("local_quant_noise_weakest", r["diagnostics"])
        r = verdict.search(PASS_TX, "ofdm_tx64_q64")
        self.assertEqual(r["verdict"], "OPEN")
        self.assertEqual([k["name"] for k in r["constraints"]], ["snr"])

    def test_contract_envelope(self):
        from dspgen.contract import CONTRACTS
        env = CONTRACTS["real_r32_narrow"].envelope
        self.assertEqual(env["blocker_rel_db"], 45.0)
        self.assertLess(env["desired_peak"], 0.05)


if __name__ == "__main__":
    unittest.main()
