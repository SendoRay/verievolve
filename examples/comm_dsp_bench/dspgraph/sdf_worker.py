"""在独立进程中执行一份 build 程序：构造电路、算出逐位输出、按裁判打分。

stdin : {"code", "spec", "scenarios": [...], "extra_bits", "extra_scopes", "want_verilog"}
stdout: {"ok": true, "outputs": {场景: [[re...],[im...]]}, "area", "stats", "saturation", "verilog"?}
     或 {"ok": false, "error": {...}}
"""

from __future__ import annotations

import json
import math
import sys
import traceback


def main():
    req = json.loads(sys.stdin.read())
    import numpy as np
    import scipy
    import scipy.signal

    from . import judge
    from .rx_spec import SPECS
    from .sdf import BuildError, Graph
    spec = SPECS[req["spec"]]
    idxs = req["scenarios"]
    x = np.stack([judge.scene(spec, i).x_codes for i in idxs])
    scopes = req.get("extra_scopes")
    g = Graph(spec, x, req.get("extra_bits", 0), set(scopes) if scopes is not None else None,
              auto_narrow=req.get("auto_narrow", False))
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "__name__": "candidate"}
    try:
        exec(compile(req["code"], "<candidate>", "exec"), env)
        if "build" not in env:
            raise BuildError("structure", "program must define build(g, spec)")
        env["build"](g, spec)
        if g.y is None:
            raise BuildError("structure", "build() never called g.output(i, q)")
        out = {"ok": True, "area": g.area(), "stats": g.stats, "saturation": g.sat,
               "scores": [judge.score(spec, i, g.y[k]) for k, i in enumerate(idxs)],
               "notes": sorted(set(g.notes))[:10]}
        if req.get("probes") and g.probes:
            out["probes"] = {name: judge.probe(spec, idxs[0], v[0], per) for name, v, per in g.probes}
        if req.get("want_verilog"):
            out["verilog"] = g.verilog()
            out["outputs"] = {str(i): [g.y[k].real.tolist(), g.y[k].imag.tolist()]
                              for k, i in enumerate(idxs)}
    except BuildError as e:
        out = {"ok": False, "error": e.as_dict()}
    except Exception as e:
        tb = traceback.extract_tb(sys.exc_info()[2])
        line = next((f.lineno for f in reversed(tb) if f.filename == "<candidate>"), None)
        out = {"ok": False, "error": {"code": "python_error", "line": line,
                                      "message": f"{type(e).__name__}: {str(e)[:400]}"}}
    sys.stdout.write(json.dumps(out, default=float))


if __name__ == "__main__":
    main()
