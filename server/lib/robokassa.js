const crypto = require("crypto");

const PAYMENT_BASE_URL = "https://auth.robokassa.ru/Merchant/Index.aspx";

// Оба лендинга («Код уважения» и «Пересборка») используют один и тот же
// магазин Robokassa — клиент отказался заводить второй магазин (налоговые
// сложности). У магазина один статический Result URL, поэтому платежи
// различаются пользовательским параметром Shp_product (см. документацию
// Robokassa, раздел "Дополнительные пользовательские параметры" —
// docs.robokassa.ru/ru/notifications-and-redirects). Для 'kod' Shp_product
// намеренно не передаётся вовсе — это исходный продукт, его поведение
// (ни URL, ни подпись) не должно измениться.
const PRODUCTS = {
  kod: {
    priceRub: 1990,
    name: "Курс «Код уважения» (PDF)",
    shpProduct: null,
  },
  peresborka: {
    priceRub: 2990,
    name: "Курс «Пересборка»",
    shpProduct: "peresborka",
  },
};

function getProductConfig(product) {
  const config = PRODUCTS[product];
  if (!config) throw new Error(`Неизвестный продукт: ${product}`);
  return config;
}

function md5(input) {
  return crypto.createHash("md5").update(input, "utf8").digest("hex");
}

function formatSum(amount) {
  return amount.toFixed(2);
}

// Магазин «Privatebot» — ИП на НПД, чек через «Робочеки СМЗ». С апреля 2026
// Робокасса требует номенклатуру (Receipt) в каждом запросе на оплату даже для
// самозанятых — без него чек не формируется. Подтверждено на вебинарном проекте,
// см. netlify/functions/_lib/robokassa.js в том репозитории и его память проекта.
// Для СМЗ достаточно tax: "none" — sno/payment_method/payment_object не нужны.
function buildReceipt(outSum, productName) {
  return JSON.stringify({
    items: [
      {
        name: productName,
        quantity: 1,
        sum: Number(outSum),
        tax: "none",
      },
    ],
  });
}

// Подпись для создания платежа: MerchantLogin:OutSum:InvId:Receipt:Пароль#1[:Shp_product=...]
// ВАЖНО (проверено на живом эндпоинте, не по документации Робокассы):
// Receipt участвует в подписи как СЫРАЯ JSON-строка, БЕЗ url-кодирования —
// encodeURIComponent()/urlencode()-стиль ломает подпись (ошибка 29).
// Shp_* добавляются В КОНЕЦ строки, после пароля — таков порядок по докам
// Robokassa (раздел "Сборка подписи"), и только когда параметр реально передан.
function buildPaymentSignature({ merchantLogin, outSum, invId, receiptJson, password1, shpProduct }) {
  let base = `${merchantLogin}:${outSum}:${invId}:${receiptJson}:${password1}`;
  if (shpProduct) base += `:Shp_product=${shpProduct}`;
  return md5(base);
}

// Подпись для проверки Result URL: OutSum:InvId:Пароль#2[:Shp_product=...].
// Receipt на неё не влияет. Shp_product возвращается Robokassa в вебхуке
// БЕЗ изменений и участвует в подписи ровно в том виде, в каком пришёл —
// проверено по docs.robokassa.ru/ru/notifications-and-redirects (пример:
// "100.000000:450009:Пароль#2:Shp_login=Vasya:Shp_oplata=1").
function buildResultSignature({ outSum, invId, password2, shpProduct }) {
  let base = `${outSum}:${invId}:${password2}`;
  if (shpProduct) base += `:Shp_product=${shpProduct}`;
  return md5(base);
}

function isTestMode() {
  return process.env.ROBOKASSA_TEST_MODE === "true";
}

function getPassword1() {
  return isTestMode() ? process.env.ROBOKASSA_TEST_PASSWORD_1 : process.env.ROBOKASSA_PASSWORD_1;
}

function getPassword2() {
  return isTestMode() ? process.env.ROBOKASSA_TEST_PASSWORD_2 : process.env.ROBOKASSA_PASSWORD_2;
}

function buildPaymentUrl(invId, siteOrigin, product = "kod") {
  const { priceRub, name, shpProduct } = getProductConfig(product);

  const merchantLogin = process.env.ROBOKASSA_MERCHANT_LOGIN;
  const password1 = getPassword1();
  if (!merchantLogin || !password1) {
    throw new Error("ROBOKASSA_MERCHANT_LOGIN / пароль#1 не заданы");
  }

  const outSum = formatSum(priceRub);
  const receiptJson = buildReceipt(outSum, name);
  const signature = buildPaymentSignature({ merchantLogin, outSum, invId, receiptJson, password1, shpProduct });

  const params = new URLSearchParams({
    MerchantLogin: merchantLogin,
    OutSum: outSum,
    InvId: String(invId),
    Description: name,
    Receipt: receiptJson,
    SignatureValue: signature,
    Culture: "ru",
    SuccessURL: `${siteOrigin}/payment-success.html`,
    FailURL: `${siteOrigin}/payment-fail.html`,
  });
  if (shpProduct) params.set("Shp_product", shpProduct);
  if (isTestMode()) params.set("IsTest", "1");

  return `${PAYMENT_BASE_URL}?${params.toString()}`;
}

module.exports = {
  PRODUCTS,
  getProductConfig,
  buildPaymentUrl,
  buildResultSignature,
  getPassword2,
};
