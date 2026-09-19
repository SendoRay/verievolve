"""certfit 模板进化程序：lut_sincos

参数：algo("lut"|"cordic"), order("nearest"|"linear"|"quad"),
      depth(64/128/256/512/1024), stages(8..20)。

证书字段：cert_mean_sqnr_db（确定性全枚举）、cert_wc_sqnr_db（最坏界）、
area_lut（真实 Yosys 综合）。精度-面积-吞吐 Pareto 由 MAP-Elites 网格维持。

本次进化说明：
  - 保留四分之一波折叠 + 段内线性插值：y = T[k] + (T[k+1]-T[k]) * ds / W。
  - 上一版把"相位分辨率"(2^14/象限) 误当成精度上界，实际瓶颈是段内线性
    插值的曲率误差 ≈ h^2/8（h 为段宽）。depth=64（每象限 16 段）时该误差
    约 -58 dB，正是 61 dB 的来源。
  - 将 depth 提升到 512（每象限 128 段）：插值误差降到约 -94 dB，逼近 16 位
    输出的量化上限（~98 dB）；面积仅随表项线性增长，且小数位 ds 变窄使
    乘法器更小，因此是精度/面积的边际最优点。
"""

# EVOLVE-BLOCK-START
PARAMS = {
    "algo": "lut",
    "order": "linear",
    "depth": 512,
    "stages": 12,
}
# EVOLVE-BLOCK-END