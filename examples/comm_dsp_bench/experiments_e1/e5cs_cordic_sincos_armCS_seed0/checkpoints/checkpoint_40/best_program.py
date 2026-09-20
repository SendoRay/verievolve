"""certfit 模板进化程序：cordic_sincos（证书适应度，Arm C）

可调参数：
  algo:   "lut" | "cordic"
  order:  "nearest" | "linear" | "quad"（lut）
  depth:  64/128/256/512/1024（lut 全波表深）
  stages: 8..20（cordic 迭代级数）

证书字段：cert_mean_sqnr_db（确定性全枚举）、cert_wc_sqnr_db（最坏界）、
area_lut（真实 Yosys 综合）。精度-面积-吞吐 Pareto 由 MAP-Elites 网格维持。

探索策略：
  放弃 CORDIC（吞吐 0.07，综合分仅 0.5562），回到实测最优的 LUT 线性插值。

  实测轨迹非常规整，说明精度事实上由“插值步长”而非任何小上限决定：
    depth= 64 -> 61.11 dB
    depth=128 -> 73.20 dB   (+12.09 dB)
    depth=256 -> 85.09 dB   (+11.89 dB)
  每次表深加倍都稳定带来 ~+12 dB，这正好等于 20*log10(4)：线性插值误差
  ∝ 步长^2，步长减半 -> 误差降至 1/4 -> SQNR 提升 12 dB。也就是说所谓
  “~61.4 dB 上限”并不存在，之前的 61.4 只是 quad/64 的表值量化巧合。

  面积方面，加深深度的代价极小（ROM/译码仅随表深缓慢增长）：
    2220 (d=64) -> 2260 (d=128) -> 2332 (d=256)
  在 score ∝ precision^0.4 / area^0.106 下，继续加倍表深仍是净收益：
    depth=256 实测 0.7613。

  因此继续加倍到 depth=512：预计再降 ~12 dB 插值误差（趋向输出字量化上限
  ~97 dB），面积仅小幅上升，可在不牺牲吞吐（0.9082）的前提下进一步拉高
  精度-面积 Pareto 点，是本轮最稳妥的增量改进。
"""

# EVOLVE-BLOCK-START
PARAMS = {
    # 回退到已被验证的 LUT 线性插值路线（throughput 0.9082，远优于 CORDIC）。
    # 关键：depth=64/128/256 的实测精度为 61.11 / 73.20 / 85.09 dB，
    # 每次加倍稳定 +12 dB（= 20*log10(4)，线性插值误差 ∝ 1/depth^2 所致），
    # 说明精度仍受插值步长支配，尚未触及输出字宽上限。
    # 面积每步仅 +40~70 LUT（ROM/译码随表深缓慢增长），
    # 在 score ∝ precision^0.4 / area^0.106 下继续加深高度划算。
    # 故取 depth=512：预期精度 ~97 dB（逼近输出量化上限），
    # 面积保持小幅增长，进一步提升精度-面积 Pareto 位置。
    "algo": "lut",
    "order": "linear",
    "depth": 512,
    "stages": 12,
}
# EVOLVE-BLOCK-END