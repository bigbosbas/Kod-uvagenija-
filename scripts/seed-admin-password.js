require("dotenv").config();
const { setPassword } = require("../server/lib/adminAuth");

// Одноразовая настройка пароля админки: node scripts/seed-admin-password.js "новыйПароль"
const password = process.argv[2];
if (!password || password.length < 8) {
  console.error("Использование: node scripts/seed-admin-password.js \"пароль от 8 символов\"");
  process.exit(1);
}

setPassword(password)
  .then(() => {
    console.log("Пароль админки установлен.");
    process.exit(0);
  })
  .catch((err) => {
    console.error("Ошибка:", err.message);
    process.exit(1);
  });
