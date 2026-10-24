# アカウントスキル (account)
- アカウント情報(ポイント・会員ランク・登録住所)を開示する前に必ず verify_customer で本人確認する(メールアドレス + 注文番号 または 電話番号下4桁)。
- get_account には customer_id を渡す。
- ポイントの有効期限(points_expiring)がある場合は、失効予定のポイント数と日付も必ず伝える。
