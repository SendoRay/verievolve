"""冻结 witness NCO 池：RTL 映射 vs Python bit-true 全映射逐位对拍 + 数值等价类。

WITNESS_FROZEN_DDC_v1 §2.2 / §7-14。候选只读取 accumulator 高 B 位（B≤16），
所以对全部 2^B 个相位字穷举即覆盖完整 2^32 映射；低位用固定 seed 随机填充，
为每个高位相位字取一条代表状态。RTL 只读取高位这一结构事实由生成代码锁定；
等价类按 2^16 个高 16 位码上的完整 (sin, cos) 映射划分。

直接运行本文件会把逐点结果写入
examples/comm_dsp_bench/experiments_system/nco_rtl_equiv_v1/report.json。
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from certfit import tpl_cordic
from chains.ddc import candidates, fixed_chain, rtl_gen, spec

TB = """`timescale 1ns/1ps
module tb;
    reg [31:0] acc;
    wire signed [15:0] s, c;
    reg [31:0] mem [0:{n_m1}];
    integer i, fh;
    nco_map dut(.phase_acc(acc), .sin_o(s), .cos_o(c));
    initial begin
        $readmemh("{stim}", mem);
        fh = $fopen("{dump}", "w");
        for (i = 0; i < {n}; i = i + 1) begin
            acc = mem[i];
            #1;
            $fwrite(fh, "%0d %0d\\n", s, c);
        end
        $fclose(fh);
        $finish;
    end
endmodule
"""


def python_map(cfg: dict, acc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """与 fixed_chain.nco_sincos 相同的 acc → (sin, cos) 位精确映射。"""
    b = int(cfg["phase_bits"])
    z = (acc >> (spec.W_P_ACC - b)) << (16 - b)
    z_signed = np.where(z >= (1 << 15), z - (1 << 16), z).astype(np.int64)
    params = ({"algo": "lut", "order": cfg["order"], "depth": int(cfg["depth"])}
              if cfg["algo"] == "lut" else {"algo": "cordic", "stages": int(cfg["stages"])})
    s, c = tpl_cordic.emulate(params, z_signed)
    return s.astype(np.int64), c.astype(np.int64)


def exhaustive_acc(cfg: dict, seed: int = 0) -> np.ndarray:
    b = int(cfg["phase_bits"])
    low = np.random.default_rng(seed).integers(0, 1 << (32 - b), size=1 << b)
    return (np.arange(1 << b, dtype=np.int64) << (32 - b)) | low


def rtl_map(cfg: dict, acc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "nco.v").write_text(rtl_gen.gen_nco_verilog(cfg))
        (td / "stim.hex").write_text("\n".join(f"{int(a):08x}" for a in acc) + "\n")
        (td / "tb.v").write_text(TB.format(n=len(acc), n_m1=len(acc) - 1,
                                           stim=td / "stim.hex", dump=td / "out.txt"))
        p = subprocess.run(["iverilog", "-g2012", "-o", str(td / "sim"),
                            str(td / "nco.v"), str(td / "tb.v")],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"{cfg['name']} iverilog 编译失败：{p.stderr[:500]}")
        subprocess.run([str(td / "sim")], capture_output=True, text=True, cwd=td,
                       timeout=600, check=True)
        rows = np.loadtxt(td / "out.txt", dtype=np.int64).reshape(-1, 2)
    return rows[:, 0], rows[:, 1]


def mapping_digest(cfg: dict) -> str:
    """2^16 个高 16 位码上的完整映射摘要（B≤16 时即完整 2^32 映射）。"""
    s, c = python_map(cfg, np.arange(1 << 16, dtype=np.int64) << 16)
    return hashlib.sha256(s.astype("<i4").tobytes() + c.astype("<i4").tobytes()).hexdigest()


def equivalence_classes(pool: list[dict]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for cfg in pool:
        groups.setdefault(mapping_digest(cfg), []).append(cfg["name"])
    return sorted((sorted(v) for v in groups.values()), key=lambda g: g[0])


def run_all(pool: list[dict]) -> dict:
    results = {}
    for cfg in pool:
        acc = exhaustive_acc(cfg)
        ps, pc = python_map(cfg, acc)
        rs, rc = rtl_map(cfg, acc)
        mism = int(np.sum(ps != rs) + np.sum(pc != rc)) if len(rs) == len(ps) else -1
        results[cfg["name"]] = {
            "candidate": dict(cfg),
            "n_states": int(len(acc)),
            "coverage": "all high phase words; one deterministic low-bit representative",
            "mismatch": mism,
            "pass": mism == 0,
            "digest": mapping_digest(cfg),
        }
    version = subprocess.run(["iverilog", "-V"], capture_output=True, text=True)
    first_line = (version.stdout or version.stderr).splitlines()[0]
    return {
        "schema_version": "nco-rtl-equiv-v1",
        "pool": "legacy6+frozen-v2-20",
        "pool_size": len(pool),
        "iverilog_version": first_line,
        "results": results,
        "classes": equivalence_classes(pool),
    }


needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None,
                                    reason="需要 iverilog")


def test_python_map_matches_fixed_chain_trajectory():
    # 本测试的 Python 映射必须就是全链使用的 fixed_chain.nco_sincos
    n, f = 4096, 0.39
    fcw = spec.fcw_of(f)
    acc = (np.arange(n, dtype=np.int64) * fcw) & 0xFFFFFFFF
    for cfg in candidates.witness_nco_candidates():
        s, c = fixed_chain.nco_sincos(cfg, n, f)
        ps, pc = python_map(cfg, acc)
        np.testing.assert_array_equal(s, ps, err_msg=cfg["name"])
        np.testing.assert_array_equal(c, pc, err_msg=cfg["name"])


@needs_iverilog
@pytest.mark.parametrize("cfg", candidates.witness_nco_candidates(include_legacy=False),
                         ids=lambda c: c["name"])
def test_v2_nco_rtl_matches_python_exhaustively(cfg):
    acc = exhaustive_acc(cfg)
    ps, pc = python_map(cfg, acc)
    rs, rc = rtl_map(cfg, acc)
    assert len(rs) == len(acc)
    np.testing.assert_array_equal(rs, ps)
    np.testing.assert_array_equal(rc, pc)


def test_equivalence_classes_are_exact_mapping_partitions():
    pool = candidates.witness_nco_candidates()
    classes = equivalence_classes(pool)
    assert sorted(n for g in classes for n in g) == sorted(c["name"] for c in pool)
    by_name = {c["name"]: c for c in pool}
    for g in classes:
        ref = python_map(by_name[g[0]], np.arange(1 << 16, dtype=np.int64) << 16)
        for name in g[1:]:
            got = python_map(by_name[name], np.arange(1 << 16, dtype=np.int64) << 16)
            np.testing.assert_array_equal(got[0], ref[0])
            np.testing.assert_array_equal(got[1], ref[1])


if __name__ == "__main__":
    rep = run_all(candidates.witness_nco_candidates())
    out = BENCH / "experiments_system" / "nco_rtl_equiv_v1" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    for name, r in rep["results"].items():
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {name} states={r['n_states']} mismatch={r['mismatch']}")
    print("classes:", [g for g in rep["classes"] if len(g) > 1])
