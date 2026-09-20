"""certfit 模板进化程序：cordic_sincos（证书适应度，Arm C）

可调参数：
  algo:   "lut" | "cordic"
  order:  "nearest" | "linear" | "quad"（lut）
  depth:  64/128/256/512/1024（lut 全波表深）
  stages: 8..20（cordic 迭代级数）

证书字段：cert_mean_sqnr_db（确定性全枚举）、cert_wc_sqnr_db（最坏界）、
area_lut（真实 Yosys 综合）。精度-面积-吞吐 Pareto 由 MAP-Elites 网格维持。

探索策略（从 LUT 转向 CORDIC）：
  历史尝试表明 LUT 路线已被“表值 / 输出字量化上限”钉死：
    * linear/64 达到 61.10 dB，而 quad/64 的实际上限约 61.43 dB（仅 +0.33 dB）；
    * 但 quad 让面积从 2220 翻倍到 4966 LUT（面积是拟合 score ∝ p / area^0.106
      中的主要惩罚项），反而把分数从 0.6640 拉到 0.6131。
  进一步分析：LUT 的 2220 LUT 主要来自插值算术（乘法器），ROM 本身很小，
  因此“加大表深 / 提高插值阶数”无法在精度-面积 Pareto 上继续改进——
  精度早已贴近同一输出字宽上限。

  因此转向 CORDIC：无 ROM、纯加/移位迭代，每级迭代约贡献 1 bit 角度精度，
  达到同一输出字宽上限所需级数很少（~10-12 级），在相同精度下面积显著低于
  插值查表。这能在保持精度 ~上限的同时，把 area 降低到 LUT 路线之下，
  从而按 score ∝ p / area^0.106 获得明显更高的分数，并在 area/throughput
  维度上生成新的 Pareto 点。stages=12 足以在输出字宽限制下达到精度上限。
"""

# EVOLVE-BLOCK-START
PARAMS = {
    # CORDIC 路线 throughput 只有 0.07（12 级迭代 = 12 周期/输出）。即便面积
    # 降到 1524、精度升到 70.9 dB，综合分仍从 0.6640 掉到 0.5562——吞吐才是
    # 这里的决定性维度。因此回退到已被验证的 LUT 线性插值（throughput 0.9082）。
    #
    # 面积分析：quad/64 面积 4966 vs linear/64 面积 2220，说明面积主项是插值
    # 乘法器而非 ROM；ROM 深度 64->128 仅让面积从 2220 增到 2260（+40 LUT），
    # 而精度从 61.1 dB 跃升到 73.2 dB（score 0.6640 -> 0.7134）。
    # 由于线性插值误差 ∝ 1/depth^2，继续加倍表深可进一步压低插值误差，
    # 仅付出极小的 ROM/译码面积代价。故取 depth=256：在精度逼近输出字量化
    # 上限的同时面积基本不变，期望在 score ∝ precision^0.4 / area^0.106 上
    # 继续获益，并在精度/面积维度上生成一个新的 Pareto 点。
    "algo": "lut",
    "order": "linear",
    "depth": 256,
    "stages": 12,
}
# EVOLVE-BLOCK-END