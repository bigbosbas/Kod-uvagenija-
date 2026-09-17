const express = require("express");
const { getPool } = require("../lib/db");
const { PRODUCTS, getProductConfig, buildPaymentUrl, buildResultSignature, getPassword2 } = require("../lib/robokassa");
const { generateAccessToken } = require("../lib/accessToken");
const { getPdfDownloadUrl } = require("../lib/s3");
const { createOneTimeInviteLink } = require("../lib/telegram");

const router = express.Router();

// Простой rate limit в памяти процесса — на один инстанс App Platform этого
// достаточно, отдельный Redis для такого объёма избыточен.
const rateLimitBuckets = new Map();
function rateLimit({ windowMs, max }) {
  return (req, res, next) => {
    const key = req.ip;
    const now = Date.now();
    const bucket = rateLimitBuckets.get(key) || [];
    const recent = bucket.filter((ts) => now - ts < windowMs);
    if (recent.length >= max) {
      return res.status(429).json({ error: "Слишком много запросов, попробуйте позже" });
    }
    recent.push(now);
    rateLimitBuckets.set(key, recent);
    next();
  };
}

// POST /api/create-payment — создаёт заказ и возвращает ссылку на оплату.
// Доступ к материалам выдаётся НЕ здесь — только по серверному Result URL.
// { product } в теле запроса — 'kod' (по умолчанию) или 'peresborka'; оба
// лендинга делят один и тот же магазин Robokassa (см. ТЗ «Пересборки», раздел 5).
router.post("/create-payment", rateLimit({ windowMs: 60_000, max: 10 }), async (req, res) => {
  const invId = Date.now();
  const product = req.body && PRODUCTS[req.body.product] ? req.body.product : "kod";

  try {
    const { priceRub } = getProductConfig(product);
    const pool = getPool();
    await pool.query(
      "insert into payments (order_id, amount, status, access_source, product) values ($1, $2, 'pending', 'auto', $3)",
      [String(invId), priceRub, product]
    );

    const protocol = req.get("x-forwarded-proto") || req.protocol;
    const host = req.get("host");
    const siteOrigin = `${protocol}://${host}`;
    const paymentUrl = buildPaymentUrl(invId, siteOrigin, product);

    res.json({ paymentUrl, invId: String(invId) });
  } catch (err) {
    console.error("create-payment error:", err);
    res.status(500).json({ error: "Не удалось создать платёж" });
  }
});

// GET /api/check-payment?order=<invId> — опрашивается со страницы ожидания.
router.get("/check-payment", async (req, res) => {
  const order = req.query.order;
  if (!order) return res.json({ paid: false });

  try {
    const pool = getPool();
    const { rows } = await pool.query(
      "select status, access_token from payments where order_id = $1",
      [String(order)]
    );
    const row = rows[0];
    const paid = Boolean(row && row.status === "paid" && row.access_token);
    res.json({ paid, accessToken: paid ? row.access_token : null });
  } catch (err) {
    console.error("check-payment error:", err);
    res.json({ paid: false });
  }
});

// POST /api/robokassa-webhook — Result URL. Единственное место, откуда
// реально выдаётся доступ. Робокасса стучится сюда сервер-сервер,
// подделать это из браузера нельзя. Один Result URL на оба продукта —
// Shp_product (если передан при создании платежа) приходит обратно без
// изменений и участвует в подписи (см. lib/robokassa.js buildResultSignature).
router.post("/robokassa-webhook", express.urlencoded({ extended: false }), async (req, res) => {
  const { OutSum: outSum, InvId: invId, SignatureValue: signature, Shp_product: shpProduct } = req.body;

  if (!outSum || !invId || !signature) {
    return res.status(400).send("Bad Request");
  }

  const password2 = getPassword2();
  if (!password2) {
    console.error("robokassa-webhook: пароль#2 не задан");
    return res.status(500).send("Server misconfigured");
  }

  const expected = buildResultSignature({ outSum, invId, password2, shpProduct });
  if (expected.toLowerCase() !== String(signature).toLowerCase()) {
    console.error("robokassa-webhook: подпись не совпадает для InvId", invId);
    return res.status(403).send("Forbidden");
  }

  const product = shpProduct === "peresborka" ? "peresborka" : "kod";

  try {
    const pool = getPool();
    const { rows } = await pool.query(
      "select id, status, access_token, telegram_invite_link from payments where order_id = $1",
      [String(invId)]
    );
    const existing = rows[0];
    if (!existing) {
      console.error("robokassa-webhook: платёж не найден для InvId", invId);
      return res.status(400).send("Unknown order");
    }

    // Идемпотентность: Робокасса может продублировать уведомление.
    if (existing.status !== "paid") {
      const token = existing.access_token || generateAccessToken();
      let inviteLink = existing.telegram_invite_link || null;

      if (product === "peresborka" && !inviteLink) {
        // Сбой Telegram (сеть/API) не должен блокировать фиксацию оплаты —
        // иначе Robokassa получает 500 и клиент остаётся без статуса 'paid'
        // вообще. Ссылку в этом случае лениво досоздаст /api/verify-access.
        try {
          inviteLink = await createOneTimeInviteLink();
        } catch (telegramErr) {
          console.error("robokassa-webhook: не удалось создать telegram-инвайт, платёж всё равно фиксируем", telegramErr);
        }
      }

      await pool.query(
        `update payments
         set status = 'paid', paid_at = now(), access_token = $1, robokassa_payload = $2, telegram_invite_link = $3
         where id = $4`,
        [token, JSON.stringify(req.body), inviteLink, existing.id]
      );
    }

    res.send(`OK${invId}`);
  } catch (err) {
    console.error("robokassa-webhook error:", err);
    res.status(500).send("Server error");
  }
});

// GET /api/verify-access?token=<token> — проверяет токен и, если оплата
// подтверждена, выдаёт ссылку на материалы: presigned S3-URL для PDF
// («Код уважения») или одноразовую Telegram-инвайт-ссылку («Пересборка»).
router.get("/verify-access", rateLimit({ windowMs: 60_000, max: 30 }), async (req, res) => {
  const token = req.query.token;
  if (!token || typeof token !== "string" || token.length < 10) {
    return res.json({ valid: false });
  }

  try {
    const pool = getPool();
    const { rows } = await pool.query(
      "select id, product, telegram_invite_link from payments where access_token = $1 and status = 'paid'",
      [token]
    );
    const row = rows[0];
    if (!row) return res.json({ valid: false });

    if (row.product === "peresborka") {
      let inviteLink = row.telegram_invite_link;
      if (!inviteLink) {
        // Вебхук мог не успеть создать ссылку (сбой Telegram API) — раз
        // оплата уже подтверждена, досоздаём её здесь, чтобы покупатель не
        // застревал без доступа до ручного вмешательства админа.
        try {
          inviteLink = await createOneTimeInviteLink();
          await pool.query("update payments set telegram_invite_link = $1 where id = $2", [inviteLink, row.id]);
        } catch (err) {
          console.error("verify-access: не удалось создать telegram-инвайт", err);
          return res.json({ valid: false });
        }
      }
      return res.json({ valid: true, product: "peresborka", downloadUrl: inviteLink });
    }

    const downloadUrl = await getPdfDownloadUrl();
    res.json({ valid: true, product: "kod", downloadUrl });
  } catch (err) {
    console.error("verify-access error:", err);
    res.json({ valid: false });
  }
});

module.exports = router;
