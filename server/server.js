require("dotenv").config();
const path = require("path");
const express = require("express");
const cookieParser = require("cookie-parser");

const paymentsRouter = require("./routes/payments");
const adminRouter = require("./routes/admin");
const visitsRouter = require("./routes/visits");

const app = express();
const PORT = process.env.PORT || 3000;

app.disable("x-powered-by");
app.use(express.json());
app.use(cookieParser());

app.use("/api", paymentsRouter);
app.use("/api", visitsRouter);
app.use("/api/admin", adminRouter);

// Статика: сама страница, ассеты, admin-панель (SPA-страница отдаётся отдельно).
app.use(express.static(path.join(__dirname, "..", "public")));

app.get("/admin", (req, res) => {
  res.sendFile(path.join(__dirname, "..", "public", "admin", "index.html"));
});

app.listen(PORT, () => {
  console.log(`Сервер запущен на порту ${PORT}`);
});
