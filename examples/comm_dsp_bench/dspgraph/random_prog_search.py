"""非 LLM 对照：对 build 程序做随机数值字面量变异的进化搜索（与 LLM diff 进化同起点、同评价次数）。

变异只改程序里的数字（表长、位宽、抽头/衰减指标、系数位数、增益等），不能改结构；
这是“不借助领域知识、在同一程序表示上搜索”的基线。结构性变异需要人工写变换算子，不属于本基线。

python -m dspgraph.random_prog_search OUT.json --specs dev --seeds 0,1 --budget 120 --jobs 2
"""
import argparse, ast, json, math, random, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .rtl_judge import evaluate_program
from .rx_spec import DEV_SPECS

SEED = Path(__file__).resolve().parent / "seeds/naive.py"


def literals(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            out.append(n)
    return out


def mutate(code, rng):
    tree = ast.parse(code)
    lits = literals(tree)
    for _ in range(1 if rng.random() < 0.6 else 2):
        n = rng.choice(lits)
        v = n.value
        if isinstance(v, int):
            n.value = max(0, rng.choice([v - 1, v + 1, v - 2, v + 2, v * 2, v // 2]))
        else:
            n.value = round(v * rng.choice([0.7, 0.85, 1.15, 1.4]), 6)
    return ast.unparse(tree)


SWAP = {"add": "sub", "sub": "add", "reg": "reg"}
KW_CHOICES = {"share": [1, 2, 4, 8, 16, 32], "ovf": ["sat", "wrap"], "rnd": ["round", "trunc"],
              "coef_bits": list(range(8, 25)), "phase": [0, 1, 2, 3]}


def _g_calls(tree):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "g"]


def _build_body(tree):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "build":
            return n
    return None


def mutate_struct(code, rng):
    """随机原语级结构变异（无领域知识）：删除/复制语句、包一层 g.q、改关键字参数、互换同签名原语、数值变异。"""
    tree = ast.parse(code)
    op = rng.choice(["num", "num", "wrap_q", "kw", "swap", "delete", "duplicate"])
    calls = _g_calls(tree)
    fn = _build_body(tree)
    if op == "num" or not calls or fn is None:
        return mutate(code, rng)
    if op == "wrap_q":
        c = rng.choice([c for c in calls if c.func.attr not in ("output", "scope", "input")] or calls)
        w = rng.randint(10, 26)
        d = rng.randint(-2, 4)
        lam = ast.parse(f"(lambda _t: g.q(_t, {w}, _t.f - {d}))(0)", mode="eval").body
        lam.args[0] = ast.Call(func=c.func, args=c.args, keywords=c.keywords)
        c.func, c.args, c.keywords = lam.func, lam.args, []
    elif op == "kw":
        c = rng.choice(calls)
        k = rng.choice(list(KW_CHOICES))
        c.keywords = [kw for kw in c.keywords if kw.arg != k] + \
            [ast.keyword(arg=k, value=ast.Constant(rng.choice(KW_CHOICES[k])))]
    elif op == "swap":
        cs = [c for c in calls if c.func.attr in SWAP]
        if not cs:
            return mutate(code, rng)
        c = rng.choice(cs)
        c.func.attr = SWAP[c.func.attr]
    else:
        stmts = []
        for parent in ast.walk(fn):
            for field in ("body", "orelse"):
                lst = getattr(parent, field, None)
                if isinstance(lst, list):
                    for i, st in enumerate(lst):
                        if isinstance(st, (ast.Assign, ast.Expr)) and "output" not in ast.unparse(st):
                            stmts.append((lst, i))
        if not stmts:
            return mutate(code, rng)
        lst, i = rng.choice(stmts)
        if op == "delete" and len(lst) > 1:
            lst.pop(i)
        else:
            lst.insert(i, ast.parse(ast.unparse(lst[i])).body[0])
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def key(r):
    if not r["valid"]:
        return (2, 0)
    q = r["quality"]
    if q["passed"]:
        return (0, r["area"])
    return (1, max(0, -q["snr_margin_db"]) + 3 * max(0, q["ripple_db"] - q["ripple_max_db"]) / q["ripple_max_db"])


def one(args):
    spec, seed, budget, kind = args
    mut = mutate_struct if kind == "struct" else mutate
    rng = random.Random(seed * 9973 + 5)
    t0 = time.time()
    base = SEED.read_text()
    r0 = evaluate_program(base, spec)
    pop = [(base, r0)]
    seen = {base}
    curve, used, npass, ninv = [], 0, 0, 0
    best = r0["area"]
    while used < budget:
        pop.sort(key=lambda cr: key(cr[1]))
        parent = rng.choice(pop[: max(3, len(pop) // 2)])[0]
        try:
            child = mut(parent, rng)
        except Exception:
            continue
        if child in seen:
            continue
        seen.add(child)
        r = evaluate_program(child, spec)
        used += 1
        if r["valid"] and r["quality"]["passed"]:
            npass += 1
            best = min(best, r["area"])
        elif not r["valid"]:
            ninv += 1
        curve.append(best)
        pop.append((child, r))
        pop.sort(key=lambda cr: key(cr[1]))
        pop = pop[:16]
    bc = min((c for c in pop if c[1]["valid"] and c[1]["quality"]["passed"]), key=lambda c: c[1]["area"])
    return {"spec": spec, "seed": seed, "budget": budget, "mutation": kind, "naive_area": r0["area"], "best_area": best,
            "rel": best / r0["area"], "passed_evals": npass, "invalid_evals": ninv, "curve": curve,
            "best_code": bc[0], "seconds": time.time() - t0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--budget", type=int, default=120)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--kind", default="numeric", choices=["numeric", "struct"])
    a = ap.parse_args()
    tasks = [(s.name, int(sd), a.budget, a.kind) for sd in a.seeds.split(",") for s in DEV_SPECS]
    rows = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for r in ex.map(one, tasks):
            rows.append(r)
            a.out.write_text(json.dumps(rows, indent=1, default=float))
            print(r["spec"], r["seed"], round(r["rel"], 4), r["passed_evals"], r["invalid_evals"], flush=True)


if __name__ == "__main__":
    main()
