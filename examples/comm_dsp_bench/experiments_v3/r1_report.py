"""第一轮结果汇总：表格（Markdown）+ 对比图（面积、功耗两个分面，每个分面一根纵轴）。
数据全部来自本目录下的终验 JSON；不足的项写“—”。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/chengzhy/verievolve/thesis/midterm/figures/src")
from style import C_BASE, C_NAIVE, C_OURS, C_REF, INK, INK2, use_data_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

D = Path(__file__).resolve().parent
J = lambda p: json.loads((D / p).read_text())

rows = []   # (链路, 方法, 类别, 质量, 面积, 功耗, fmax, 说明)
# 链路 A：45 dB 强干扰 DDC
u = J("usrp_real_r32_narrow.json")
rows.append(("A 强干扰 DDC", "USRP（开源）", "base", "不达标（SNR 差 5.5 dB）", u["ppa"]["area_um2"],
             u["ppa"]["power_vcd"]["total_mw"], u["ppa"]["fmax_mhz"], "固定结构，参数为本规格的最优配置"))
t = J("textbook/real_r32_narrow_pipe_final.json")
rows.append(("A 强干扰 DDC", "教科书结构 + 贪心字长（规则）", "rule", "达标；时序差 0.17 ns",
             t["objectives"]["area_um2"], t["objectives"]["power_mw"], t["objectives"]["fmax_mhz"],
             "CORDIC + 5 阶 CIC + 半带 + 补偿 FIR，90 次评价"))
for k in (1, 2):
    r = J(f"r1_final/real_r32_narrow_full_{k}.json")
    rows.append(("A 强干扰 DDC", f"本方法（Claude agent）{k} 号", "ours", "终验通过", r["objectives"]["area_um2"],
                 r["objectives"]["power_mw"], r["objectives"]["fmax_mhz"], ""))
# 链路 C：OFDM 发射
z = J("zipcpu_ofdm_tx64_gen.json")["hwmpy1_ckpce3"]["ppa"]
rows.append(("C OFDM 发射（任意输入）", "ZipCPU IFFT（开源）+ 外壳", "base", "终验通过", z["area_um2"],
             z["power_vcd"]["total_mw"], z["fmax_mhz"], "64 点流水 IFFT，按其生成规则配置"))
r = J("r1_final/ofdm_tx64_gen_full_1.json")
rows.append(("C OFDM 发射（任意输入）", "本方法（Claude agent）", "ours", "终验通过", r["objectives"]["area_um2"],
             r["objectives"]["power_mw"], r["objectives"]["fmax_mhz"], ""))
z2 = J("zipcpu_ofdm_tx64_q1024.json")["hwmpy1_ckpce3"]["ppa"]
rows.append(("C OFDM 发射（1024QAM 输入）", "ZipCPU IFFT（开源）+ 外壳", "base", "终验通过", z2["area_um2"],
             z2["power_vcd"]["total_mw"], z2["fmax_mhz"], "同上"))
for k in (1, 2):
    r = J(f"r1_final/ofdm_tx64_q1024_full_{k}.json")
    rows.append(("C OFDM 发射（1024QAM 输入）", f"本方法（Claude agent）{k} 号", "ours", "终验通过（映射器融合）",
                 r["objectives"]["area_um2"], r["objectives"]["power_mw"], r["objectives"]["fmax_mhz"], ""))

md = ["| 链路 | 方法 | 质量 | 真实面积 (μm²) | 仿真功耗 (mW) | fmax (MHz) | 说明 |", "|---|---|---|---|---|---|---|"]
for a, m, _, q, ar, pw, f, n in rows:
    md.append(f"| {a} | {m} | {q} | {ar:,.0f} | {pw:.1f} | {f:.0f} | {n} |")
(D / "r1_results.md").write_text("\n".join(md) + "\n")
print("\n".join(md))

use_data_style()
groups = list(dict.fromkeys(r[0] for r in rows))
col = {"base": C_BASE, "rule": C_NAIVE, "ours": C_OURS}
fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
for ax, idx, lab in ((axes[0], 4, "真实面积 (um^2，Nangate45)"), (axes[1], 5, "门级仿真功耗 (mW)")):
    x, ticks, tl = 0, [], []
    for gname in groups:
        gr = [r for r in rows if r[0] == gname]
        start = x
        for r in gr:
            ax.bar(x, r[idx], width=0.8, color=col[r[2]], edgecolor="#fcfcfb", linewidth=2)
            ax.text(x, r[idx], f"{r[idx]:,.0f}" if idx == 4 else f"{r[idx]:.1f}", ha="center", va="bottom",
                    fontsize=7.5, color=INK2)
            x += 1
        ticks.append((start + x - 1) / 2)
        tl.append(gname.replace("（", "\n（"))
        x += 0.8
    ax.set_xticks(ticks)
    ax.set_xticklabels(tl, fontsize=8.5)
    ax.set_ylabel(lab)
    ax.grid(axis="x", visible=False)
from matplotlib.patches import Patch  # noqa: E402
axes[0].legend(handles=[Patch(color=C_BASE, label="开源实现"), Patch(color=C_NAIVE, label="规则方法（教科书 + 贪心字长）"),
                        Patch(color=C_OURS, label="本方法（每根柱为一次独立运行）")], loc="upper left", bbox_to_anchor=(0.0, -0.18), ncol=3, fontsize=8, frameon=False)
fig.suptitle("第一轮：同一质量判定、同一综合与功耗流程下的对比（目标时钟 A 2.0 ns，C 2.5 ns）", x=0.06, ha="left",
             fontsize=10.5, color=INK)
fig.tight_layout(rect=(0, 0.06, 1, 0.94))
fig.savefig(D / "figs" / "r1_compare.png", dpi=200)
print(D / "figs" / "r1_compare.png")
