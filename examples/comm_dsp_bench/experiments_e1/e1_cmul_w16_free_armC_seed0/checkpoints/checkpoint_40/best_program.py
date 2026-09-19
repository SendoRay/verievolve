"""certfit 模板进化程序：cmul_w16_free（证书适应度，Arm C）

你（LLM）在本文件内进化 PARAMS 字典。每个合法参数点都会被确定性证书
评估器赋予精确的 SQNR/面积，不存在采样噪声——同一点永远同一分数。

可调参数与语义：
  operand_trunc (int, 0..10)   每操作数 RNE 丢位 → 乘法器变窄（面积↓）
  prod_drop      (int, 0..8)   输出丢位 → 精度换面积（SQNR ≈ 6.02·(30-2·so-sd)）
  rounding       ("rne"|"trunc")  舍入模式
  structure      ("direct"|"karatsuba")  4 乘法器 vs 3 乘法器（精度不变，面积不同）

评估反馈字段：
  cert_mean_sqnr_db : 确定性均值 SQNR（排序适应度，零噪声）
  cert_wc_sqnr_db   : 全体输入最坏情况 SQNR 下界（sound 证书）
  area_lut          : 真实 Yosys ice40 综合面积
"""

# EVOLVE-BLOCK-START
# precision 已饱和在 999 dB（不可再提升），因此在不损失精度的前提下
# 用 Karatsuba 结构把 4 个乘法器降为 3 个，直接压低面积。
PARAMS = {
    "operand_trunc": 0,
    "prod_drop": 0,
    "rounding": "rne",
    "structure": "karatsuba",
}
# EVOLVE-BLOCK-END