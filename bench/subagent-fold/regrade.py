"""Grader v2: reference = data.json + skill texts (v1 lacked skills -> false 'fabrication' flags). 3 samples per answer, majority pass."""
import json, re, time, collections
from concurrent.futures import ThreadPoolExecutor
import bench
GRADER_MODEL = "claude-haiku-5-5"; K = 3
TASKS = {t["id"]: t for t in json.load(open("tasks.json"))}
REF = open("data.json").read() + "\n\n## 業務手順(スキル。エージェントに与えられている正しい社内ルール)\n" + "\n".join(bench.SKILLS.values())
GRADER_SYS = """あなたはカスタマーサポート回答の採点者です。ルーブリックに厳密に従って採点してください。
最初にJSONを出力し、それ以外は書かないこと。出力形式: {"score": 1-5の整数, "pass": true/false, "reason": "日本語で1-2文"}
基準: 5=ルーブリックの必須事項をすべて正確に満たし不要な誤りなし / 4=必須事項を満たすが軽微な不足 / 3=重要事項の一部欠落 / 2=重大な誤り / 1=誤答・ルール違反。
pass は score>=4 かつ ルーブリックの「不合格」条件に該当しない場合のみ true。
回答がルーブリックにない情報を含む場合、下記の参照データ・業務手順と矛盾しなければ減点しない。矛盾する場合や参照データにない事実の捏造は減点する。
顧客のメールアドレスと注文番号(または電話番号下4桁)が参照データ上で一致する場合、「本人確認ができました」という記述は正しい。
## 参照データ(今日は2026-10-24)
""" + REF
def grade_once(task, answer):
    prompt = f"## 顧客の質問\n{task['user']}\n\n## ルーブリック(正解情報)\n{task['rubric']}\n\n## 採点対象の回答\n{answer}"
    for _ in range(3):
        t = time.time()
        r = bench.client.messages.create(model=GRADER_MODEL, max_tokens=1500, system=GRADER_SYS, messages=[{"role": "user", "content": prompt}])
        call = dict(agent="grader", model=GRADER_MODEL, input=r.usage.input_tokens, output=r.usage.output_tokens,
                    cache_write=r.usage.cache_creation_input_tokens or 0, cache_read=r.usage.cache_read_input_tokens or 0, sec=time.time() - t)
        m = re.search(r"\{.*\}", "".join(b.text for b in r.content if b.type == "text"), re.S)
        try: return json.loads(m.group(0)), call
        except Exception: pass
    return {"score": 0, "pass": False, "reason": "parse error"}, call
def regrade(rec):
    gs, calls = zip(*[grade_once(TASKS[rec["task"]], rec["answer"]) for _ in range(K)])
    rec["grade_v1"] = rec["grade"]
    passes = sum(bool(g.get("pass")) for g in gs)
    rec["grade"] = dict(score=sum(g.get("score", 0) for g in gs) / K, **{"pass": passes * 2 > K}, pass_votes=passes, samples=list(gs))
    rec["grader_calls_v2"] = list(calls); rec["grader_cost_v2"] = bench.cost(list(calls))
    rec["success"] = bool(rec["det_pass"] and rec["grade"]["pass"])
    return rec
if __name__ == "__main__":
    recs = [json.loads(l) for l in open("results/runs_grader_v1.jsonl")]
    with ThreadPoolExecutor(6) as ex: recs = list(ex.map(regrade, recs))
    open("results/runs.jsonl", "w").write("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in recs))
    print("grader v2 cost $%.4f" % sum(r["grader_cost_v2"] for r in recs))
    print("v1 vs v2 pass flips:", collections.Counter((r["arch"], bool(r["grade_v1"].get("pass")), r["grade"]["pass"]) for r in recs))
