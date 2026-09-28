"""DDC 子链（数字下变频）：混频 → 接收 FIR → 抽取。

模块：
  spec        冻结参数（版本化）
  scenarios   场景生成（float 输入，seed 冻结）
  ref_chain   float64 参考链
  fixed_chain 整数 bit-true 候选链
  candidates  候选空间与合法性检查
  metrics     局部/系统指标与谱加权预测模型
"""
