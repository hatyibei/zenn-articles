"""Single-loop (skills) vs orchestrator+subagents benchmark on a mock EC support domain.
Author: 八兵衛 (hathibei7). API key is read from env by the SDK and never logged."""
import json, time, threading, os
from concurrent.futures import ThreadPoolExecutor
import anthropic

AGENT_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 2048
# USD / MTok (https://docs.claude.com/en/docs/about-claude/pricing, 2026-10-24 閲覧)
PRICES = {
    "claude-sonnet-5-5": dict(inp=2.0, out=10.0, cw=2.5, cr=0.10),
    "claude-haiku-5-5": dict(inp=0.10, out=0.50, cw=0.125, cr=0.01),
}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(f"{HERE}/data.json"))
SKILLS = {n: open(f"{HERE}/skills/{n}.md").read() for n in ["orders", "shipping", "returns", "products", "account"]}
SKILL_DESC = {
    "orders": "注文の照会・注文ステータス・本人確認の手順",
    "shipping": "お届け予定日・配送状況・配達完了日・配送先変更",
    "returns": "返品・返金・交換・破損対応、返品期限の計算",
    "products": "商品の在庫・入荷予定・バリエーション",
    "account": "ポイント残高・会員ランク・登録情報",
}
client = anthropic.Anthropic(max_retries=6)

# ---------------- thin mock tools (deterministic) ----------------
def verify_customer(email, order_id=None, phone_last4=None):
    for cid, c in DATA["customers"].items():
        if c["email"].lower() == str(email).lower():
            if order_id and DATA["orders"].get(order_id, {}).get("customer_id") == cid:
                return {"verified": True, "customer_id": cid, "name": c["name"]}
            if phone_last4 and c["phone_last4"] == str(phone_last4):
                return {"verified": True, "customer_id": cid, "name": c["name"]}
    return {"verified": False, "message": "本人確認に失敗しました。メールアドレスと注文番号(または電話番号下4桁)が一致しません。"}

def get_order(order_id, customer_id):
    o = DATA["orders"].get(order_id)
    if not o or o["customer_id"] != customer_id:
        return {"error": "注文が見つからないか、この顧客の注文ではありません。先に verify_customer で本人確認してください。"}
    return {"order_id": order_id, **o}

def get_shipment(tracking_number):
    s = DATA["shipments"].get(tracking_number)
    return {"tracking_number": tracking_number, **s} if s else {"error": "追跡番号が見つかりません"}

def get_return_policy(category):
    p = DATA["return_policies"]
    return {"category": category, "policy": p.get(category, "該当カテゴリなし"), "general_rule": p["general"]}

def check_inventory(query):
    q = str(query).lower().replace(" ", "")
    hits = {k: v for k, v in DATA["inventory"].items() if q in k.lower() or q in v["name"].lower().replace(" ", "")
            or any(t and t in v["name"].lower().replace(" ", "") for t in [q.replace("ブラック", ""), q.replace("ホワイト", "")] if len(t) >= 2)}
    return {"results": hits} if hits else {"results": {}, "message": "該当商品なし。商品名の一部やSKUで再検索してください。"}

def get_account(customer_id):
    c = DATA["customers"].get(customer_id)
    if not c: return {"error": "顧客が見つかりません"}
    return {k: v for k, v in c.items() if k not in ("phone_last4",)} | {"customer_id": customer_id}

TOOL_IMPL = dict(verify_customer=verify_customer, get_order=get_order, get_shipment=get_shipment,
                 get_return_policy=get_return_policy, check_inventory=check_inventory, get_account=get_account)
S = lambda props, req: {"type": "object", "properties": props, "required": req}
TOOL_DEFS = {
    "verify_customer": {"name": "verify_customer", "description": "本人確認。email と order_id または phone_last4 を照合し customer_id を返す。",
        "input_schema": S({"email": {"type": "string"}, "order_id": {"type": "string"}, "phone_last4": {"type": "string"}}, ["email"])},
    "get_order": {"name": "get_order", "description": "注文情報(ステータス・商品・カテゴリ・final_sale・配送業者・追跡番号)を取得。",
        "input_schema": S({"order_id": {"type": "string"}, "customer_id": {"type": "string"}}, ["order_id", "customer_id"])},
    "get_shipment": {"name": "get_shipment", "description": "追跡番号から配送状況・最新お届け予定日・配達完了日を取得。",
        "input_schema": S({"tracking_number": {"type": "string"}}, ["tracking_number"])},
    "get_return_policy": {"name": "get_return_policy", "description": "返品ポリシーを取得。category: apparel / electronics / home / damaged",
        "input_schema": S({"category": {"type": "string", "enum": ["apparel", "electronics", "home", "damaged"]}}, ["category"])},
    "check_inventory": {"name": "check_inventory", "description": "商品名の一部またはSKUで在庫・入荷予定日を検索。",
        "input_schema": S({"query": {"type": "string"}}, ["query"])},
    "get_account": {"name": "get_account", "description": "顧客アカウント(ポイント・会員ランク・失効予定ポイント・住所)を取得。",
        "input_schema": S({"customer_id": {"type": "string"}}, ["customer_id"])},
}
BASE_RULES = f"""あなたはECショップ「ハチベエストア」のカスタマーサポートAIです。今日は {DATA['today']} です。
- 日本語で、丁寧かつ簡潔に回答する。事実はツールの結果のみに基づく。推測で日付や在庫を答えない。
- 本人確認前に注文・アカウント情報を開示しない。返品ポリシー確認前に返金を約束しない。
- このやり取りは1往復のみ。追加質問はせず、得られた情報で最終回答を書く(不足があれば何が必要かを回答内で案内する)。"""

# ---------------- generic tool loop ----------------
class Trace:
    def __init__(self): self.lock = threading.Lock(); self.calls = []; self.tools = []; self.usage = []
    def add_call(self, agent, model, u, dt):
        with self.lock:
            self.calls.append(dict(agent=agent, model=model, input=u.input_tokens, output=u.output_tokens,
                cache_write=u.cache_creation_input_tokens or 0, cache_read=u.cache_read_input_tokens or 0, sec=round(dt, 3)))
    def add_tool(self, agent, name, args, result):
        with self.lock: self.tools.append(dict(t=time.time(), agent=agent, name=name, args=args, result=result))

def run_loop(agent, system, tools, user, trace, extra_tools=None, max_turns=10, model=AGENT_MODEL):
    """One model, one context: model emits a batch of tool calls; harness runs them in parallel and returns raw results."""
    extra_tools = extra_tools or {}
    msgs = [{"role": "user", "content": user}]
    for turn in range(max_turns):
        t = time.time()
        r = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=system, tools=tools, messages=msgs,
                                   cache_control={"type": "ephemeral"})
        trace.add_call(agent, model, r.usage, time.time() - t)
        msgs.append({"role": "assistant", "content": r.content})
        uses = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not uses:
            return "".join(b.text for b in r.content if b.type == "text"), turn + 1
        def exec_one(b):
            fn = extra_tools.get(b.name) or TOOL_IMPL.get(b.name)
            try: res = fn(**b.input) if fn else {"error": f"unknown tool {b.name}"}
            except Exception as e: res = {"error": repr(e)}
            if b.name not in extra_tools: trace.add_tool(agent, b.name, b.input, res)
            return {"type": "tool_result", "tool_use_id": b.id, "content": res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)}
        with ThreadPoolExecutor(8) as ex: results = list(ex.map(exec_one, uses))
        msgs.append({"role": "user", "content": results})
    return "(turn budget exceeded)", max_turns

# ---------------- Architecture B: single loop + progressive disclosure (skills) ----------------
def run_single(user):
    trace = Trace(); loaded = []
    def load_skill(name):
        loaded.append(name); return SKILLS.get(name, f"unknown skill {name}")
    system = BASE_RULES + "\n\n## 利用可能なスキル(必要になったら load_skill で手順全文を読み込むこと)\n" + \
        "\n".join(f"- {k}: {v}" for k, v in SKILL_DESC.items())
    tools = list(TOOL_DEFS.values()) + [{"name": "load_skill", "description": "スキル(業務手順)の全文を読み込む。該当領域の作業前に読み込むこと。",
        "input_schema": S({"name": {"type": "string", "enum": list(SKILLS)}}, ["name"])}]
    t0 = time.time()
    ans, turns = run_loop("main", system, tools, user, trace, extra_tools={"load_skill": load_skill}, max_turns=12)
    return dict(answer=ans, latency=time.time() - t0, turns=turns, skills=loaded, routed=[], calls=trace.calls, tools=trace.tools)

# ---------------- Architecture A: orchestrator + specialist subagents ----------------
SPECIALIST_TOOLS = {  # org-chart split: each team owns its own tools
    "orders": ["verify_customer", "get_order"],
    "shipping": ["verify_customer", "get_order", "get_shipment"],
    "returns": ["verify_customer", "get_order", "get_return_policy"],
    "products": ["check_inventory"],
    "account": ["verify_customer", "get_account"],
}
def run_multi(user):
    trace = Trace(); routed = []
    def make_delegate(name):
        def delegate(request):
            routed.append(name)
            sys = BASE_RULES + f"\n\nあなたは「{name}」担当のスペシャリストです。オーケストレーターからの依頼に答え、結果を簡潔に要約して返してください。\n\n" + SKILLS[name]
            ans, _ = run_loop(f"sub:{name}", sys, [TOOL_DEFS[t] for t in SPECIALIST_TOOLS[name]], request, trace, max_turns=8)
            return ans
        return delegate
    system = BASE_RULES + "\n\nあなたはオーケストレーターです。自分ではデータを参照できません。以下の専門エージェントに依頼(ask_<name>)し、その回答をもとに顧客への最終回答を書いてください。依頼文には顧客のメール・注文番号など必要な情報をすべて含めること。複数のエージェントへ同時に依頼してもよい。\n" + \
        "\n".join(f"- ask_{k}: {v} (使えるツール: {', '.join(SPECIALIST_TOOLS[k])})" for k, v in SKILL_DESC.items())
    tools = [{"name": f"ask_{k}", "description": f"{k}担当エージェントに依頼する: {SKILL_DESC[k]}",
              "input_schema": S({"request": {"type": "string"}}, ["request"])} for k in SKILLS]
    extra = {f"ask_{k}": make_delegate(k) for k in SKILLS}
    t0 = time.time()
    ans, turns = run_loop("orchestrator", system, tools, user, trace, extra_tools=extra, max_turns=8)
    return dict(answer=ans, latency=time.time() - t0, turns=turns, skills=[], routed=routed, calls=trace.calls, tools=trace.tools)

def cost(calls):
    tot = 0.0
    for c in calls:
        p = PRICES[c["model"]]
        tot += (c["input"] * p["inp"] + c["output"] * p["out"] + c["cache_write"] * p["cw"] + c["cache_read"] * p["cr"]) / 1e6
    return tot
