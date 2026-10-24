"""Run all tasks x N repeats x 2 architectures, grade, save raw JSONL. Usage: python run.py N"""
import json, re, sys, time, random, threading
from concurrent.futures import ThreadPoolExecutor
import bench

GRADER_MODEL = "claude-haiku-5-5"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
BUDGET_STOP = 3.5
TASKS = json.load(open("tasks.json"))
OUT = "results/runs.jsonl"
lock = threading.Lock(); spent = [0.0]

def date_re(iso):
    y, m, d = iso.split("-"); m, d = int(m), int(d)
    return rf"({y}年\s*)?{m}月\s*{d}日|{m}/{d}(?!\d)|{y}-{m:02d}-{d:02d}|{y}/{m:02d}/{d:02d}|{y}/{m}/{d}(?!\d)"
def expand(p): return re.sub(r"\{date:([\d-]+)\}", lambda m: f"(?:{date_re(m.group(1))})", p)

def det_checks(task, run):
    names = [t["name"] for t in run["tools"]]
    missing = [t for t in task["required_tools"] if t not in names]
    miss_pat = [p for p in task["must"] if not re.search(expand(p), run["answer"])]
    bad_pat = [p for p in task["must_not"] if re.search(expand(p), run["answer"])]
    # rule: no customer data tool (get_order/get_account) before a successful verify_customer
    verified = False; order_violation = False
    for t in sorted(run["tools"], key=lambda x: x["t"]):
        if t["name"] == "verify_customer" and t["result"].get("verified"): verified = True
        if t["name"] in ("get_order", "get_account") and not verified: order_violation = True
    return dict(missing_tools=missing, missing_patterns=miss_pat, forbidden_patterns=bad_pat, verify_order_violation=order_violation,
                det_pass=not (missing or miss_pat or bad_pat))

GRADER_SYS = """あなたはカスタマーサポート回答の採点者です。ルーブリックに厳密に従って採点し、JSONのみを出力してください。
最初にJSONを出力し、それ以外は書かないこと。出力形式: {"score": 1-5の整数, "pass": true/false, "reason": "日本語で1-2文"}
基準: 5=ルーブリックの必須事項をすべて正確に満たし不要な誤りなし / 4=必須事項を満たすが軽微な不足 / 3=重要事項の一部欠落 / 2=重大な誤り / 1=誤答・ルール違反。
pass は score>=4 かつ ルーブリックの「不合格」条件に該当しない場合のみ true。
回答がルーブリックにない情報を含む場合、下記の参照データ(システムの正しいデータ)と矛盾しなければ減点しない。矛盾する場合や参照データにない事実の捏造は減点する。
## 参照データ(今日は2026-10-24)
""" + open("data.json").read()
def grade(task, answer):
    prompt = f"## 顧客の質問\n{task['user']}\n\n## ルーブリック(正解情報)\n{task['rubric']}\n\n## 採点対象の回答\n{answer}"
    for _ in range(3):
        t = time.time()
        r = bench.client.messages.create(model=GRADER_MODEL, max_tokens=1500, system=GRADER_SYS, messages=[{"role": "user", "content": prompt}])
        call = dict(agent="grader", model=GRADER_MODEL, input=r.usage.input_tokens, output=r.usage.output_tokens,
                    cache_write=r.usage.cache_creation_input_tokens or 0, cache_read=r.usage.cache_read_input_tokens or 0, sec=time.time() - t)
        txt = "".join(b.text for b in r.content if b.type == "text")
        m = re.search(r"\{.*\}", txt, re.S)
        try: return json.loads(m.group(0)), call
        except Exception: continue
    return {"score": 0, "pass": False, "reason": "grader parse error"}, call

def job(arch, task, rep):
    if spent[0] > BUDGET_STOP: return
    f = bench.run_single if arch == "B_single" else bench.run_multi
    try: run = f(task["user"])
    except Exception as e: run = dict(answer=f"(error {e!r})", latency=None, turns=0, skills=[], routed=[], calls=[], tools=[], error=repr(e))
    g, gcall = grade(task, run["answer"])
    rec = dict(arch=arch, task=task["id"], type=task["type"], rep=rep, model=bench.AGENT_MODEL, **run,
               api_calls=len(run["calls"]), cost_usd=bench.cost(run["calls"]), grade=g, grader_call=gcall,
               grader_cost=bench.cost([gcall]), **det_checks(task, run))
    rec["success"] = bool(rec["det_pass"] and g.get("pass"))
    with lock:
        spent[0] += rec["cost_usd"] + rec["grader_cost"]
        with open(OUT, "a") as fh: fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        print(f"{arch:9s} {task['id']} r{rep} lat={rec['latency'] and round(rec['latency'],1)}s calls={rec['api_calls']} "
              f"${rec['cost_usd']:.4f} det={rec['det_pass']} g={g.get('score')} ok={rec['success']} total=${spent[0]:.3f}", flush=True)

jobs = [(a, t, r) for r in range(N) for t in TASKS for a in ("A_multi", "B_single")]
random.seed(0); random.shuffle(jobs)
with ThreadPoolExecutor(4) as ex: list(ex.map(lambda j: job(*j), jobs))
print("TOTAL SPENT (agents+grader) $%.3f" % spent[0])
