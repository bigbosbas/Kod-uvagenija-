// Старый сайт клиента (nagaichenkopsy.com и app.) выводим из поиска: его DNS
// направлен на этот же сервер, и на любой адрес этих доменов отвечаем
// 410 Gone + noindex. С 410 Яндекс и Google снимают страницы быстрее, чем с
// редиректом. robots.txt закрывает сайт только для Яндекса: его «Удаление по
// префиксу» в Вебмастере требует Disallow. Для остальных (Google) сайт открыт,
// иначе робот не зайдёт, не увидит 410/noindex и оставит страницы в выдаче.
// Маунтится до /api — иначе старые пути вроде app.…/api/order попали бы в
// API лендингов.
const OLD_HOSTS = new Set(
  (process.env.OLD_SITE_HOSTS || "nagaichenkopsy.com,www.nagaichenkopsy.com,app.nagaichenkopsy.com")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean)
);

// Открытый канал клиента (ссылку дал сам клиент 18.10.2026). Переменная
// окружения OLD_SITE_CHANNEL_URL при необходимости её переопределяет.
const DEFAULT_CHANNEL_URL = "https://t.me/+010Tt_USoMc4ZTRi";

// Ссылка на канал — только t.me, чтобы из переменной окружения в HTML не
// попало что-то постороннее.
function channelUrl() {
  const raw = (process.env.OLD_SITE_CHANNEL_URL || DEFAULT_CHANNEL_URL).trim();
  return /^https:\/\/t\.me\/[A-Za-z0-9_+\/-]+$/.test(raw) ? raw : "";
}

// Куда теперь ведём людей со старого адреса. Канал — первым, если задан.
function destinations() {
  const list = [
    { kind: "Курс", title: "Код уважения", href: "https://kod.privatebotrus.ru/", host: "kod.privatebotrus.ru" },
    { kind: "Курс", title: "Пересборка", href: "https://peresborka.privatebotrus.ru/", host: "peresborka.privatebotrus.ru" },
    { kind: "Вебинар", title: "Измена, обида и предательство", href: "https://webinar.nagaichenkopsy.com/", host: "webinar.nagaichenkopsy.com" },
  ];
  const channel = channelUrl();
  // У ссылки-приглашения (t.me/+…) хвост нечитаемый — показываем просто t.me.
  const host = channel.includes("/+") ? "t.me" : channel.replace("https://", "");
  if (channel) list.unshift({ kind: "Telegram", title: "Канал Руслана", href: channel, host });
  return list;
}

// Стилистика лендингов kod./peresborka.: бумажный фон, чернильный текст,
// золото, Cormorant Garamond + Manrope. Инфографика «старый адрес → куда
// переехало»: зачёркнутый домен и золотая ветка к новым адресам.
function renderPage() {
  const items = destinations()
    .map(
      (d) => `
      <li class="node">
        <span class="stem" aria-hidden="true"></span>
        <a class="dest" href="${d.href}" rel="noopener">
          <span class="dest__kind">${d.kind}</span>
          <span class="dest__title">${d.title}</span>
          <span class="dest__host">${d.host}</span>
          <svg class="dest__arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </a>
      </li>`
    )
    .join("");
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Сайт переехал — Руслан Нагайченко</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;1,600&family=Manrope:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --ink: #0b1821; --paper: #f5f1e9; --paper-warm: #eae0d1; --white: #fffdf8;
    --gold: #d8ae63; --gold-light: #ebcb91; --gold-dark: #9e7437;
    --muted: #66717a; --divider: rgba(11, 24, 33, 0.14);
    --card: var(--white); --text: var(--ink); --eyebrow: var(--gold-dark);
    --font-display: "Cormorant Garamond", Georgia, serif;
    --font-ui: "Manrope", Arial, sans-serif;
    --ease: cubic-bezier(0.16, 1, 0.3, 1);
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --paper: #0b1821; --paper-warm: #172532; --card: #132331; --text: #f5f1e9;
      --muted: #9aa6b0; --divider: rgba(235, 203, 145, 0.18); --eyebrow: var(--gold-light);
      color-scheme: dark;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    padding: 40px max(16px, env(safe-area-inset-right)) 40px max(16px, env(safe-area-inset-left));
    background:
      radial-gradient(900px 500px at 85% -10%, rgba(216, 174, 99, 0.18), transparent 60%),
      radial-gradient(700px 420px at -10% 110%, rgba(216, 174, 99, 0.12), transparent 60%),
      linear-gradient(180deg, var(--paper), var(--paper-warm));
    color: var(--text); font: 400 16px/1.6 var(--font-ui);
    -webkit-font-smoothing: antialiased;
  }
  main { width: 100%; max-width: 560px; display: grid; gap: 28px; }
  .eyebrow { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; color: var(--eyebrow); }
  h1 { margin: 8px 0 0; font: 600 clamp(2.4rem, 7vw, 3.4rem)/1.02 var(--font-display); letter-spacing: -0.01em; text-wrap: balance; }
  h1 em { font-style: italic; color: var(--gold-dark); }
  @media (prefers-color-scheme: dark) { h1 em { color: var(--gold-light); } }
  .lead { margin: 12px 0 0; color: var(--muted); max-width: 42ch; }

  /* инфографика: было → стало */
  .map { display: grid; gap: 0; }
  .old {
    justify-self: start; display: inline-flex; align-items: center; gap: 12px;
    padding: 10px 16px; border-radius: 999px; border: 1px dashed var(--divider);
    color: var(--muted); font-size: 0.92rem;
  }
  .old__tag { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; }
  .old__host { text-decoration: line-through; text-decoration-color: var(--gold); text-decoration-thickness: 2px; }
  .tree { list-style: none; margin: 0; padding: 18px 0 0 28px; display: grid; gap: 12px; }
  .node { position: relative; padding-left: 26px; }
  /* ствол ветки сплошной: каждый узел тянет линию от зазора над собой до
     своего низа, последний — только до центра, чтобы ствол заканчивался ровно
     на нём при любой высоте карточек */
  .node > .stem { position: absolute; left: -6px; top: -12px; bottom: 0; width: 2px; background: var(--gold); }
  .node:first-child > .stem { top: -18px; }
  .node:last-child > .stem { bottom: auto; height: calc(50% + 12px); }
  .node:first-child:last-child > .stem { height: calc(50% + 18px); }
  .node::before { content: ""; position: absolute; left: -6px; top: 50%; width: 32px; height: 2px; background: var(--gold); }
  .node::after {
    content: ""; position: absolute; left: -11px; top: 50%; width: 12px; height: 12px; margin-top: -5px;
    border-radius: 50%; background: var(--paper); border: 2px solid var(--gold);
  }
  .dest {
    display: grid; grid-template-columns: 1fr auto; grid-template-areas: "kind arrow" "title arrow" "host arrow";
    align-items: center; column-gap: 16px; padding: 16px 20px; border-radius: 14px;
    background: var(--card); border: 1px solid var(--divider); color: inherit; text-decoration: none;
    box-shadow: 0 10px 30px -18px rgba(11, 24, 33, 0.35);
    transition: transform 220ms var(--ease), border-color 220ms var(--ease), box-shadow 220ms var(--ease);
  }
  .dest:hover { transform: translateX(4px); border-color: var(--gold); box-shadow: 0 14px 34px -16px rgba(158, 116, 55, 0.45); }
  .dest:focus-visible { outline: 3px solid var(--gold); outline-offset: 3px; }
  .dest__kind { grid-area: kind; font-size: 0.66rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: var(--eyebrow); }
  .dest__title { grid-area: title; font: 600 1.6rem/1.1 var(--font-display); margin-top: 2px; }
  .dest__host { grid-area: host; font-size: 0.84rem; color: var(--muted); margin-top: 4px; overflow-wrap: anywhere; }
  .dest__arrow { grid-area: arrow; width: 22px; height: 22px; color: var(--gold-dark); }
  @media (prefers-color-scheme: dark) { .dest__arrow { color: var(--gold-light); } }
  .foot { font-size: 0.82rem; color: var(--muted); border-top: 1px solid var(--divider); padding-top: 16px; }
  @media (prefers-reduced-motion: reduce) { .dest { transition: none; } .dest:hover { transform: none; } }
</style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Руслан Нагайченко</div>
    <h1>Сайт <em>переехал</em></h1>
    <p class="lead">Старый адрес больше не работает. Всё актуальное теперь по новым ссылкам.</p>
  </header>
  <section class="map" aria-label="Куда переехал сайт">
    <div class="old"><span class="old__tag">было</span><span class="old__host">nagaichenkopsy.com</span></div>
    <ul class="tree">${items}
    </ul>
  </section>
  <p class="foot">Если вы пришли по старой ссылке из Telegram — просто выберите нужное выше.</p>
</main>
</body>
</html>`;
}

function oldSiteGone(req, res, next) {
  if (!OLD_HOSTS.has(String(req.hostname || "").toLowerCase())) return next();

  if (req.path === "/robots.txt") {
    res.type("text/plain").set("Cache-Control", "no-cache").send("User-agent: Yandex\nDisallow: /\n\nUser-agent: *\nAllow: /\n");
    return;
  }
  res
    .status(410)
    .set("X-Robots-Tag", "noindex, nofollow")
    .set("Cache-Control", "no-cache")
    .type("html")
    .send(req.method === "HEAD" ? "" : renderPage());
}

module.exports = { oldSiteGone, OLD_HOSTS };
