"""独立进程中执行候选 build 程序（定点解释），按 Task 打分。协议与 dspgraph.sdf_worker 相同。"""
import json, math, sys, traceback


def main():
    req = json.loads(sys.stdin.read())
    import numpy as np, scipy, scipy.signal
    from dspgraph.sdf import BuildError
    from .graph import TaskGraph
    from .task import get
    task = get(req["task"])
    idxs = req["scenarios"]
    x = np.stack([task.scene(i)["x_codes"] for i in idxs])
    xq = np.stack([task.scene(i)["xq_codes"] for i in idxs]) if task.iface("in_kind") == "complex" else None
    scopes = req.get("extra_scopes")
    spec = task.spec()
    g = TaskGraph(spec, x, xq, in_kind=task.iface("in_kind"), out_kind=task.iface("out_kind"),
                  in_period=task.iface("in_period"), out_period=task.iface("out_period"),
                  extra_bits=req.get("extra_bits", 0), extra_scopes=set(scopes) if scopes is not None else None)
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "__name__": "candidate"}
    try:
        exec(compile(req["code"], "<candidate>", "exec"), env)
        if "build" not in env:
            raise BuildError("structure", "program must define build(g, spec)")
        env["build"](g, spec)
        if g.y is None:
            raise BuildError("structure", "build() never called g.output(...)")
        out = {"ok": True, "area": g.area(), "stats": g.stats, "saturation": g.sat,
               "scores": [task.score(i, g.y[k]) for k, i in enumerate(idxs)]}
        if req.get("want_verilog"):
            out["verilog"] = g.verilog()
            yy = np.asarray(g.y)
            out["outputs"] = {str(i): [yy[k].real.tolist(), yy[k].imag.tolist()] for k, i in enumerate(idxs)}
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
