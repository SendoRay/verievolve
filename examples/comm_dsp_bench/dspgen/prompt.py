"""由 Task 规格自动拼出提示词（与链路无关）。"""
import inspect, json
from dspgraph.llm_prog import GENERAL, PRIMS
from dspgraph.sdf import Graph
from .graph import TaskGraph

EXTRA = ("interpolate",)


def api_doc():
    out = []
    for name in PRIMS + EXTRA:
        fn = getattr(TaskGraph, name, None) or getattr(Graph, name)
        sig = str(inspect.signature(fn)).replace("self, ", "").replace("(self)", "()")
        out.append(f"- g.{name}{sig}: " + " ".join((inspect.getdoc(fn) or "").split()))
    return "\n".join(out)


def interface_text(t):
    ik, ok = t.iface("in_kind"), t.iface("out_kind")
    return (f"输入：{'复数 (i, q)' if ik == 'complex' else '实数'}，有符号 {t.interface['in_bits']} 位，每 {t.iface('in_period')} 个时钟一个样点；"
            f"输出：{'复数 (i, q)' if ok == 'complex' else '实数'}，有符号 {t.interface['out_bits']} 位，"
            f"每 {t.iface('out_period')} 个时钟一个样点。")


def system_prompt(t, struct_note: str = "") -> str:
    sc = [t.scene(i) for i in t.search_scenarios]
    view = dict(t.params)
    view.update({"各测试场景SNR门槛dB": [round(s["snr_min_db"], 2) for s in sc],
                 "理想实现SNR上限dB": [round(s["ceiling_db"], 2) for s in sc],
                 "纹波上限dB": t.tolerance["ripple_max_db"]})
    return f"""你是数字通信硬件架构师。任务：修改 Python 程序 build(g, spec)，它用下面的原语搭出实现给定数学功能的硬件。
在满足全部指标的前提下，使硬件面积尽可能小。可以使用任何等价或近似变换，不要求与理想数学逐位相等，只要求指标达标。

【数学功能】
{t.description}

【接口】{interface_text(t)}

【规格参数】（程序中以 spec.<名字> 读取；另有 spec.input_bits、spec.output_bits）
{json.dumps(view, ensure_ascii=False, indent=1)}

【原语】
{api_doc()}

{GENERAL}
{struct_note}
【评分】裁判只看输入输出：冻结测试信号送入电路，对照理想参考计算 SNR（自动搜索群时延，只拟合一个复增益；
失真、混叠、镜像、量化噪声全部算误差）与通带纹波；每个场景都必须 SNR ≥ 门槛且纹波 ≤ 上限。

【回答格式】按要求给出对当前程序的修改。优先做有针对性的改动并保持程序达标；每次改动要有明确的面积收益理由。"""
