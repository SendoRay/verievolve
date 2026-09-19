# 参考文献（按章引用顺序，最终编号在合并时生成）

## LLM for RTL / 硬件

1. Thakur et al., "Verigen: Efficient hardware description generation using large language models," arXiv:2308.00708, 2023.
2. Liu et al., "RTLCoder: Outperforming GPT-3.5 in RTL code generation," ICCAD 2024, arXiv:2312.08617.
3. Xie et al., "CodeV: Retrieval-augmented ... to Verilog generation," arXiv:2406.14772, 2024.
4. Nadimi et al., "CraftRTL: Effective code generation for RTL," ICLR 2025, arXiv:2312.08167.
5. Goodlet et al., "AutoChip: Automating HDL generation using LLM feedback," arXiv:2311.04887, 2023.
6. Blocklove et al., "Chip-Chat: Challenges and opportunities in conversational hardware design," arXiv:2305.13243, 2023.
7. Ramakrishnan et al., "VerilogCoder: Autonomous Verilog coding agents with graph-based planning," ASP-DAC 2025, arXiv:2408.08927.
8. NVIDIA, "ACE-RTL: Agentic context evolution for RTL," 2026.
9. Liu et al., "VerilogEval: Evaluating LLMs for Verilog code generation," ICCAD 2023; v2 in ICML 2024.
10. Liu et al., "RTLLM 2.0," 2025, arXiv:2503.15508.
11. Synopsys/NVIDIA, "CVDP: Comprehensive Verilog Design Problems," arXiv:2506.14074, 2025.
12. BSC, "TuRTLe: A unified evaluation framework for RTL generation," MLCAD 2025, arXiv:2504.01986.
13. Yang et al., "Large Language Model for Verilog Code Generation: Literature Review and the Road Ahead," ACM Computing Surveys (接收), arXiv:2512.00020.
14. Zang et al., "The Dawn of Agentic EDA," arXiv:2512.23189, 2025.

## 进化式 LLM 代码生成

15. Novikov et al., "AlphaEvolve: A coding agent for scientific and algorithmic discovery," DeepMind, arXiv:2506.13131, 2025.
16. Sharma et al., "OpenEvolve," https://github.com/algorithmicsuperintelligence/openevolve, 2025.
17. Sakana AI, "ShinkaEvolve: Towards sample-efficient program evolution," arXiv:2509.19349, 2025.
18. Lehman et al., "Evolution through large models," 2022; Mouret & Clune, "Illuminating search spaces by mapping elites," 2015.
19. EvolVE: "Evolution strategies for LLM-driven chip design," arXiv:2601.18067, 2026.
20. REvolution: "LLM-driven evolutionary RTL," ASP-DAC 2026, arXiv:2510.21407.
21. COEVO: "Co-evolutionary LLM RTL optimization," arXiv/GitHub hping666/COEVO, 2026.
22. EvoVerilog: Zhang et al., "Multi-objective LLM population search for Verilog," arXiv:2508.13156, 2025.

## 定点算术 / 数值分析

23. Sung & Kum, "Simulation-based word-length optimization method for fixed-point DSP systems," IEEE Trans. Signal Processing, 1995.
24. Lee, Gaffar, Cheung, Mencer, Luk, Constantinides, "Accuracy-guaranteed bit-width optimization," IEEE TCAD, 2006.
25. de Dinechin & Pasca, "Designing custom arithmetic data paths with FloPoCo," IEEE Design & Test, 2011.
26. Chevillard, Joldes, Lauter, "Sollya: An environment for the development of numerical codes," ICMS 2010.
27. Muller, "Elementary Functions: Algorithms and Implementation," Birkhäuser, 3rd ed.
28. Boldo & Melquiond, "Gappa: Proving arithmetic properties automatically," arXiv:cs/0701131.
29. Darulova & Kuncak, "Daisy: Sound and automated program reasoning about floating-point precision," 2014.
30. Panchekha et al., "Automatically improving accuracy for floating point expressions," PLDI 2015.
31. Garrido, "A survey on pipelined FFT hardware architectures," Journal of Signal Processing Systems, 2013.

## 等价饱和 / 程序合成

32. Willsey et al., "egg: Fast and extensible equality saturation," POPL 2021.
33. Coward et al., "Automatic datapath optimization using e-graphs," ARITH 2022.
34. ROVER: "Reducing operator count in RTL via e-graph rewriting with verification," 2024.
35. ASPEN: "LLM-generated e-graph rewrite rules for RTL datapath optimization," MLCAD 2025.
36. Necula, "Proof-carrying code," POPL 1997.

## 形式化在环

37. Laeufer et al., "RTL-Repair: Quick combinational repair of RTL," ASPLOS 2024.
38. VeriThoughts: NYU, arXiv:2505.20302, 2025.
39. FormalRTL / SpecLoop 2026（见 Awesome-LLM-Circuit-Agent 索引）.

## 通信标准

40. 3GPP TS 38.211 (NR; Physical channels and modulation), TS 38.212 (Multiplexing and channel coding).

## 本文工作自身产物（实验数据）

- CommDSP-Bench 基准与审计：`examples/comm_dsp_bench/`（SPEC.md, AUDIT.md, regression_report3.json）
- 证书引擎：`examples/comm_dsp_bench/certfit/`
- E1/E2/E3/E4 实验数据：`examples/comm_dsp_bench/experiments_e1/`
