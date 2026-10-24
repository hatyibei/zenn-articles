"""results/ext_runs.jsonl -> results/ext_summary.json / ext_runs.csv (追加実験の集計)"""
import json, re, csv, statistics as st, collections
R = [json.loads(l) for l in open("results/ext_runs.jsonl")]
out = collections.defaultdict(dict)
for (exp, arch, task), g in sorted({(r["exp"], r["arch"], r["task"]): None for r in R}.items()):
    G = [r for r in R if (r["exp"], r["arch"], r["task"]) == (exp, arch, task)]
    out[exp][f"{arch}/{task}"] = dict(
        n=len(G), success=sum(bool(r.get("success")) for r in G) if exp != "hard" else None, det_pass=sum(r["det_pass"] for r in G),
        called_get_shipment=sum(any(t["name"] == "get_shipment" for t in r["tools"]) for r in G),
        latency=[round(r["latency"], 2) for r in G], cost_mean=round(st.mean(r["cost_usd"] for r in G), 5),
        routed_or_skills=[r["routed"] or r["skills"] for r in G], stop_reasons=dict(collections.Counter(s for r in G for s in r["stop_reasons"])))
out["_spend"] = dict(agents=round(sum(r["cost_usd"] for r in R), 4), grader=round(sum(r.get("grader_cost", 0) for r in R), 4),
                     retries=max((r["retry_stats_snapshot"]["retries"] for r in R), default=0))
json.dump(out, open("results/ext_summary.json", "w"), ensure_ascii=False, indent=1)
with open("results/ext_runs.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["exp", "arch", "task", "rep", "success", "det_pass", "latency_s", "api_calls", "cost_usd", "routed_or_skills", "tools_called"])
    for r in R: w.writerow([r["exp"], r["arch"], r["task"], r["rep"], r.get("success"), r["det_pass"], round(r["latency"], 2), r["api_calls"], round(r["cost_usd"], 5),
                            "|".join(r["routed"] or r["skills"]), "|".join(t["agent"] + ":" + t["name"] for t in r["tools"])])
print(json.dumps(out["_spend"]))
