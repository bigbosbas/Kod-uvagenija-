// Выдача доступа к приватному каналу «Пересборки» — одноразовая
// Telegram-инвайт-ссылка вместо presigned S3-URL (см. ТЗ, раздел 3).
// Бот должен быть администратором канала с правом «Приглашение
// пользователей по ссылке». Токен и ID канала — только через .env,
// никогда в коде/чате.
const INVITE_TTL_SECONDS = 48 * 60 * 60; // 48 часов на переход по ссылке

async function createOneTimeInviteLink() {
  const token = process.env.TELEGRAM_BOT_TOKEN_PERESBORKA;
  const chatId = process.env.TELEGRAM_CHANNEL_ID_PERESBORKA;
  if (!token || !chatId) {
    throw new Error("TELEGRAM_BOT_TOKEN_PERESBORKA / TELEGRAM_CHANNEL_ID_PERESBORKA не заданы");
  }

  const expireDate = Math.floor(Date.now() / 1000) + INVITE_TTL_SECONDS;
  const res = await fetch(`https://api.telegram.org/bot${token}/createChatInviteLink`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      member_limit: 1, // одноразовая — нельзя переслать и использовать повторно
      expire_date: expireDate,
      name: `peresborka-${Date.now()}`.slice(0, 32), // видно только админам канала
    }),
  });

  const data = await res.json();
  if (!data.ok) {
    throw new Error(`Telegram createChatInviteLink: ${data.description || "неизвестная ошибка"}`);
  }
  return data.result.invite_link;
}

module.exports = { createOneTimeInviteLink };
