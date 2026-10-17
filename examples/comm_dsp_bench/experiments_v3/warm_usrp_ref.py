import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dspgen.task import get
for n in ("usrpq_dev_r32_narrow", "usrpq_real_r32_narrow"):
    t = get(n)
    for i in [0, 1, 10, 11, 12] + list(range(100, 130)):
        r = t._ref(i)
    print(n, {i: round(t._ref(i)["snr_db"], 2) for i in (0, 1, 10, 11, 12)}, "stat min", round(min(t._ref(i)["snr_db"] for i in range(100, 130)), 2), flush=True)
