const { Pool } = require("pg");

// Единый пул соединений на весь процесс — переиспользуется всеми роутами.
// DATABASE_URL берётся из переменных окружения Timeweb App Platform, никогда не хардкодить.
let pool;

function getPool() {
  if (!pool) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error("DATABASE_URL не задан");
    }
    pool = new Pool({
      connectionString,
      ssl: process.env.DATABASE_SSL === "false" ? false : { rejectUnauthorized: false },
    });
    // pg эмитит 'error' на простаивающем соединении при любом сбое сети/БД;
    // без слушателя это необработанное исключение — валит весь процесс.
    pool.on("error", (err) => {
      console.error("Postgres pool error:", err);
    });
  }
  return pool;
}

module.exports = { getPool };
