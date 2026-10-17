import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dspgen.baselines import zipcpu_fft
r = zipcpu_fft.evaluate("ofdm_tx64_gen")
Path(__file__).with_name("zipcpu_ofdm_tx64_gen.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
print(json.dumps({k: {kk: v[kk] for kk in ("search_margin_db", "holdout_passed", "stat_failures", "ppa")} for k, v in r.items()}, ensure_ascii=False, default=str))
