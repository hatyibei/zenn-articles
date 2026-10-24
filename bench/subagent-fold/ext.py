"""追加実験 (レビュー対応). usage: python ext.py {serial|a2|a1|hard}
- serial: 全12タスク×A/B各1回を完全直列で実行(並列実行・リトライによるレイテンシ汚染の確認)
- a2: A''(部分的に畳んだ構成: オーケストレーターが get_order を持ち shipping は専門エージェント)を連鎖系タスクで各3回
- a1: A'(returns担当にも get_shipment を付与)を返品系タスクで各3回
- hard: 罠を難しくしたアブレーション(古い見込み日を未来日 10/26 に、スキルから get_shipment へのヒントを全削除)
結果は results/ext_runs.jsonl に追記。累計 $1.9 を超えたら新規実行を止める。"""
import json, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import bench
from run import det_checks, date_re  # run.py は __main__ ガード付き
src = open("regrade.py").read().split("def regrade(")[0]; G = {}; exec(src, G)   # grader v2 (3回多数決)
TASKS = {t["id"]: t for t in json.load(open("tasks.json"))}
OUT = "results/ext_runs.jsonl"; LIMIT = 1.9; lock = threading.Lock()
def spent():
    try: return sum(json.loads(l)["cost_usd"] + json.loads(l).get("grader_cost", 0) for l in open(OUT))
    except FileNotFoundError: return 0.0
def go(exp, arch, tid, rep, grade=True, extra=None):
    if spent() > LIMIT: print("BUDGET STOP"); return
    t = TASKS[tid]
    r = bench.run_single(t["user"]) if arch == "B" else bench.run_multi(t["user"], variant=arch)
    rec = dict(exp=exp, arch=arch, task=tid, rep=rep, **{k: v for k, v in r.items() if k != "system_prompt"},
               api_calls=len(r["calls"]), cost_usd=bench.cost(r["calls"]), stop_reasons=[c["stop_reason"] for c in r["calls"]],
               retry_stats_snapshot=dict(bench.RETRY_STATS), **det_checks(t, r), **(extra or {}))
    if grade:
        gs, calls = zip(*[G["grade_once"](t, r["answer"]) for _ in range(3)])
        votes = sum(bool(g.get("pass")) for g in gs)
        rec["grade"] = dict(score=sum(g.get("score", 0) for g in gs) / 3, pass_votes=votes, samples=list(gs), **{"pass": votes >= 2})
        rec["grader_cost"] = bench.cost(list(calls)); rec["success"] = bool(rec["det_pass"] and votes >= 2)
    with lock:
        open(OUT, "a").write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        print(f"{exp:7s} {arch:3s} {tid} r{rep} lat={r['latency']:.1f}s ${rec['cost_usd']:.4f} det={rec['det_pass']} "
              f"ok={rec.get('success')} retries={bench.RETRY_STATS['retries']} spent=${spent():.3f}", flush=True)
exp = sys.argv[1]
if exp == "serial":
    for tid in TASKS:
        for arch in ("A", "B"): go("serial", arch, tid, 0)
elif exp in ("a2", "a1"):
    arch = "A2" if exp == "a2" else "A1"
    tids = ["T02", "T03", "T04", "T05", "T10", "T11"] if exp == "a2" else ["T04", "T03"]
    jobs = [(tid, rep) for rep in range(3) for tid in tids]
    with ThreadPoolExecutor(3) as ex: list(ex.map(lambda j: go(exp, arch, j[0], j[1]), jobs))
elif exp == "hard":
    bench.DATA["orders"]["A1002"]["estimated_delivery_at_order_time"] = "2026-10-26"   # 「今日」ではなく未来の古い見込み日
    bench.SKILLS["orders"] = "\n".join(l for l in bench.SKILLS["orders"].splitlines() if "estimated_delivery_at_order_time" not in l and "配達完了日は配送情報" not in l)
    bench.SKILLS["shipping"] = bench.SKILLS["shipping"].replace("お届け予定日・配送状況・配達完了日は get_shipment(tracking_number) の結果を唯一の正とする。追跡番号は注文情報(get_order)から取得する。", "配送状況は get_shipment(tracking_number) で確認できる。")
    bench.SKILLS["returns"] = bench.SKILLS["returns"].replace("と配達完了日を確認する", "を確認する").replace("(get_shipment の delivered_at)", "")
    assert "get_shipment" not in bench.SKILLS["returns"] and "estimated_delivery" not in bench.SKILLS["orders"]
    json.dump({k: bench.SKILLS[k] for k in ("orders", "shipping", "returns")}, open("results/hard_ablation_skills.json", "w"), ensure_ascii=False, indent=1)
    def hard(arch, tid, rep):
        go("hard", arch, tid, rep, grade=False)
    jobs = [(a, "T02", r) for r in range(5) for a in ("B", "A", "A2")] + [(a, "T03", r) for r in range(5) for a in ("B", "A2")]
    with ThreadPoolExecutor(3) as ex: list(ex.map(lambda j: hard(*j), jobs))
print("retry stats", bench.RETRY_STATS, "spent total $%.3f" % spent())
