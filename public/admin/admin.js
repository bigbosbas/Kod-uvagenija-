const loginScreen = document.getElementById("loginScreen");
const mainScreen = document.getElementById("mainScreen");
const loginPassword = document.getElementById("loginPassword");
const loginBtn = document.getElementById("loginBtn");
const loginError = document.getElementById("loginError");
const ordersBody = document.getElementById("ordersBody");

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function statusBadge(status) {
  const map = { paid: ["Оплачено", "badge--paid"], pending: ["Ожидание", "badge--pending"], failed: ["Отклонён", "badge--failed"] };
  const [label, cls] = map[status] || [status, ""];
  return `<span class="badge ${cls}">${label}</span>`;
}

function productLabel(product) {
  return product === "peresborka" ? "Пересборка" : "Код уважения";
}

// TODO: заполнить, когда определится домен «Пересборки» (см. ТЗ, раздел 4) —
// ссылка на этот домен нужна, т.к. админка живёт на домене «Кода уважения»,
// а /?access=token должен открываться на сайте того продукта, для которого выдан.
const PERESBORKA_ORIGIN = "";

async function loadOrders() {
  const res = await fetch("/api/admin/orders");
  if (res.status === 401) return showLogin();
  const { orders } = await res.json();
  ordersBody.innerHTML = orders
    .map((o) => {
      const origin = o.product === "peresborka" && PERESBORKA_ORIGIN ? PERESBORKA_ORIGIN : window.location.origin;
      const link = o.access_token ? `${origin}/?access=${o.access_token}` : null;
      return `<tr>
        <td>${fmtDate(o.created_at)}</td>
        <td>${productLabel(o.product)}</td>
        <td>${o.email ? escapeHtml(o.email) : "—"}</td>
        <td>${Number(o.amount).toFixed(0)} ₽</td>
        <td>${statusBadge(o.status)}</td>
        <td>${o.access_source === "manual" ? "Вручную" : "Робокасса"}</td>
        <td>${link ? `<button class="btn btn--secondary btn-small copy-link" data-link="${link}" style="color:var(--ink); border-color:var(--divider);">Скопировать</button>` : "—"}</td>
      </tr>`;
    })
    .join("");

  document.querySelectorAll(".copy-link").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await navigator.clipboard.writeText(btn.dataset.link);
      const original = btn.textContent;
      btn.textContent = "Скопировано";
      setTimeout(() => (btn.textContent = original), 1500);
    });
  });
}

async function loadStats() {
  const res = await fetch("/api/admin/stats");
  if (res.status === 401) return showLogin();
  const stats = await res.json();

  document.getElementById("statPaidCount").textContent = stats.totalPaidCount;
  document.getElementById("statRevenue").textContent = `${stats.totalRevenue.toLocaleString("ru-RU")} ₽`;
  document.getElementById("statVisits").textContent = stats.visitsLast30Count;
  document.getElementById("statConversion").textContent = `${stats.conversionRate}%`;

  const sourcesBody = document.getElementById("sourcesBody");
  if (!stats.topSources.length) {
    sourcesBody.innerHTML = `<tr><td colspan="2" class="hint">Пока нет данных</td></tr>`;
  } else {
    sourcesBody.innerHTML = stats.topSources
      .map((s) => `<tr><td>${escapeHtml(s.source)}</td><td>${Number(s.count)}</td></tr>`)
      .join("");
  }
}

function showLogin() {
  loginScreen.hidden = false;
  mainScreen.hidden = true;
}
function showMain() {
  loginScreen.hidden = true;
  mainScreen.hidden = false;
  loadOrders();
  loadStats();
}

loginBtn.addEventListener("click", async () => {
  loginError.hidden = true;
  const res = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: loginPassword.value }),
  });
  if (res.ok) {
    loginPassword.value = "";
    showMain();
  } else {
    const data = await res.json().catch(() => ({}));
    loginError.textContent = data.error || "Не удалось войти";
    loginError.hidden = false;
  }
});
loginPassword.addEventListener("keydown", (e) => { if (e.key === "Enter") loginBtn.click(); });

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/admin/logout", { method: "POST" });
  showLogin();
});

const changePasswordToggle = document.getElementById("changePasswordToggle");
const changePasswordPanel = document.getElementById("changePasswordPanel");
changePasswordToggle.addEventListener("click", () => {
  changePasswordPanel.hidden = !changePasswordPanel.hidden;
});

document.getElementById("submitChangePassword").addEventListener("click", async () => {
  const currentPassword = document.getElementById("currentPassword").value;
  const newPassword = document.getElementById("newPassword").value;
  const errorEl = document.getElementById("changePasswordError");
  errorEl.hidden = true;

  const res = await fetch("/api/admin/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ currentPassword, newPassword }),
  });
  if (res.ok) {
    document.getElementById("currentPassword").value = "";
    document.getElementById("newPassword").value = "";
    changePasswordPanel.hidden = true;
    alert("Пароль изменён");
  } else {
    const data = await res.json().catch(() => ({}));
    errorEl.textContent = data.error || "Не удалось сменить пароль";
    errorEl.hidden = false;
  }
});

document.getElementById("grantBtn").addEventListener("click", async () => {
  const product = document.getElementById("grantProduct").value;
  const email = document.getElementById("grantEmail").value.trim();
  const notes = document.getElementById("grantNotes").value.trim();
  const errorEl = document.getElementById("grantError");
  errorEl.hidden = true;

  const res = await fetch("/api/admin/grant-access", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product, email, notes }),
  });
  if (res.ok) {
    document.getElementById("grantEmail").value = "";
    document.getElementById("grantNotes").value = "";
    loadOrders();
    loadStats();
  } else {
    const data = await res.json().catch(() => ({}));
    errorEl.textContent = data.error || "Не удалось выдать доступ";
    errorEl.hidden = false;
  }
});

// Проверяем сессию сразу при загрузке.
fetch("/api/admin/orders").then((res) => (res.status === 401 ? showLogin() : showMain()));
