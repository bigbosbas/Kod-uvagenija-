const express = require("express");
const { getPool } = require("../lib/db");
const { generateAccessToken } = require("../lib/accessToken");
const { PRICE_RUB } = require("../lib/robokassa");
const {
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  isRateLimited,
  recordAttempt,
  verifyPassword,
  setPassword,
  issueSessionToken,
  requireAdmin,
} = require("../lib/adminAuth");

const router = express.Router();

// POST /api/admin/login
router.post("/login", async (req, res) => {
  const ip = req.ip;
  const { password } = req.body || {};

  try {
    if (await isRateLimited(ip)) {
      return res.status(429).json({ error: "Слишком много попыток, подождите 15 минут" });
    }

    const ok = password && (await verifyPassword(password));
    await recordAttempt(ip, Boolean(ok));

    if (!ok) return res.status(401).json({ error: "Неверный пароль" });

    const token = issueSessionToken();
    res.cookie(SESSION_COOKIE, token, {
      httpOnly: true,
      secure: true,
      sameSite: "strict",
      maxAge: SESSION_TTL_SECONDS * 1000,
    });
    res.json({ ok: true });
  } catch (err) {
    console.error("admin/login error:", err);
    res.status(500).json({ error: "Server error" });
  }
});

router.post("/logout", (req, res) => {
  res.clearCookie(SESSION_COOKIE);
  res.json({ ok: true });
});

// POST /api/admin/change-password — требует текущий пароль, не только сессию,
// чтобы угнанная cookie не позволяла выкинуть настоящего админа.
router.post("/change-password", requireAdmin, async (req, res) => {
  const { currentPassword, newPassword } = req.body || {};
  if (!currentPassword || !newPassword || newPassword.length < 8) {
    return res.status(400).json({ error: "Некорректные данные" });
  }

  try {
    const ok = await verifyPassword(currentPassword);
    if (!ok) return res.status(403).json({ error: "Текущий пароль неверен" });

    await setPassword(newPassword);
    res.json({ ok: true });
  } catch (err) {
    console.error("admin/change-password error:", err);
    res.status(500).json({ error: "Server error" });
  }
});

// GET /api/admin/stats — карточки статистики + источники по UTM за 30 дней
// (перенесено с вебинарного проекта, тот же расчёт, другая СУБД).
router.get("/stats", requireAdmin, async (req, res) => {
  try {
    const pool = getPool();
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

    const [paymentsResult, visitsResult] = await Promise.all([
      pool.query("select status, amount, access_source, created_at from payments"),
      pool.query("select utm_source, created_at from visits"),
    ]);

    const payments = paymentsResult.rows;
    const visits = visitsResult.rows;

    const paid = payments.filter((p) => p.status === "paid");
    const paidLast30 = paid.filter((p) => p.created_at.toISOString() >= thirtyDaysAgo);
    const visitsLast30 = visits.filter((v) => v.created_at.toISOString() >= thirtyDaysAgo);

    const totalRevenue = paid.reduce((sum, p) => sum + Number(p.amount || 0), 0);
    const manualCount = paid.filter((p) => p.access_source === "manual").length;

    const sourceCounts = {};
    for (const v of visitsLast30) {
      const key = v.utm_source && v.utm_source.trim() ? v.utm_source.trim() : "(без метки)";
      sourceCounts[key] = (sourceCounts[key] || 0) + 1;
    }
    const topSources = Object.entries(sourceCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([source, count]) => ({ source, count }));

    const conversionRate =
      visitsLast30.length > 0 ? (paidLast30.length / visitsLast30.length) * 100 : 0;

    res.json({
      totalPaidCount: paid.length,
      totalRevenue,
      manualCount,
      autoCount: paid.length - manualCount,
      visitsLast30Count: visitsLast30.length,
      paidLast30Count: paidLast30.length,
      conversionRate: Math.round(conversionRate * 10) / 10,
      topSources,
    });
  } catch (err) {
    console.error("admin/stats error:", err);
    res.status(500).json({ error: "Server error" });
  }
});

// GET /api/admin/orders — список заказов для таблицы в админке.
router.get("/orders", requireAdmin, async (req, res) => {
  try {
    const pool = getPool();
    const { rows } = await pool.query(
      `select id, order_id, email, amount, status, access_source, access_token,
              created_at, paid_at, notes
       from payments
       order by created_at desc
       limit 200`
    );
    res.json({ orders: rows });
  } catch (err) {
    console.error("admin/orders error:", err);
    res.status(500).json({ error: "Server error" });
  }
});

// POST /api/admin/grant-access — ручная выдача доступа.
// Не отправляет ссылку клиенту автоматически — это отдельный шаг для админа
// (см. ТЗ, раздел 5: сама запись в базе доступ не открывает, пока ссылку не передали).
router.post("/grant-access", requireAdmin, async (req, res) => {
  const { email, notes } = req.body || {};
  const orderId = `manual-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  const token = generateAccessToken();

  try {
    const pool = getPool();
    const { rows } = await pool.query(
      `insert into payments (order_id, email, amount, status, paid_at, access_token, access_source, granted_by, notes)
       values ($1, $2, $3, 'paid', now(), $4, 'manual', 'admin', $5)
       returning id, order_id, access_token`,
      [orderId, email || null, PRICE_RUB, token, notes || null]
    );
    res.json({ ok: true, order: rows[0] });
  } catch (err) {
    console.error("admin/grant-access error:", err);
    res.status(500).json({ error: "Server error" });
  }
});

module.exports = router;
