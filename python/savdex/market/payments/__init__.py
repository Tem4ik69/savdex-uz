"""
Оплата заказов маркетплейса картой — этап 2 (docs/marketplace.md, «Оплата —
этап 2»; docs/marketplace-security.md, раздел 3).

Один слой на трёх провайдеров:

- ``base.py`` — настройки из окружения, протокол провайдера, строки
  ``market_payments`` (один живой счёт на заказ), проведение оплаты
  (``orders.mark_paid``) и возврат (``refund_order`` → ``orders.mark_refunded``)
  — ровно один раз;
- ``uzum.py`` — Merchant API Uzum: check, create, confirm, reverse, status
  (свой serviceId, не тот, что у тарифов сайта);
- ``payme.py`` — Payme Merchant API (JSON-RPC);
- ``click.py`` — Click SHOP API: Prepare и Complete;
- ``reconcile.py`` — ночная сверка оплат с журналом денег.

Сумма — только из заказа; колбэк сверяет присланную сумму с базой.
Ключи — только из окружения: провайдер без ключей выключен (его колбэки —
404, оплатить им нельзя).
"""
