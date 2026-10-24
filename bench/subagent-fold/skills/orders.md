# 注文スキル (orders)
- 注文情報を開示する前に必ず verify_customer で本人確認を行う。確認できなければ注文内容・配送先・追跡番号などを一切開示せず、正しいメールアドレスと注文番号の再確認を依頼する。
- get_order には verify_customer で得た customer_id を渡す。
- 注文ステータスの意味: processing=発送準備中(まだ発送前), shipped=発送済み, delivered=配達完了。
- 注文レコードの estimated_delivery_at_order_time は「注文時点の見込み」であり最新ではない。お届け日を聞かれたら必ず配送情報(get_shipment)で最新の予定日を確認する。
- 注文レコードには配達完了日が含まれない。配達完了日は配送情報(get_shipment の delivered_at)にある。
