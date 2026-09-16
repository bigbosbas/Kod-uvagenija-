const express = require("express");
const crypto = require("crypto");
const { getPool } = require("../lib/db");
const { getSiteProduct } = require("../lib/site");

const router = express.Router();
const MAX_LEN = 300;

function clean(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.slice(0, MAX_LEN);
}

// Хеш IP для статистики — не сам IP, минимизация ПДн.
function hashIp(req) {
  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0].trim() || req.ip || "unknown";
  const salt = process.env.ADMIN_JWT_SECRET || "";
  return crypto.createHash("sha256").update(ip + salt).digest("hex");
}

// POST /api/log-visit — лёгкий лог визита с UTM-метками для статистики
// в админке. Не должен ломать страницу посетителю при сбое.
router.post("/log-visit", async (req, res) => {
  const body = req.body || {};
  try {
    const pool = getPool();
    // product определяется по домену запроса на сервере, а не по тому, что
    // прислал клиент — иначе можно было бы подделать статистику чужого сайта.
    await pool.query(
      `insert into visits (utm_source, utm_medium, utm_campaign, utm_content, utm_term, referrer, landing_path, user_agent, ip_hash, product)
       values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [
        clean(body.utmSource),
        clean(body.utmMedium),
        clean(body.utmCampaign),
        clean(body.utmContent),
        clean(body.utmTerm),
        clean(body.referrer),
        clean(body.landingPath),
        clean(body.userAgent),
        hashIp(req),
        getSiteProduct(req),
      ]
    );
  } catch (err) {
    console.error("log-visit error:", err);
  }
  res.status(204).end();
});

module.exports = router;
