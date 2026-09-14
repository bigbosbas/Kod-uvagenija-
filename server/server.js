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

// Статика: сама страница, ассеты, admin-панель (SPA-страница отдаётся отдельно).
// maxAge — только для повторных визитов; index.html через no-cache, чтобы
// правки разметки/скриптов не залипали в браузере после деплоя.
app.use(express.static(path.join(__dirname, "..", "public"), {
  maxAge: "7d",
  setHeaders: (res, filePath) => {
    if (filePath.endsWith(".html")) {
      res.setHeader("Cache-Control", "no-cache");
    }
  },
}));

app.get("/admin", (req, res) => {
  res.sendFile(path.join(__dirname, "..", "public", "admin", "index.html"));
});

app.listen(PORT, () => {
  console.log(`Сервер запущен на порту ${PORT}`);
});
