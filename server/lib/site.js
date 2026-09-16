// Единая точка определения "какой это сайт" по домену запроса — использует
// и статическая раздача в server.js, и лог визитов в routes/visits.js.
// Раньше эта строка была продублирована в двух местах — риск разъехаться.
const PERESBORKA_HOST = process.env.PERESBORKA_HOST || "peresborka.privatebotrus.ru";

function getSiteProduct(req) {
  return req.hostname === PERESBORKA_HOST ? "peresborka" : "kod";
}

module.exports = { PERESBORKA_HOST, getSiteProduct };
