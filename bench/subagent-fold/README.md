# subagent-fold ベンチマーク

Anthropic の記事「Building agents: When to fold subagents into your main agent loop」の主張を、モックのECサポートエージェントで検証したコードです。

- A: オーケストレーター + 専門サブエージェント (`bench.run_multi`)
- B: シングルループ + スキル(progressive disclosure)(`bench.run_single`)

## 必要なもの

- Python 3.10+
- `pip install anthropic matplotlib`
- 環境変数 `ANTHROPIC_API_KEY`(コード内でキーを表示・保存することはありません)

## 実行方法

```bash
export ANTHROPIC_API_KEY=...        # 自分のキー
python run.py 3                     # 12タスク × 3回 × 2構成を実行し results/runs.jsonl に追記(採点v1込み)
python regrade.py                   # 採点器v2(スキル本文を参照に追加、3回多数決)で再採点
python analyze.py                   # results/summary.json, results/runs.csv, comparison.png を出力
python ablation.py                  # (任意) T02 のヒント削除アブレーション
```

- エージェントモデル: `claude-sonnet-5-5`、採点モデル: `claude-haiku-5-5`(`bench.py` / `run.py` / `regrade.py` で変更可)
- 参考までに、筆者の環境では本実行(72 run + 採点)で約 $1.4 でした。`run.py` には累計コストが $3.5 を超えたら新規実行を止めるガードがあります。
- 再実行前に `results/runs.jsonl` を削除してください(追記方式のため)。

## ファイル

| ファイル | 内容 |
|---|---|
| `data.json` | モックデータ(顧客・注文・配送・返品ポリシー・在庫)。今日=2026-10-24 固定 |
| `skills/*.md` | スキル本文(= A のサブエージェントのプロンプト) |
| `tasks.json` | ゴールデンタスク12件、決定的チェック、ルーブリック |
| `bench.py` | ツール、ツールループ、アーキテクチャA/B、コスト計算 |
| `run.py` / `regrade.py` / `analyze.py` / `ablation.py` | 実行・採点・集計・アブレーション |
| `results/` | 記事に掲載した集計結果(summary.json, runs.csv, ablation_T02.json) |

生ログ(runs.jsonl)はサイズの都合で含めていません。
