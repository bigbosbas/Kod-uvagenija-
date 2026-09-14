const crypto = require("crypto");

// Непредсказуемый токен доступа — та же схема, что на вебинарном проекте
// (_lib/accessToken.js): 32 случайных байта, hex. Никаких email/паролей на входе,
// сам токен и есть секрет.
function generateAccessToken() {
  return crypto.randomBytes(32).toString("hex");
}

module.exports = { generateAccessToken };
