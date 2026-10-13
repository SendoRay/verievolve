"""dspgraph：由积木库组成的通信 DSP 链表示、评价、搜索与硬件生成框架。"""

from . import blocks  # noqa: F401  导入即注册全部积木
from .core import REGISTRY, PlanError, build, catalog, chain_cost  # noqa: F401
