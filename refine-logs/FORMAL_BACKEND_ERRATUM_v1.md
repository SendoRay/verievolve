# 正式后端勘误 v1：quad signed 舍入

日期：2026-10-02。研究协议、候选空间、Python模型、动作分布、seed、B32和工程阈值均不改变。

## 发现与停止

`formal-necessary-v1-20261002` 在全局提案179（seed307、joint第26次）自动停止，状态为 **inconclusive**，S/L均N/A。全部失败现场和此前记录保留，未运行held-out或cost-first。

候选hash：`ca6ccefbc07584e2521b0df245e2285eb74c3fa113234c31e995d02012e0b9b4`。
结构：LUT1024、quad、phase_bits=16；polyphase FIR16、product_drop=2。
NCO全相位对拍有5544个分量错误，最大512 LSB。

## 根因

`chains/ddc/rtl_gen.py::_lut_interp` 的quad `qr` 表达式把signed右移与unsigned拼接相加。拼接污染运算上下文，负`t2`按unsigned计算右移；左值声明signed不能修复已经错误的中间运算。

首错相位577：表值[1809,2009,2210]，a2=1、d=1、t2=-63。
- 正确：`(-63 >> 13) + 1 = 0`；sin=1812。
- 原DDC RTL：`((2^22-63) >> 13) + 1 = 512`；sin=2324。

独立复核在内存中完整重算得到sin/cos各2772个错误，精确匹配故障报告。原`design_gen.gen_lut_quarter`的signed切片实现与Python模型一致，故修复DDC RTL而不是修改模型以适配错误。

## 修复与验证

只将quad舍入改成两个显式signed操作数：signed t2的算术右移，加signed的单bit舍入位。保留a2[7:0]截断及其他数值语义。

- 全部5种LUT深度×9种相位位宽的quad全相位对拍通过。
- 原生成器在浅表64和深表1024上的全相位结果与模型一致。
- nearest/linear发射的RTL与Git834d449逐字节一致。
- 失败候选179的NCO与完整DDC含饱和/背压对拍已通过；新旧area key不同，旧错误quad面积不可复用。
- 全部37个pilot有效候选均无quad叶子，其当前RTL hash仍与旧记录完全一致。此前验证通过与新组合暴露错误不矛盾。
- 定位证据：`experiments_search/backend_repair/quad-signed-v1-20261002/`（位于`examples/comm_dsp_bench/`下）。

## 历史来源与重跑纪律

源码修复后，历史来源通过原SHA-256匹配当前文件或明确Git存档834d449；只读取旧字节，不执行旧代码，也不声称该存档提交在更早实验当时已存在。工具/库/脚本及当前生成的RTL仍必须一致才能用旧面积。当前运行的源码漂移检查不放宽。

只保留原先37个已审pilot面积的同等预热，不导入此次失败formal run的任何部分结果。新run从相同seed和初态重新执行完整预算；新的quad RTL若被提出必须重新综合与验证。

旧`FORMAL_S_READY.json`保留原样；修订实现使用新的`FORMAL_S_READY_v2.json`和新的run-id。旧formal-v1不转成S0，也不与新运行拼接成成功结果。
