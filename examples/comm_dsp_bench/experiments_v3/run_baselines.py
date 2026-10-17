"""开源基线在 v3 框架下的完整评价（搜索、留出、30 个统计场景、门级仿真功耗）。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dspgen.baselines import usrp, zipcpu_fft
out = Path(__file__).resolve().parent
if not (out / "zipcpu_ofdm_tx64_q1024.json").exists():
    r = zipcpu_fft.evaluate("ofdm_tx64_q1024")
    (out / "zipcpu_ofdm_tx64_q1024.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    print("zipcpu done", flush=True)
for name in ("real_r32_narrow", "dev_r32_narrow"):
    r = usrp.evaluate_spec(name)
    (out / f"usrp_{name}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    print("usrp", name, r["best"]["margin"], r["ppa"].get("area_um2"), flush=True)
