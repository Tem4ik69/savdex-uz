# Онлайн-оплата счетов сайта: Uzum, Payme, Click

Тарифы и пакеты кредитов в кабинете (`/cabinet/billing`) оплачиваются
картой через **Uzum**, **Payme** или **Click** — покупатель выбирает
способ над кнопками «Оплатить». Включено несколько — показывается выбор,
один — выбора нет, ни одного — кнопка «Выставить счёт» (оплата переводом
по реквизитам). Заказы маркетплейса платят отдельно, со своими ключами —
[marketplace.md](marketplace.md), «Оплата — этап 2».

Счёт выставляется сразу (`payments`, статус `pending`), доступ — только
после оплаты. Зачисление у всех трёх одно — `settlement.mark_paid`:
тариф или кредиты выдаются ровно один раз, сверки (`reconcile_billing`,
«Сверка со шлюзом» в админке) провайдера не различают. Транзакции
провайдеров — строки `payment_transactions` (`provider` = `uzum`,
`payme` или `click`); схема базы не менялась.

## Код

| Что | Где |
|---|---|
| Выбор провайдера, касса Uzum | `python/savdex/payments/checkout.py` (`available`, `choose`) |
| Payme: ключи, ссылка, чек | `python/savdex/payments/payme.py` |
| Click: ключи, ссылка, подпись | `python/savdex/payments/click.py` |
| Колбэки Uzum | `python/savdex/web/payment_callbacks.py` |
| Колбэки Payme (Merchant API) | `python/savdex/web/payme_callbacks.py` |
| Колбэки Click (SHOP API) | `python/savdex/web/click_callbacks.py` |
| Уход на оплату из кабинета | `python/savdex/web/billing_actions.py` (`_checkout`) |
| Выбор способа в кабинете | `resources/js/components/BillingStore.tsx` (`ProviderPicker`) |
| Проверки | `python/tests/test_web_payme_click.py`, `test_payme_click.py` |

## Адреса колбэков — завести в кабинетах провайдеров

| Провайдер | Адрес |
|---|---|
| Uzum (Merchant API) | `https://savdex.uz/payments/uzum/callback/{check,create,confirm,reverse,status}` |
| Uzum (вебхук кассы) | `https://savdex.uz/payments/uzum/callback` |
| Payme (Merchant API) | `https://savdex.uz/payments/payme/callback` |
| Click (SHOP API) | Prepare — `https://savdex.uz/payments/click/callback/prepare`, Complete — `https://savdex.uz/payments/click/callback/complete` |

Выключенный провайдер отвечает на свои адреса 404.

## Переменные окружения

Только на машинах (`/opt/savdex/env/app.env` у `savdex-web` и
`savdex-admin`) или в секретах GitHub — **не в коде и не в чате**.

**Payme**

| Переменная | Что |
|---|---|
| `PAYMENTS_PAYME_ENABLED` | `true` — включить (без ключей не включится) |
| `PAYMENTS_PAYME_MERCHANT_ID`, `PAYMENTS_PAYME_KEY` | касса и ключ из кабинета Payme Business |
| `PAYMENTS_PAYME_CHECKOUT_URL` | по умолчанию `https://checkout.paycom.uz`; песочница — `https://checkout.test.paycom.uz` |
| `PAYMENTS_PAYME_ACCOUNT_FIELD` | поле счёта в `account`, по умолчанию `invoice` — так же назвать поле в кабинете Payme |
| `PAYMENTS_PAYME_CALLBACK_IPS` | адреса Payme через запятую; **на боевом без них Payme выключен** |
| `PAYMENTS_PAYME_PENDING_MINUTES` | через сколько минут незавершённая попытка не мешает новой (по умолчанию 30, не больше 720) |
| `PAYMENTS_PAYME_IKPU`, `PAYMENTS_PAYME_PACKAGE_CODE`, `PAYMENTS_PAYME_VAT_PERCENT` | чек; не заданы — берутся у Uzum (`PAYMENTS_UZUM_SPIC`, `…_PACKAGE_CODE`, `…_VAT_PERCENT`), без ИКПУ чек не передаётся |

**Click**

| Переменная | Что |
|---|---|
| `PAYMENTS_CLICK_ENABLED` | `true` — включить (без ключей не включится) |
| `PAYMENTS_CLICK_SERVICE_ID`, `PAYMENTS_CLICK_MERCHANT_ID`, `PAYMENTS_CLICK_SECRET_KEY` | сервис, поставщик и ключ подписи из кабинета Click |
| `PAYMENTS_CLICK_PAY_URL` | по умолчанию `https://my.click.uz/services/pay` |
| `PAYMENTS_CLICK_CALLBACK_IPS` | адреса Click через запятую; **на боевом без них Click выключен** |

**Общее:** `PAYMENTS_DEFAULT` (`uzum`, `payme` или `click`) — какой способ
выбран сразу. Uzum — как раньше: `PAYMENTS_UZUM_ENABLED`,
`PAYMENTS_UZUM_CHECKOUT_ENABLED` и ключи `PAYMENTS_UZUM_*`.

## Как идёт оплата

**Payme.** «Оплатить» → `checkout.paycom.uz` со счётом и суммой в
тийинах. Payme зовёт `CheckPerformTransaction` (счёт ждёт оплаты, сумма
та), `CreateTransaction`, после списания — `PerformTransaction`: тариф
выдаётся. Транзакция живёт 12 часов. Пока по счёту идёт другая попытка
Payme моложе `PAYMENTS_PAYME_PENDING_MINUTES`, новая не заводится
(-31053); старше — гасится.

**Click.** «Оплатить» → `my.click.uz` с номером счёта. Click зовёт
Prepare (проверка подписи, счёта и суммы), после списания — Complete:
тариф выдаётся. Ошибка в ответ на Complete — Click сам возвращает деньги.

**Повторы** любого колбэка безопасны: второго зачисления нет.

## Возвраты

Как у Uzum — вручную, но с порядком шагов:

1. В админке оформить и провести возврат (счёт — «Возвращён»).
2. **Payme:** отменить транзакцию в кабинете Payme Business — Payme
   позовёт `CancelTransaction`. По не возвращённому в админке счёту
   отмену проведённой транзакции сайт не примет (-31007): иначе деньги
   ушли бы назад, а тариф остался.
3. **Click:** вернуть деньги в кабинете Click (колбэка о возврате у
   SHOP API нет).

## Перед боевым включением

- Договоры с Payme и Click, ключи — в `app.env` на обеих машинах.
- Сверить с документацией провайдеров: коды ошибок и тексты Payme,
  состав чека (`detail`), правила подписи Click и ответ на повторный
  Complete, параметры страниц оплаты.
- Пройти песочницу: у Payme — тестовый кабинет
  (`checkout.test.paycom.uz`) и его автопроверка Merchant API; у Click —
  тестовые запросы Prepare и Complete.
- Задать `PAYMENTS_PAYME_CALLBACK_IPS` и `PAYMENTS_CLICK_CALLBACK_IPS`
  (адреса — у провайдеров).
