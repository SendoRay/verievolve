"""certfit 模板进化程序：cordic_sincos（证书适应度，Arm C）

可调参数：
  algo:   "lut" | "cordic"
  order:  "nearest" | "linear" | "quad"（lut）
  depth:  64/128/256/512/1024（lut 全波表深）
  stages: 8..20（cordic 迭代级数）

证书字段：cert_mean_sqnr_db（确定性全枚举）、cert_wc_sqnr_db（最坏界）、
area_lut（真实 Yosys 综合）。精度-面积-吞吐 Pareto 由 MAP-Elites 网格维持。
"""

# EVOLVE-BLOCK-START
PARAMS = {
    "algo": "lut",
    "order": "nearest",
    "depth": 64,
    "stages": 12,
}
# EVOLVE-BLOCK-END
