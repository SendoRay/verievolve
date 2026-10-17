"""dspc 候选级判定（G0–G2）与实现级一致性门（G3）的回归测试。使用 DDC 任务 dev_r32_narrow。"""
import shutil
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))
warnings.filterwarnings("ignore")

from dspc.direct import direct_start  # noqa: E402
from dspc.judge import verdict  # noqa: E402
from dspgen.task import get  # noqa: E402

TASK = "dev_r32_narrow"


class TestCandidateGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = direct_start(get(TASK))

    def test_direct_start_is_feasible_and_ideal_equals_formula(self):
        r = verdict(self.root, TASK, sweep=False)
        self.assertEqual(r["verdict"], "FEASIBLE")
        snr = r["constraints"][0]
        ideal = r["diagnostics"]["ideal_constraints"][0]
        # 直写起点的理想解释不差于任务的理想参考（门槛 + 允许损失）。注意两者测法不同：
        # 理想上限用已知延迟的 SNR，候选打分在延迟范围内搜索最佳对齐，因此后者可略高。
        loss = get(TASK).tolerance["snr_loss_db"]
        self.assertGreaterEqual(ideal["value"], ideal["threshold"] + loss - 0.1)
        self.assertGreater(snr["slack"], 0.3)

    def test_polyphase_rewrite_is_bit_exact(self):
        poly = self.root.replace(
            "        i5 = lib.fir(g, i1, h3, coef_bits=22)\n        q6 = lib.fir(g, q2, h3, coef_bits=22)\n"
            "    d7 = g.decimate(i5, 32)\n    d8 = g.decimate(q6, 32)",
            "        d7 = lib.fir_decimate(g, i1, h3, 32, coef_bits=22)\n"
            "        d8 = lib.fir_decimate(g, q2, h3, 32, coef_bits=22)")
        self.assertNotEqual(poly, self.root)
        r = verdict(poly, TASK, parent_code=self.root, claim="equiv", sweep=False)
        self.assertEqual(r["class"]["actual"], "T1")

    def test_precision_change_is_t2(self):
        narrow = self.root.replace("g.q(g.mul(x, cos), 22, 20)", "g.q(g.mul(x, cos), 14, 12)")
        r = verdict(narrow, TASK, parent_code=self.root, claim="equiv", sweep=False)
        self.assertEqual(r["class"]["actual"], "T2")
        self.assertIn("note", r["class"])                 # 声明 equiv 与实际不符

    def test_illegal_fold_is_broken(self):
        bad = self.root.replace("        q6 = lib.fir(g, q2, h3, coef_bits=22)\n",
                                "        q6 = lib.fir(g, q2, h3, coef_bits=22)\n        g.commit(fold=8)\n")
        r = verdict(bad, TASK, sweep=False)
        self.assertEqual(r["verdict"], "BROKEN")
        self.assertEqual(r["error"]["code"], "G0")


class TestFrameTask(unittest.TestCase):
    def test_ofdm_tx_direct_start_matches_v4(self):
        """OFDM 发射直写起点：定点 SNR（−EVM）与旧实现一致，理想解释为精确 IDFT。"""
        r = verdict(direct_start(get("ofdm_tx64_gen")), "ofdm_tx64_gen", sweep=False)
        self.assertEqual(r["verdict"], "FEASIBLE")
        self.assertAlmostEqual(r["constraints"][0]["value"], 54.86, delta=0.02)
        self.assertGreater(r["diagnostics"]["ideal_constraints"][0]["value"], 200)


DEC_PROG = '''
def build(g, spec):
    x = g.input()
    with g.scope("dec"):
        d = g.decimate(x, 32)
        g.commit(fold=32)
    b = spec.output_bits
    o = g.q(g.shift(d, -1), b, b - 1)
    g.output(o, g.q(g.sub(o, o), b, b - 1))
'''

GOOD_RTL = '''
module top(input clk, input rst, input in_valid, input signed [11:0] in_i,
           output reg out_valid, output reg signed [15:0] out_i, output reg signed [15:0] out_q);
  (* ve_scope = "dec" *) reg [4:0] cnt;
  always @(posedge clk) begin
    if (rst) begin cnt <= 0; out_valid <= 0; out_i <= 0; out_q <= 0; end
    else begin
      out_valid <= 0;
      if (in_valid) begin
        cnt <= cnt + 1;
        if (cnt == 0) begin out_valid <= 1; out_i <= {{1{in_i[11]}}, in_i, 3'b000}; out_q <= 0; end
      end
    end
  end
endmodule
'''


@unittest.skipIf(shutil.which("iverilog") is None, "iverilog not installed")
class TestConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dspc.contract import freeze
        cls.dir = Path(tempfile.mkdtemp(prefix="dspc_test_"))
        freeze(DEC_PROG, TASK, cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_faithful_rtl_passes(self):
        from dspc.conform import check
        self.assertTrue(check(self.dir, GOOD_RTL)["passed"])

    def test_bug_invisible_on_search_scenarios_is_caught(self):
        from dspc.conform import check
        bug = GOOD_RTL.replace("out_i <= {{1{in_i[11]}}, in_i, 3'b000};",
                               "out_i <= (in_i == 12'sh7ff) ? 16'sd0 : {{1{in_i[11]}}, in_i, 3'b000};")
        r = check(self.dir, bug)
        self.assertFalse(r["passed"])
        self.assertEqual(r["sets"]["search0"]["mismatches"], 0)    # 搜索场景看不出来
        self.assertGreater(r["sets"]["extreme"]["mismatches"], 0)  # 极值序列抓到

    def test_missing_scope_annotation_is_caught(self):
        from dspc.conform import check
        r = check(self.dir, GOOD_RTL.replace('(* ve_scope = "dec" *) ', ""))
        self.assertIn("scope_annotation", [v["code"] for v in r["violations"]])


if __name__ == "__main__":
    unittest.main()
