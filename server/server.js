require("dotenv").config();
const path = require("path");
const express = require("express");
const helmet = require("helmet");
const compression = require("compression");
const cookieParser = require("cookie-parser");

const paymentsRouter = require("./routes/payments");
const adminRouter = require("./routes/admin");
const visitsRouter = require("./routes/visits");

const app = express();
const PORT = process.env.PORT || 3000;

app.disable("x-powered-by");
// CSP выключен явно: инлайновые <script>/<style> и сторонние Google Fonts
// на этой странице не подходят под безопасный дефолтный CSP без отдельной
// настройки nonce/hash — остальные заголовки Helmet (X-Frame-Options,
// X-Content-Type-Options, Referrer-Policy и т.д.) применяются как обычно.
app.use(helmet({ contentSecurityPolicy: false }));
app.use(compression());
app.use(express.json());
app.use(cookieParser());

app.use("/api", paymentsRouter);
app.use("/api", visitsRouter);
app.use("/api/admin", adminRouter);

// Один процесс/деплой обслуживает оба лендинга клиента («Код уважения» и
// «Пересборка») — они делят один магазин Robokassa и одну базу (см. ТЗ
// «Пересборки», раздел 2). Какой статический сайт отдавать, решаем по
// заголовку Host. PERESBORKA_HOST — плейсхолдер до подтверждения домена
// клиентом (ТЗ, раздел 4); переопределяется переменной окружения.
const PUBLIC_DIR = path.join(__dirname, "..", "public");
const PERESBORKA_DIR = path.join(__dirname, "..", "public-peresborka");
const PERESBORKA_HOST = process.env.PERESBORKA_HOST || "peresborka.privatebotrus.ru";

// maxAge — только для повторных визитов; index.html через no-cache, чтобы
// правки разметки/скриптов не залипали в браузере после деплоя.
const staticOptions = {
  maxAge: "7d",
  setHeaders: (res, filePath) => {
    if (filePath.endsWith(".html")) {
      res.setHeader("Cache-Control", "no-cache");
    }
  },
};
const serveKod = express.static(PUBLIC_DIR, staticOptions);
const servePeresborka = express.static(PERESBORKA_DIR, staticOptions);

// Админка общая на оба продукта (различие — колонка/фильтр product в самих
// данных) — маунтится ДО хост-диспетчера ниже, иначе с домена «Пересборки»
// запросы вида /admin/admin.js ушли бы в чужую статическую папку и отдавали 404.
app.use("/admin", express.static(path.join(PUBLIC_DIR, "admin"), staticOptions));
app.get("/admin", (req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, "admin", "index.html"));
});

app.use((req, res, next) => {
  if (req.hostname === PERESBORKA_HOST) return servePeresborka(req, res, next);
  return serveKod(req, res, next);
});

app.listen(PORT, () => {
  console.log(`Сервер запущен на порту ${PORT}`);
});
