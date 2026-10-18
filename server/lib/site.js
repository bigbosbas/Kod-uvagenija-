// Единая точка определения "какой это сайт" по домену запроса — использует
// и статическая раздача в server.js, и лог визитов в routes/visits.js.
// Раньше эта строка была продублирована в двух местах — риск разъехаться.
const PERESBORKA_HOST = process.env.PERESBORKA_HOST || "peresborka.privatebotrus.ru";
const KNIGI_HOST = process.env.KNIGI_HOST || "knigi.privatebotrus.ru";

// Возвращает сайт, а не конкретный товар: на knigi. продаются две книги,
// для визитов/UTM это один сайт 'knigi'.
function getSiteProduct(req) {
  if (req.hostname === PERESBORKA_HOST) return "peresborka";
  if (req.hostname === KNIGI_HOST) return "knigi";
  return "kod";
}

module.exports = { PERESBORKA_HOST, KNIGI_HOST, getSiteProduct };
