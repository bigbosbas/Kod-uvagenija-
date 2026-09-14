const express = require("express");
const { getPool } = require("../lib/db");
const { PRICE_RUB, buildPaymentUrl, buildResultSignature, getPassword2 } = require("../lib/robokassa");
const { generateAccessToken } = require("../lib/accessToken");
const { getPdfDownloadUrl } = require("../lib/s3");

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
// Доступ к файлу выдаётся НЕ здесь — только по серверному Result URL.
router.post("/create-payment", rateLimit({ windowMs: 60_000, max: 10 }), async (req, res) => {
  const invId = Date.now();

  try {
    const pool = getPool();
    await pool.query(
      "insert into payments (order_id, amount, status, access_source) values ($1, $2, 'pending', 'auto')",
      [String(invId), PRICE_RUB]
    );

    const protocol = req.get("x-forwarded-proto") || req.protocol;
    const host = req.get("host");
    const siteOrigin = `${protocol}://${host}`;
    const paymentUrl = buildPaymentUrl(invId, siteOrigin);

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
// подделать это из браузера нельзя.
router.post("/robokassa-webhook", express.urlencoded({ extended: false }), async (req, res) => {
  const { OutSum: outSum, InvId: invId, SignatureValue: signature } = req.body;

  if (!outSum || !invId || !signature) {
    return res.status(400).send("Bad Request");
  }

  const password2 = getPassword2();
  if (!password2) {
    console.error("robokassa-webhook: пароль#2 не задан");
    return res.status(500).send("Server misconfigured");
  }

  const expected = buildResultSignature({ outSum, invId, password2 });
  if (expected.toLowerCase() !== String(signature).toLowerCase()) {
    console.error("robokassa-webhook: подпись не совпадает для InvId", invId);
    return res.status(403).send("Forbidden");
  }

  try {
    const pool = getPool();
    const { rows } = await pool.query(
      "select id, status, access_token from payments where order_id = $1",
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
      await pool.query(
        `update payments
         set status = 'paid', paid_at = now(), access_token = $1, robokassa_payload = $2
         where id = $3`,
        [token, JSON.stringify(req.body), existing.id]
      );
    }

    res.send(`OK${invId}`);
  } catch (err) {
    console.error("robokassa-webhook error:", err);
    res.status(500).send("Server error");
  }
});

// GET /api/verify-access?token=<token> — проверяет токен и, если оплата
// подтверждена, выдаёт временную подписанную ссылку на скачивание PDF.
router.get("/verify-access", rateLimit({ windowMs: 60_000, max: 30 }), async (req, res) => {
  const token = req.query.token;
  if (!token || typeof token !== "string" || token.length < 10) {
    return res.json({ valid: false });
  }

  try {
    const pool = getPool();
    const { rows } = await pool.query(
      "select id from payments where access_token = $1 and status = 'paid'",
      [token]
    );
    if (!rows.length) return res.json({ valid: false });

    const downloadUrl = await getPdfDownloadUrl();
    res.json({ valid: true, downloadUrl });
  } catch (err) {
    console.error("verify-access error:", err);
    res.json({ valid: false });
  }
});

module.exports = router;
