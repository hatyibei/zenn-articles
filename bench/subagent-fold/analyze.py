import json, statistics as st, csv, collections
import bench
recs = [json.loads(l) for l in open("results/runs.jsonl")]
TASKS = {t["id"]: t for t in json.load(open("tasks.json"))}
ARCHS = ["A_multi", "B_single"]
def m(x): return sum(x) / len(x) if x else float("nan")
def p(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]
def nocache_cost(calls):
    return sum((c["input"] + c["cache_write"] + c["cache_read"]) * bench.PRICES[c["model"]]["inp"] / 1e6 + c["output"] * bench.PRICES[c["model"]]["out"] / 1e6 for c in calls)
for r in recs:
    exp = set(TASKS[r["task"]]["expected_skills"])
    got = set(r["skills"] if r["arch"] == "B_single" else r["routed"])
    r["route_ok"] = exp <= got
    r["route_extra"] = len(got - exp)
    core = (exp - {"orders"}) or exp   # orders tools (get_order) are shared by shipping/returns specialists
    r["route_core_ok"] = core <= got
    r["tools_ok"] = not r["missing_tools"]
    r["in_total"] = sum(c["input"] + c["cache_write"] + c["cache_read"] for c in r["calls"])
    r["out_total"] = sum(c["output"] for c in r["calls"])
    r["cost_nocache"] = nocache_cost(r["calls"])
    r["n_tool_calls"] = len(r["tools"])
summary = {}
for a in ARCHS:
    R = [r for r in recs if r["arch"] == a]
    L = [r["latency"] for r in R if r["latency"]]
    summary[a] = dict(
        runs=len(R), success_rate=m([r["success"] for r in R]), det_pass_rate=m([r["det_pass"] for r in R]),
        grader_pass_rate=m([bool(r["grade"].get("pass")) for r in R]), grader_score_mean=m([r["grade"].get("score", 0) for r in R]),
        latency_mean=m(L), latency_median=st.median(L), latency_p90=p(L, 0.9),
        api_calls_mean=m([r["api_calls"] for r in R]), data_tool_calls_mean=m([r["n_tool_calls"] for r in R]),
        input_tokens_mean=m([r["in_total"] for r in R]), output_tokens_mean=m([r["out_total"] for r in R]),
        cost_mean=m([r["cost_usd"] for r in R]), cost_total=sum(r["cost_usd"] for r in R),
        cost_nocache_mean=m([r["cost_nocache"] for r in R]),
        route_or_skill_acc=m([r["route_ok"] for r in R]), route_extra_mean=m([r["route_extra"] for r in R]), route_core_acc=m([r["route_core_ok"] for r in R]),
        required_tools_acc=m([r["tools_ok"] for r in R]), verify_violation=sum(r["verify_order_violation"] for r in R),
        errors=sum(1 for r in R if r.get("error")))
grader_total = sum(r["grader_cost"] + r.get("grader_cost_v2", 0) for r in recs)
per_task = collections.defaultdict(dict)
for t in TASKS:
    for a in ARCHS:
        R = [r for r in recs if r["arch"] == a and r["task"] == t]
        per_task[t][a] = dict(ok=sum(r["success"] for r in R), n=len(R), score=m([r["grade"].get("score", 0) for r in R]),
                              lat=m([r["latency"] for r in R if r["latency"]]), cost=m([r["cost_usd"] for r in R]),
                              det_fail=[(r["rep"], r["missing_tools"], r["missing_patterns"], r["forbidden_patterns"]) for r in R if not r["det_pass"]],
                              grade_fail=[(r["rep"], r["grade"].get("score"), r["grade"].get("pass_votes"), [g.get("reason") for g in r["grade"].get("samples", [])]) for r in R if not r["grade"].get("pass")],
                              route=[sorted(r["skills"] if a == "B_single" else r["routed"]) for r in R])
by_type = {a: {ty: m([r["success"] for r in recs if r["arch"] == a and r["type"] == ty]) for ty in ["single", "chain", "rule"]} for a in ARCHS}
json.dump(dict(summary=summary, grader_cost_total=grader_total, by_type=by_type, per_task=per_task), open("results/summary.json", "w"), ensure_ascii=False, indent=1)
with open("results/runs.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["arch", "task", "type", "rep", "success", "det_pass", "grader_score", "grader_pass", "latency_s", "api_calls", "data_tool_calls",
                "input_tokens_total", "output_tokens", "cost_usd", "cost_nocache_usd", "route_ok", "skills_or_agents", "tools_called", "missing_tools", "missing_patterns", "forbidden_patterns"])
    for r in sorted(recs, key=lambda r: (r["task"], r["arch"], r["rep"])):
        w.writerow([r["arch"], r["task"], r["type"], r["rep"], r["success"], r["det_pass"], r["grade"].get("score"), r["grade"].get("pass"),
                    round(r["latency"], 2) if r["latency"] else "", r["api_calls"], r["n_tool_calls"], r["in_total"], r["out_total"],
                    round(r["cost_usd"], 5), round(r["cost_nocache"], 5), r["route_ok"], "|".join(r["skills"] or r["routed"]),
                    "|".join(t["agent"] + ":" + t["name"] for t in r["tools"]), "|".join(r["missing_tools"]), "|".join(r["missing_patterns"]), "|".join(r["forbidden_patterns"])])
print(json.dumps(summary, indent=1, ensure_ascii=False)); print("grader total $%.4f" % grader_total); print(json.dumps(by_type, ensure_ascii=False))
for t, d in per_task.items():
    print(t, TASKS[t]["type"], {a: f"{d[a]['ok']}/{d[a]['n']} s={d[a]['score']:.1f} lat={d[a]['lat']:.1f} ${d[a]['cost']:.4f}" for a in ARCHS})
    for a in ARCHS:
        if d[a]["det_fail"] or d[a]["grade_fail"]: print("   ", a, d[a]["det_fail"], d[a]["grade_fail"])
        print("    route", a, d[a]["route"])

import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 4, figsize=(14, 3.6))
lab = ["A: orchestrator+subagents", "B: single loop+skills"]; col = ["#d9822b", "#2b7bd9"]
for i, (k, title) in enumerate([("success_rate", "Strict rubric success rate"), ("grader_score_mean", "Mean rubric score (1-5)"), ("latency_mean", "Mean latency [s]"), ("cost_mean", "Mean cost / task [USD]")]):
    v = [summary[a][k] for a in ARCHS]; ax[i].bar(["A", "B"], v, color=col); ax[i].set_title(title)
    for j, x in enumerate(v): ax[i].text(j, x, f"{x:.3f}" if k == "cost_mean" else f"{x:.2f}", ha="center", va="bottom")
fig.suptitle(f"Mock EC support agent (mock tools, zero tool latency), 12 tasks x 3 runs, {bench.AGENT_MODEL}. A=orchestrator+subagents, B=single loop+skills. Per-task cost excludes grader.", fontsize=9)
plt.tight_layout(); plt.savefig("comparison.png", dpi=130)
