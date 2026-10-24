"""Ablation: remove the 'order-time estimate is stale, always check get_shipment' hints from skills, rerun T02 (delivery date) x5 per arch.
Tests whether the article's failure (answering from order lookup alone, skipping delivery date) appears when the skill doesn't spell it out."""
import json, re
from concurrent.futures import ThreadPoolExecutor
import bench
bench.SKILLS["orders"] = "\n".join(l for l in bench.SKILLS["orders"].splitlines() if "estimated_delivery_at_order_time" not in l and "配達完了日は配送情報" not in l)
bench.SKILLS["shipping"] = bench.SKILLS["shipping"].replace("お届け予定日・配送状況・配達完了日は get_shipment(tracking_number) の結果を唯一の正とする。追跡番号は注文情報(get_order)から取得する。", "配送状況は get_shipment(tracking_number) で確認できる。")
T = {t["id"]: t for t in json.load(open("tasks.json"))}["T02"]
def job(a):
    r = (bench.run_single if a == "B_single" else bench.run_multi)(T["user"])
    ans = r["answer"]
    return dict(arch=a, latency=r["latency"], cost=bench.cost(r["calls"]), called_get_shipment=any(t["name"] == "get_shipment" for t in r["tools"]),
                says_1028=bool(re.search(r"10月\s*28日|10/28|2026-10-28", ans)), skills=r["skills"], routed=r["routed"], tools=[t["agent"]+":"+t["name"] for t in r["tools"]], answer=ans)
with ThreadPoolExecutor(4) as ex: out = list(ex.map(job, ["A_multi", "B_single"] * 5))
json.dump(dict(orders_skill=bench.SKILLS["orders"], shipping_skill=bench.SKILLS["shipping"], runs=out), open("results/ablation_T02.json", "w"), ensure_ascii=False, indent=1)
for a in ["A_multi", "B_single"]:
    R = [o for o in out if o["arch"] == a]
    print(a, "get_shipment", sum(o["called_get_shipment"] for o in R), "/", len(R), "correct 10/28", sum(o["says_1028"] for o in R), "lat", round(sum(o["latency"] for o in R)/len(R),1), "cost $%.4f" % (sum(o["cost"] for o in R)/len(R)))
print("total $%.4f" % sum(o["cost"] for o in out))
