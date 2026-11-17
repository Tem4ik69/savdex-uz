-- Н38: Telegram-бот больше не спрашивает ИНН, почту и код — привязка
-- только одноразовой ссылкой из кабинета. Что прежняя привязка успела
-- записать в разговоры, больше не нужно и стирается: ИНН (у ИП это ПИНФЛ —
-- личные данные), с какой учётной записью сверяли, хеш кода из письма,
-- счётчики ошибок и пауза. Сами разговоры (шаг и язык) остаются.
-- Код бота стирает эти поля и сам, но только у чатов, которые снова
-- напишут боту, — здесь разом у всех.

update telegram_bot_chats
set tin = null,
    user_id = null,
    code_hash = null,
    code_expires_at = null,
    mistakes = 0,
    locked_until = null,
    codes_sent = 0,
    codes_window_at = null,
    -- Ждали почту или код — теперь ждут ссылку из кабинета (шаг «inn»)
    state = case when state in ('email', 'code') then 'inn' else state end
where tin is not null
   or user_id is not null
   or code_hash is not null
   or state in ('email', 'code');
