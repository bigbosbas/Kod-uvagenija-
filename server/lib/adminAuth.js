const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const { getPool } = require("./db");

const SESSION_COOKIE = "admin_session";
const SESSION_TTL_SECONDS = 60 * 60 * 8; // 8 часов
const MAX_ATTEMPTS_PER_WINDOW = 5;
const WINDOW_MINUTES = 15;

function getJwtSecret() {
  const secret = process.env.ADMIN_JWT_SECRET;
  if (!secret) throw new Error("ADMIN_JWT_SECRET не задан");
  return secret;
}

// Rate limiting по IP — защита от подбора пароля админки, требование из
// AGENT_SECURITY_RULES.md ("Всегда реализовывать rate limiting для... форм авторизации").
async function isRateLimited(ip) {
  const pool = getPool();
  const { rows } = await pool.query(
    `select count(*)::int as attempts
     from admin_login_attempts
     where ip = $1 and created_at > now() - interval '${WINDOW_MINUTES} minutes' and success = false`,
    [ip]
  );
  return rows[0].attempts >= MAX_ATTEMPTS_PER_WINDOW;
}

async function recordAttempt(ip, success) {
  const pool = getPool();
  await pool.query("insert into admin_login_attempts (ip, success) values ($1, $2)", [ip, success]);
}

async function verifyPassword(password) {
  const pool = getPool();
  const { rows } = await pool.query("select password_hash from admin_credentials where id = 1");
  if (!rows.length) return false;
  return bcrypt.compare(password, rows[0].password_hash);
}

async function setPassword(newPassword) {
  const hash = await bcrypt.hash(newPassword, 12);
  const pool = getPool();
  await pool.query(
    `insert into admin_credentials (id, password_hash, updated_at) values (1, $1, now())
     on conflict (id) do update set password_hash = excluded.password_hash, updated_at = now()`,
    [hash]
  );
}

function issueSessionToken() {
  return jwt.sign({ role: "admin" }, getJwtSecret(), { expiresIn: SESSION_TTL_SECONDS });
}

function verifySessionToken(token) {
  try {
    const payload = jwt.verify(token, getJwtSecret());
    return payload.role === "admin";
  } catch {
    return false;
  }
}

// Middleware: без валидной сессии — 401. Проверка прав только на сервере,
// никогда не доверять фронтенду.
function requireAdmin(req, res, next) {
  const token = req.cookies ? req.cookies[SESSION_COOKIE] : null;
  if (!token || !verifySessionToken(token)) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  next();
}

module.exports = {
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  isRateLimited,
  recordAttempt,
  verifyPassword,
  setPassword,
  issueSessionToken,
  verifySessionToken,
  requireAdmin,
};
