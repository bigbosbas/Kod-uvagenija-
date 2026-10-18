// Локальный просмотр заглушки старого сайта (lib/oldSite.js) без базы и API:
// на любой путь отдаёт ту же страницу, что увидят на nagaichenkopsy.com.
const express = require("express");
const { oldSiteGone } = require("../server/lib/oldSite");
const app = express();
app.use((req, res, next) => { Object.defineProperty(req, "hostname", { value: "nagaichenkopsy.com" }); next(); });
app.use(oldSiteGone);
const port = Number(process.env.PORT || 4510);
app.listen(port, () => console.log(`old-site stub preview on http://localhost:${port}`));
