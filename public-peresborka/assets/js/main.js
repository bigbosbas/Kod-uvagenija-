// Доступ к материалам по приватному токену (?access=токен из админки либо из
// возврата после оплаты Робокассы). Токен один раз сохраняется в этом
// браузере (localStorage), чтобы при повторных визитах не нужна была ссылка.
// Тот же паттерн, что на «Коде уважения» — отличие только в том, что тут
// ссылка ведёт в приватный Telegram-канал, а не на скачивание PDF.
const ACCESS_TOKEN_STORAGE_KEY = "peresborkaAccessToken";
const PENDING_ORDER_STORAGE_KEY = "peresborkaPendingOrder";
const PENDING_ORDER_MAX_AGE_MS = 2 * 60 * 60 * 1000;

function storeAccessToken(token) {
  try { localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token); } catch {}
}
function readStoredAccessToken() {
  try { return localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY); } catch { return null; }
}
function clearStoredAccessToken() {
  try { localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY); } catch {}
}

function storePendingOrder(invId) {
  try { localStorage.setItem(PENDING_ORDER_STORAGE_KEY, JSON.stringify({ invId, ts: Date.now() })); } catch {}
}
function readPendingOrder() {
  try {
    const raw = localStorage.getItem(PENDING_ORDER_STORAGE_KEY);
    if (!raw) return null;
    const { invId, ts } = JSON.parse(raw);
    if (!invId || Date.now() - ts > PENDING_ORDER_MAX_AGE_MS) return null;
    return invId;
  } catch { return null; }
}
function clearPendingOrder() {
  try { localStorage.removeItem(PENDING_ORDER_STORAGE_KEY); } catch {}
}

const overlay = document.getElementById("downloadOverlay");
const overlayText = document.getElementById("downloadStatusText");
const overlayLink = document.getElementById("downloadLink");
const overlayClose = document.getElementById("downloadOverlayClose");

if (overlayClose) {
  overlayClose.addEventListener("click", () => {
    overlay.hidden = true;
  });
}

function showDownload(inviteUrl) {
  overlay.hidden = false;
  overlayText.textContent = "Ссылка на приватный канал готова.";
  overlayLink.href = inviteUrl;
  overlayLink.style.display = "inline-flex";
}

async function tryUnlockWithToken(token) {
  try {
    const res = await fetch("/api/verify-access?token=" + encodeURIComponent(token));
    const data = await res.json();
    if (data.valid && data.downloadUrl) {
      storeAccessToken(token);
      clearPendingOrder();
      showDownload(data.downloadUrl);
      return true;
    }
    clearStoredAccessToken();
    return false;
  } catch {
    return false;
  }
}

async function tryResolvePendingOrder() {
  const invId = readPendingOrder();
  if (!invId) return;
  try {
    const res = await fetch("/api/check-payment?order=" + encodeURIComponent(invId));
    const data = await res.json();
    if (data.paid && data.accessToken) {
      await tryUnlockWithToken(data.accessToken);
    }
  } catch {}
}

(async function initAccess() {
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get("access");

  if (urlToken) {
    params.delete("access");
    const cleanQuery = params.toString();
    const cleanUrl = window.location.pathname + (cleanQuery ? "?" + cleanQuery : "") + window.location.hash;
    window.history.replaceState({}, "", cleanUrl);
  }

  const token = urlToken || readStoredAccessToken();
  const unlocked = token ? await tryUnlockWithToken(token) : false;

  if (!unlocked) {
    await tryResolvePendingOrder();
  }
})();

// Покупка — тот же create-payment, что и «Код уважения», но с product:
// 'peresborka', чтобы сервер применил свою цену/Shp_product для Robokassa
// (см. server/lib/robokassa.js).
async function startPurchase(btn) {
  btn.disabled = true;
  const originalHtml = btn.innerHTML;
  try {
    const response = await fetch("/api/create-payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: "peresborka" }),
    });
    if (!response.ok) throw new Error("payment init failed");
    const { paymentUrl, invId } = await response.json();
    if (invId) storePendingOrder(invId);
    window.location.href = paymentUrl;
  } catch {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
    alert("Не получилось начать оплату. Попробуйте ещё раз чуть позже.");
  }
}

["buyBtnHero", "buyBtnCta"].forEach((id) => {
  const btn = document.getElementById(id);
  if (btn) btn.addEventListener("click", () => startPurchase(btn));
});

// Скролл-реалы — сдержанно, уважают prefers-reduced-motion (CSS уже
// отключает саму transition в этом случае, тут просто навешиваем класс).
const revealEls = document.querySelectorAll("[data-reveal]");
if (revealEls.length && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15 }
  );
  revealEls.forEach((el) => observer.observe(el));
} else {
  revealEls.forEach((el) => el.classList.add("is-visible"));
}

// Оферта / политика — открываются во всплывающем окне поверх сайта, а не в новой вкладке.
const legalDocs = {
  oferta: { src: "assets/legal/oferta.html?v=2", title: "Договор публичной оферты" },
  privacy: { src: "assets/legal/privacy-policy.html?v=2", title: "Политика обработки персональных данных" },
};
const legalModal = document.getElementById("legalModal");
const legalModalFrame = document.getElementById("legalModalFrame");
const legalModalTitle = document.getElementById("legalModalTitle");
let legalModalLastTrigger = null;

function openLegalModal(key, trigger) {
  const doc = legalDocs[key];
  if (!doc || !legalModal) return;
  legalModalLastTrigger = trigger || null;
  legalModalTitle.textContent = doc.title;
  legalModalFrame.src = doc.src;
  legalModal.hidden = false;
  document.body.classList.add("legal-modal-open");
}

function closeLegalModal() {
  if (!legalModal || legalModal.hidden) return;
  legalModal.hidden = true;
  document.body.classList.remove("legal-modal-open");
  legalModalFrame.src = "about:blank";
  if (legalModalLastTrigger) legalModalLastTrigger.focus();
}

document.querySelectorAll("[data-legal-trigger]").forEach((btn) => {
  btn.addEventListener("click", () => openLegalModal(btn.dataset.legalTrigger, btn));
});

document.querySelectorAll("[data-legal-close]").forEach((el) => {
  el.addEventListener("click", closeLegalModal);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeLegalModal();
});

// Лог визита для статистики в админке (визиты, UTM-источники). Не блокирует
// отрисовку страницы и не мешает пользователю при сбое.
(function logVisit() {
  const params = new URLSearchParams(window.location.search);
  const payload = {
    utmSource: params.get("utm_source"),
    utmMedium: params.get("utm_medium"),
    utmCampaign: params.get("utm_campaign"),
    utmContent: params.get("utm_content"),
    utmTerm: params.get("utm_term"),
    referrer: document.referrer || null,
    landingPath: window.location.pathname,
    userAgent: navigator.userAgent,
  };
  fetch("/api/log-visit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {});
})();
