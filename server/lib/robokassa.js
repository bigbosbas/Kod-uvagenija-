const crypto = require("crypto");

// Цена зафиксирована в ТЗ и на самом лендинге — одна цифра на весь проект,
// менять сразу в обоих местах.
const PRICE_RUB = 1990;
const PAYMENT_BASE_URL = "https://auth.robokassa.ru/Merchant/Index.aspx";
const PRODUCT_NAME = "Курс «Код уважения» (PDF)";

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
function buildReceipt(outSum) {
  return JSON.stringify({
    items: [
      {
        name: PRODUCT_NAME,
        quantity: 1,
        sum: Number(outSum),
        tax: "none",
      },
    ],
  });
}

// Подпись для создания платежа: MerchantLogin:OutSum:InvId:Receipt:Пароль#1
// ВАЖНО (проверено на живом эндпоинте, не по документации Робокассы):
// Receipt участвует в подписи как СЫРАЯ JSON-строка, БЕЗ url-кодирования —
// encodeURIComponent()/urlencode()-стиль ломает подпись (ошибка 29).
function buildPaymentSignature({ merchantLogin, outSum, invId, receiptJson, password1 }) {
  return md5(`${merchantLogin}:${outSum}:${invId}:${receiptJson}:${password1}`);
}

// Подпись для проверки Result URL: OutSum:InvId:Пароль#2 — Receipt на неё не влияет.
function buildResultSignature({ outSum, invId, password2 }) {
  return md5(`${outSum}:${invId}:${password2}`);
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

function buildPaymentUrl(invId, siteOrigin) {
  const merchantLogin = process.env.ROBOKASSA_MERCHANT_LOGIN;
  const password1 = getPassword1();
  if (!merchantLogin || !password1) {
    throw new Error("ROBOKASSA_MERCHANT_LOGIN / пароль#1 не заданы");
  }

  const outSum = formatSum(PRICE_RUB);
  const receiptJson = buildReceipt(outSum);
  const signature = buildPaymentSignature({ merchantLogin, outSum, invId, receiptJson, password1 });

  const params = new URLSearchParams({
    MerchantLogin: merchantLogin,
    OutSum: outSum,
    InvId: String(invId),
    Description: PRODUCT_NAME,
    Receipt: receiptJson,
    SignatureValue: signature,
    Culture: "ru",
    SuccessURL: `${siteOrigin}/payment-success.html`,
    FailURL: `${siteOrigin}/payment-fail.html`,
  });
  if (isTestMode()) params.set("IsTest", "1");

  return `${PAYMENT_BASE_URL}?${params.toString()}`;
}

module.exports = {
  PRICE_RUB,
  PRODUCT_NAME,
  buildPaymentUrl,
  buildResultSignature,
  getPassword2,
};
