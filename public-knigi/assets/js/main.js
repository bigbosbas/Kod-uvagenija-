// Лендинг книг. Здесь только анимации и кнопки «Купить PDF»; доступ к файлу
// проверяется на сервере (как у «Кода уважения»), не в этом скрипте.
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Появление блоков при прокрутке + счётчики в .stats
  const countUp = (el) => {
    const target = Number(el.dataset.count);
    if (!target || reduce) return;
    const start = performance.now();
    const dur = 900;
    const tick = (now) => {
      const p = Math.min(1, (now - start) / dur);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    };
    el.textContent = "0";
    requestAnimationFrame(tick);
  };

  const items = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    items.forEach((el) => el.classList.add("is-in"));
  } else {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        e.target.classList.add("is-in");
        e.target.querySelectorAll("[data-count]").forEach(countUp);
        io.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.12 });
    items.forEach((el) => io.observe(el));
  }

  // Оферта / политика — во всплывающем окне поверх сайта, как на «Пересборке».
  const legalDocs = {
    oferta: { src: "assets/legal/oferta.html?v=1", title: "Договор публичной оферты" },
    privacy: { src: "assets/legal/privacy-policy.html?v=1", title: "Политика обработки персональных данных" },
  };
  const legalModal = document.getElementById("legalModal");
  const legalFrame = document.getElementById("legalModalFrame");
  const legalTitle = document.getElementById("legalModalTitle");
  let legalTrigger = null;
  const openLegal = (key, trigger) => {
    const doc = legalDocs[key];
    if (!doc || !legalModal) return;
    legalTrigger = trigger || null;
    legalTitle.textContent = doc.title;
    legalFrame.src = doc.src;
    legalModal.hidden = false;
    document.body.classList.add("legal-modal-open");
    legalModal.querySelector(".legal-modal__close").focus();
  };
  const closeLegal = () => {
    if (!legalModal || legalModal.hidden) return;
    legalModal.hidden = true;
    document.body.classList.remove("legal-modal-open");
    legalFrame.src = "about:blank";
    if (legalTrigger) legalTrigger.focus();
  };
  document.querySelectorAll("[data-legal-trigger]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault(); // кнопка внутри <label> согласия — не переключать галочку
      openLegal(btn.dataset.legalTrigger, btn);
    });
  });
  document.querySelectorAll("[data-legal-close]").forEach((el) => el.addEventListener("click", closeLegal));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLegal(); });

  // ---------- Доступ к купленным книгам ----------
  // Схема как у «Кода уважения»: токен приходит в ?access= (после оплаты или
  // из админки), сервер по нему отдаёт временную ссылку на PDF. Книг две,
  // поэтому храним в этом браузере список токенов, а не один.
  const TOKENS_KEY = "knigiAccessTokens";
  const PENDING_KEY = "knigiPendingOrder";
  const PENDING_MAX_AGE_MS = 2 * 60 * 60 * 1000;
  const BOOK_TITLES = {
    book_vliyanie: "Невидимая энергия влияния",
    book_obshchenie: "Скрытая власть общения",
  };

  const readTokens = () => {
    try { const v = JSON.parse(localStorage.getItem(TOKENS_KEY) || "[]"); return Array.isArray(v) ? v.filter((t) => typeof t === "string") : []; }
    catch { return []; }
  };
  const writeTokens = (list) => { try { localStorage.setItem(TOKENS_KEY, JSON.stringify(list.slice(-6))); } catch {} };
  const readPending = () => {
    try {
      const { invId, ts } = JSON.parse(localStorage.getItem(PENDING_KEY) || "null") || {};
      return invId && Date.now() - ts < PENDING_MAX_AGE_MS ? invId : null;
    } catch { return null; }
  };
  const clearPending = () => { try { localStorage.removeItem(PENDING_KEY); } catch {} };

  const overlay = document.getElementById("downloadOverlay");
  const overlayList = document.getElementById("downloadList");
  const shown = new Set();
  const showDownload = (product, url) => {
    if (!overlay || shown.has(product)) return;
    shown.add(product);
    const row = document.createElement("a");
    row.className = "btn btn--primary btn--wide";
    row.href = url;
    row.rel = "noopener";
    row.textContent = `Скачать «${BOOK_TITLES[product] || "книгу"}»`;
    overlayList.append(row);
    overlay.hidden = false;
  };
  document.getElementById("downloadOverlayClose")?.addEventListener("click", () => { overlay.hidden = true; });

  const verify = async (token) => {
    try {
      const res = await fetch("/api/verify-access?token=" + encodeURIComponent(token));
      const data = await res.json();
      if (data.valid && data.downloadUrl && BOOK_TITLES[data.product]) {
        showDownload(data.product, data.downloadUrl);
        return true;
      }
    } catch {}
    return false;
  };

  (async function initAccess() {
    const params = new URLSearchParams(location.search);
    const urlToken = params.get("access");
    let tokens = readTokens();
    if (urlToken) {
      params.delete("access");
      const q = params.toString();
      history.replaceState({}, "", location.pathname + (q ? "?" + q : "") + location.hash);
      if (!tokens.includes(urlToken)) tokens.push(urlToken);
    }
    // Оплата могла подтвердиться, пока человек был не на странице успеха.
    const pending = readPending();
    if (pending) {
      try {
        const res = await fetch("/api/check-payment?order=" + encodeURIComponent(pending));
        const data = await res.json();
        if (data.paid && data.accessToken) {
          if (!tokens.includes(data.accessToken)) tokens.push(data.accessToken);
          clearPending();
        }
      } catch {}
    }
    const valid = [];
    for (const t of tokens) if (await verify(t)) valid.push(t);
    writeTokens(valid);
  })();

  // ---------- Покупка ----------
  const consent = document.getElementById("consent");
  const hint = document.getElementById("consentHint");
  const consentLabel = consent && consent.closest(".consent");
  consent && consent.addEventListener("change", () => {
    if (consent.checked) { hint.hidden = true; consentLabel.classList.remove("is-error"); }
  });
  document.querySelectorAll("[data-buy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!consent.checked) {
        hint.textContent = "Отметьте согласие с офертой, чтобы перейти к оплате.";
        hint.hidden = false;
        consentLabel.classList.add("is-error");
        consentLabel.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
        return;
      }
      startPurchase(btn);
    });
  });

  async function startPurchase(btn) {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Переходим к оплате…";
    try {
      const res = await fetch("/api/create-payment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product: btn.dataset.buy }),
      });
      if (!res.ok) throw new Error("payment init failed");
      const { paymentUrl, invId } = await res.json();
      if (invId) { try { localStorage.setItem(PENDING_KEY, JSON.stringify({ invId, ts: Date.now() })); } catch {} }
      location.href = paymentUrl;
    } catch {
      btn.disabled = false;
      btn.textContent = original;
      hint.textContent = "Не получилось начать оплату. Попробуйте ещё раз чуть позже.";
      hint.hidden = false;
    }
  }

  // ---------- Лог визита (UTM) для статистики в админке ----------
  (function logVisit() {
    const params = new URLSearchParams(location.search);
    fetch("/api/log-visit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        utmSource: params.get("utm_source"),
        utmMedium: params.get("utm_medium"),
        utmCampaign: params.get("utm_campaign"),
        utmContent: params.get("utm_content"),
        utmTerm: params.get("utm_term"),
        referrer: document.referrer || null,
        landingPath: location.pathname,
        userAgent: navigator.userAgent,
      }),
      keepalive: true,
    }).catch(() => {});
  })();
})();
