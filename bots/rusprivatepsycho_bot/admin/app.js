lucide.createIcons();
var tg = window.Telegram.WebApp;

tg.ready();
tg.expand();
tg.setHeaderColor('#f4f4f5');
tg.setBackgroundColor('#f4f4f5');

if (typeof tg.disableVerticalSwipes === 'function') {
    tg.disableVerticalSwipes();
}

if (typeof tg.enableClosingConfirmation === 'function') {
    tg.enableClosingConfirmation();
}

if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
    document.getElementById('adminName').textContent = tg.initDataUnsafe.user.first_name + ' (Admin)';
}

var mainScreen = document.getElementById('mainScreen');
var subpage = document.getElementById('subpage');
var subpageTitle = document.getElementById('subpageTitle');
var subpageContent = document.getElementById('subpageContent');
var closeSubpageBtn = document.getElementById('closeSubpageBtn');
var buttons = document.querySelectorAll('.admin-btn');

function api(path, opts) {
    opts = opts || {};
    var timeoutMs = 12000;
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
    var headers = Object.assign({
        'X-Telegram-Init-Data': tg.initData || '',
        'Accept': 'application/json'
    }, opts.headers || {});
    if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, Object.assign({}, opts, { headers: headers, signal: controller.signal }))
        .then(function (resp) {
            clearTimeout(timer);
            return resp;
        })
        .catch(function () {
            clearTimeout(timer);
            return {
                ok: false,
                status: 0,
                json: function () {
                    return Promise.resolve({
                        ok: false,
                        error: 'Сервер недоступен или долго не отвечает'
                    });
                }
            };
        });
}

function esc(s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

function fmtNum(n) {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('ru-RU');
}

function fmtPaymentDt(iso) {
    if (!iso) return '—';
    var t = Date.parse(iso);
    if (isNaN(t)) return String(iso);
    return new Date(t).toLocaleString('ru-RU', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function loadStats() {
    api('/api/admin/stats').then(function (r) { return r.json(); }).then(function (d) {
        if (d.ok) document.getElementById('statActiveCount').textContent = fmtNum(d.users_active);
    }).catch(function () {});
}
loadStats();

var paySheetRoot = document.getElementById('paySheetRoot');
var paySheetBody = document.getElementById('paySheetBody');
var paySheetUidEl = document.getElementById('paySheetUid');

function closePaySheet() {
    paySheetRoot.classList.remove('pay-sheet-visible');
    paySheetRoot.setAttribute('aria-hidden', 'true');
    if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
}

function openPaySheet(uid) {
    paySheetUidEl.textContent = 'Пользователь ID: ' + uid;
    paySheetBody.innerHTML = '<p class="text-sm text-gray-500 py-6 text-center">Загрузка…</p>';
    paySheetRoot.classList.add('pay-sheet-visible');
    paySheetRoot.setAttribute('aria-hidden', 'false');
    if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    api('/api/admin/users/' + uid + '/payments')
        .then(function (r) { return r.json(); })
        .then(function (pay) {
            if (!pay.ok) {
                paySheetBody.innerHTML = '<p class="text-red-600 text-sm p-4 text-center">' + esc(pay.error || 'Ошибка') + '</p>';
                return;
            }
            if (!pay.payments.length) {
                paySheetBody.innerHTML =
                    '<div class="bg-white rounded-3xl p-8 premium-shadow border border-gray-100 text-center">' +
                    '<p class="text-gray-500 text-[15px]">Нет платежей</p></div>';
                lucide.createIcons();
                return;
            }
            var html = '<div class="admin-pay-list">';
            pay.payments.forEach(function (p) {
                html += generatePaymentRow(
                    Object.assign({}, p, { labelRight: '№ ' + p.id })
                );
            });
            html += '</div>';
            paySheetBody.innerHTML = html;
            lucide.createIcons();
        });
}

document.getElementById('paySheetClose').addEventListener('click', closePaySheet);
document.getElementById('paySheetBackdrop').addEventListener('click', closePaySheet);

function pad2(n) {
    return n < 10 ? '0' + n : String(n);
}

function todayYmdLocal() {
    var d = new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}

function isoToYmdLocal(iso) {
    if (!iso) return null;
    var t = Date.parse(iso);
    if (isNaN(t)) return null;
    var d = new Date(t);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}

function ymdAddDays(ymd, days) {
    var p = ymd.split('-');
    var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    d.setDate(d.getDate() + days);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}

var grantTargetUid = null;
var grantAfterSave = null;
var grantNotifyUser = true;

function closeGrantSheet() {
    document.getElementById('grantSheetRoot').classList.remove('pay-sheet-visible');
    document.getElementById('grantSheetRoot').setAttribute('aria-hidden', 'true');
    grantTargetUid = null;
    grantAfterSave = null;
    grantNotifyUser = true;
    if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
}

function openGrantSheet(uid, hintIso, afterSave, mode) {
    grantTargetUid = uid;
    grantAfterSave = typeof afterSave === 'function' ? afterSave : null;
    var manual = mode === 'manual';
    grantNotifyUser = manual;
    var titleEl = document.getElementById('grantSheetTitle');
    if (titleEl) {
        titleEl.textContent = manual ? 'Выдать доступ вручную' : 'Продлить подписку';
    }
    var hintEl = document.getElementById('grantSheetHint');
    if (hintEl) {
        hintEl.textContent = manual
            ? 'Пользователь получит сообщение от бота с одноразовой ссылкой на вступление в канал. Срок — до конца выбранного дня по Москве.'
            : 'Обновится только дата окончания в базе (до конца выбранного дня по Москве). Сообщение пользователю не отправляется.';
    }
    document.getElementById('grantSheetUserLine').textContent = 'Пользователь ID: ' + uid;
    var inp = document.getElementById('grantSheetDate');
    var min = todayYmdLocal();
    inp.min = min;
    var def = isoToYmdLocal(hintIso);
    if (!def || def < min) def = ymdAddDays(min, 7);
    inp.value = def;
    var root = document.getElementById('grantSheetRoot');
    root.classList.add('pay-sheet-visible');
    root.setAttribute('aria-hidden', 'false');
    if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
}

document.getElementById('grantSheetBackdrop').addEventListener('click', closeGrantSheet);
document.getElementById('grantSheetCancel').addEventListener('click', closeGrantSheet);
document.getElementById('grantSheetSave').addEventListener('click', function () {
    if (grantTargetUid == null) return;
    var v = document.getElementById('grantSheetDate').value;
    if (!v) {
        alert('Выберите дату');
        return;
    }
    var min = todayYmdLocal();
    if (v < min) {
        alert('Дата не может быть в прошлом');
        return;
    }
    var cb = grantAfterSave;
    api('/api/admin/users/' + grantTargetUid + '/grant', {
        method: 'POST',
        body: { expires_date: v, notify_user: grantNotifyUser },
    })
        .then(function (r) { return r.json(); })
        .then(function (x) {
            if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(x.ok ? 'success' : 'error');
            if (!x.ok) {
                alert(x.error || 'Ошибка');
                return;
            }
            closeGrantSheet();
            if (cb) cb();
        });
});

function subscriptionExpiresMs(u) {
    var s = u.subscription_expires_at;
    if (!s) return null;
    var t = Date.parse(s);
    return isNaN(t) ? null : t;
}

function userCanRenewSubscription(u) {
    if (u.blocked) return false;
    var st = u.subscription_status || '';
    if (st === 'blocked') st = '';
    var expMs = subscriptionExpiresMs(u);
    var now = Date.now();
    if (
        expMs != null &&
        expMs > now &&
        st !== 'expired' &&
        st !== 'blocked'
    ) {
        return true;
    }
    if (st === 'active' && expMs == null) return true;
    return false;
}

function subscriptionBadgeForUser(u) {
    if (u.blocked) {
        return { badgeBg: 'bg-red-50', badgeText: 'text-red-500', status: 'Заблокирован' };
    }
    var st = u.subscription_status || '';
    if (st === 'blocked') {
        st = '';
    }
    var expMs = subscriptionExpiresMs(u);
    var now = Date.now();
    var live =
        expMs != null &&
        expMs > now &&
        st !== 'expired' &&
        st !== 'blocked';
    if (live) {
        return { badgeBg: 'bg-blue-50', badgeText: 'text-[var(--brand-blue)]', status: u.plan_title || 'Активна' };
    }
    if (st === 'active' && expMs == null) {
        return { badgeBg: 'bg-blue-50', badgeText: 'text-[var(--brand-blue)]', status: u.plan_title || 'Активна' };
    }
    if (st === 'expired' || (expMs != null && expMs <= now && st !== 'blocked')) {
        return { badgeBg: 'bg-red-50', badgeText: 'text-red-500', status: 'Просрочено' };
    }
    if (st === 'inactive' || st === '') {
        return { badgeBg: 'bg-gray-100', badgeText: 'text-gray-600', status: 'Нет подписки' };
    }
    return { badgeBg: 'bg-gray-100', badgeText: 'text-gray-600', status: st ? String(st) : '—' };
}

function ruPaymentStatus(s) {
    var m = {
        pending: 'Ожидает',
        paid: 'Оплачен',
        failed: 'Ошибка',
        cancelled: 'Отменён',
        inactive: 'Не активен'
    };
    if (s == null || s === '') return '—';
    return m[s] || String(s);
}

function generateUserRow(name, tag, id, badgeBg, badgeText, status) {
    return (
        '<div class="flex items-center justify-between gap-2">' +
        '<div class="flex items-center gap-3 min-w-0 flex-1">' +
        '<div class="w-10 h-10 shrink-0 bg-gray-100 rounded-full flex items-center justify-center text-gray-500 font-medium text-sm uppercase">' +
        esc(name.charAt(0) || '?') + '</div>' +
        '<div class="min-w-0">' +
        '<p class="font-medium text-gray-900 text-[15px] leading-tight truncate">' + esc(name) + '</p>' +
        '<p class="text-[13px] text-gray-500 truncate">' + esc(tag) + ' • ' + esc(id) + '</p>' +
        '</div></div>' +
        '<span class="text-[11px] font-medium px-2 py-1 rounded-lg shrink-0 ' + badgeBg + ' ' + badgeText + '">' + esc(status) + '</span>' +
        '</div>'
    );
}

function userPlaqueFromApi(u) {
    var name = [u.first_name, u.last_name].filter(Boolean).join(' ').trim() || '—';
    var tag = u.username ? '@' + u.username : 'нет username';
    var id = 'ID: ' + u.user_id;
    var b = subscriptionBadgeForUser(u);
    var canRenew = userCanRenewSubscription(u);
    var blocked = !!u.blocked;
    var accessBtn = '';
    if (!blocked) {
        if (canRenew) {
            accessBtn =
                '<button type="button" class="user-grant-renew col-span-2 bg-[var(--brand-blue)] text-white text-[12px] font-medium py-2.5 rounded-2xl active:scale-[0.98] transition-transform leading-tight">Продлить подписку</button>';
        } else {
            accessBtn =
                '<button type="button" class="user-grant-manual col-span-2 bg-[var(--brand-blue)] text-white text-[12px] font-medium py-2.5 rounded-2xl active:scale-[0.98] transition-transform leading-tight">Выдать доступ вручную</button>';
        }
    } else {
        accessBtn =
            '<button type="button" class="col-span-2 bg-gray-200 text-gray-400 text-[12px] font-medium py-2.5 rounded-2xl cursor-not-allowed leading-tight" disabled>Сначала разблокируйте пользователя</button>';
    }
    var blockToggleCls =
        'user-block-toggle text-[12px] font-medium py-2.5 rounded-2xl active:scale-[0.98] transition-transform leading-tight ' +
        (blocked ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-700');
    var blockToggleLabel = blocked ? 'Разблокировать' : 'Заблокировать';
    var top = generateUserRow(name, tag, id, b.badgeBg, b.badgeText, b.status);
    return (
        '<div class="user-card-wrap bg-white p-3.5 rounded-2xl border border-gray-100 premium-shadow flex flex-col gap-0 mb-3" data-uid="' +
        u.user_id +
        '" data-expires="' +
        encodeURIComponent(u.subscription_expires_at || '') +
        '" data-blocked="' +
        (blocked ? '1' : '0') +
        '">' +
        top +
        '<div class="mt-3 pt-3 border-t border-gray-100 grid grid-cols-2 gap-2">' +
        accessBtn +
        '<button type="button" class="user-revoke bg-gray-100 text-gray-900 text-[12px] font-medium py-2.5 rounded-2xl active:scale-[0.98] transition-transform leading-tight">Убрать из канала</button>' +
        '<button type="button" class="' +
        blockToggleCls +
        '">' +
        esc(blockToggleLabel) +
        '</button>' +
        '</div>' +
        '<button type="button" class="user-pay-sheet w-full mt-2 text-[13px] text-[var(--brand-blue)] font-medium py-2.5 rounded-2xl bg-white border border-gray-200 premium-shadow active:scale-[0.98] transition-transform">История оплат</button>' +
        '</div>'
    );
}

function generatePaymentRow(p) {
    var st = p.status || '';
    var amount = (p.amount_rub != null ? p.amount_rub : '') + ' ₽';
    var title = (p.plan_title || '—') + ' · ' + ruPaymentStatus(st);
    var when = fmtPaymentDt(p.created_at || '');
    var uidLine =
        p.labelRight != null && p.labelRight !== ''
            ? String(p.labelRight)
            : 'ID ' + (p.user_id != null ? p.user_id : '—');
    var cardMod = st === 'pending' ? ' admin-pay-card--pending' : '';
    var hint = st === 'pending' ? '<p class="admin-pay-card__hint">Не оплачен — ждёт подтверждения в Robokassa</p>' : '';
    return (
        '<div class="admin-pay-card' + cardMod + '">' +
        '<div class="admin-pay-card__left">' +
        '<p class="admin-pay-card__amount">' + esc(amount) + '</p>' +
        '<p class="admin-pay-card__title">' + esc(title) + '</p>' +
        hint +
        '</div>' +
        '<div class="admin-pay-card__right">' +
        '<p class="admin-pay-card__uid">' + esc(uidLine) + '</p>' +
        '<p class="admin-pay-card__when">' + esc(when) + '</p>' +
        '</div></div>'
    );
}

function generatePlanRow(title, price, desc, isActive, code) {
    return (
        '<div class="bg-white p-4 rounded-3xl border border-gray-100 premium-shadow flex items-center justify-between ' + (!isActive ? 'opacity-60' : '') + '">' +
        '<div class="min-w-0 flex-1">' +
        '<div class="flex items-center gap-2 mb-1 flex-wrap">' +
        '<h4 class="font-semibold text-gray-900">' + esc(title) + '</h4>' +
        (!isActive ? '<span class="text-[10px] bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded">Выкл</span>' : '') +
        '</div>' +
        '<p class="text-sm font-medium text-[var(--brand-blue)] mb-0.5">' + esc(price) + '</p>' +
        '<p class="text-[12px] text-gray-500">' + esc(desc) + '</p>' +
        '<p class="text-[11px] text-gray-400 mt-1 font-mono">' + esc(code) + '</p>' +
        '</div>' +
        '<div class="flex flex-col gap-1 shrink-0">' +
        '<button type="button" class="plan-edit p-2 bg-gray-50 rounded-xl text-gray-600 active:bg-gray-100" data-code="' + esc(code) + '">' +
        '<i data-lucide="edit-2" class="w-4 h-4"></i></button>' +
        '<button type="button" class="plan-toggle text-[11px] px-2 py-1 rounded-lg ' + (isActive ? 'bg-amber-100 text-amber-900' : 'bg-green-100 text-green-900') + '" data-code="' + esc(code) + '" data-next="' + (isActive ? '0' : '1') + '">' +
        (isActive ? 'Выкл' : 'Вкл') + '</button></div></div>'
    );
}

function renderUsersList(titleText, mode) {
    var limit = 40;
    var offset = 0;
    var searchQ = '';

    function fetchPage() {
        subpageContent.innerHTML = '<p class="text-sm text-gray-500 p-2">Загрузка…</p>';
        var q = searchQ.trim() ? '&q=' + encodeURIComponent(searchQ.trim()) : '';
        api('/api/admin/users?mode=' + encodeURIComponent(mode) + '&limit=' + limit + '&offset=' + offset + q)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) {
                    subpageContent.innerHTML = '<p class="text-red-600 text-sm">' + esc(d.error || 'Ошибка') + '</p>';
                    lucide.createIcons();
                    return;
                }
                var hint = (d.total != null) ? '<p class="text-sm text-gray-500 mb-1 ml-1">Записей: ' + d.total + '</p>' : '';
                var html = hint +
                    '<div class="relative mb-3">' +
                    '<i data-lucide="search" class="absolute left-3 top-3 w-5 h-5 text-gray-400"></i>' +
                    '<input type="text" id="userSearchInput" placeholder="Поиск по ID или нику..." class="w-full bg-white border border-gray-200 rounded-2xl py-2.5 pl-10 pr-4 text-[15px] outline-none focus:border-[var(--brand-blue)]" value="' + esc(searchQ) + '">' +
                    '</div>';
                if (!d.users.length) html += '<p class="text-gray-500 text-sm">Пусто</p>';
                d.users.forEach(function (u) { html += userPlaqueFromApi(u); });
                var totalUsers = d.total != null ? d.total : null;
                var canPrev = offset > 0;
                var canNext = totalUsers != null
                    ? offset + d.users.length < totalUsers
                    : d.users.length >= limit;
                if (canPrev || canNext) {
                    html += '<div class="flex gap-2 mt-2">';
                    if (canPrev) {
                        html += '<button type="button" id="usersPrev" class="flex-1 bg-white border border-gray-200 py-2.5 rounded-2xl text-[15px] font-medium">Назад</button>';
                    }
                    if (canNext) {
                        html += '<button type="button" id="usersNext" class="flex-1 bg-white border border-gray-200 py-2.5 rounded-2xl text-[15px] font-medium">Далее</button>';
                    }
                    html += '</div>';
                }
                subpageContent.innerHTML = html;
                lucide.createIcons();

                var si = document.getElementById('userSearchInput');
                var tmr;
                si.addEventListener('input', function () {
                    clearTimeout(tmr);
                    tmr = setTimeout(function () {
                        searchQ = si.value;
                        offset = 0;
                        fetchPage();
                    }, 350);
                });

                var prevU = document.getElementById('usersPrev');
                if (prevU) {
                    prevU.addEventListener('click', function () {
                        offset = Math.max(0, offset - limit);
                        fetchPage();
                    });
                }
                var nextU = document.getElementById('usersNext');
                if (nextU) {
                    nextU.addEventListener('click', function () {
                        offset += limit;
                        fetchPage();
                    });
                }

                subpageContent.querySelectorAll('.user-card-wrap').forEach(function (wrap) {
                    var uid = parseInt(wrap.getAttribute('data-uid'), 10);

                    wrap.querySelector('.user-pay-sheet').addEventListener('click', function () {
                        openPaySheet(uid);
                    });

                    var btnMan = wrap.querySelector('.user-grant-manual');
                    if (btnMan) {
                        btnMan.addEventListener('click', function () {
                            var raw = wrap.getAttribute('data-expires');
                            openGrantSheet(uid, raw ? decodeURIComponent(raw) : '', fetchPage, 'manual');
                        });
                    }
                    var btnRen = wrap.querySelector('.user-grant-renew');
                    if (btnRen) {
                        btnRen.addEventListener('click', function () {
                            var raw = wrap.getAttribute('data-expires');
                            openGrantSheet(uid, raw ? decodeURIComponent(raw) : '', fetchPage, 'renew');
                        });
                    }
                    wrap.querySelector('.user-revoke').addEventListener('click', function () {
                        if (!confirm('Убрать из канала и закрыть подписку?')) return;
                        api('/api/admin/users/' + uid + '/revoke', { method: 'POST', body: {} })
                            .then(function (r) { return r.json(); })
                            .then(function (x) {
                                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(x.ok ? 'success' : 'error');
                                alert(x.ok ? 'Готово' : (x.error || 'Ошибка'));
                                if (x.ok) fetchPage();
                            });
                    });
                    wrap.querySelector('.user-block-toggle').addEventListener('click', function () {
                        var curBlocked = wrap.getAttribute('data-blocked') === '1';
                        var nextBlocked = !curBlocked;
                        if (nextBlocked) {
                            if (!confirm('Заблокировать пользователя и убрать из канала?')) return;
                        }
                        api('/api/admin/users/' + uid + '/block', { method: 'POST', body: { blocked: nextBlocked } })
                            .then(function (r) { return r.json(); })
                            .then(function (x) {
                                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(x.ok ? 'success' : 'error');
                                alert(x.ok ? 'Готово' : (x.error || 'Ошибка'));
                                if (x.ok) fetchPage();
                            });
                    });
                });
            });
    }

    openSubpage(titleText);
    fetchPage();
}

function renderPayments() {
    var limit = 40;
    var offset = 0;
    var st = '';

    function load() {
        subpageContent.innerHTML = '<p class="text-sm text-gray-500">Загрузка…</p>';
        var qs = '?limit=' + limit + '&offset=' + offset + (st ? '&status=' + encodeURIComponent(st) : '');
        api('/api/admin/payments' + qs).then(function (r) { return r.json(); }).then(function (d) {
            if (!d.ok) {
                subpageContent.innerHTML = '<p class="text-red-600">' + esc(d.error) + '</p>';
                return;
            }
            var html =
                '<div class="admin-pay-toolbar">' +
                '<p class="admin-pay-toolbar__meta">Всего в выборке: <strong>' +
                (d.total != null ? d.total : '—') +
                '</strong></p>' +
                '<div class="admin-pay-filters">';
            ['', 'pending', 'paid', 'failed', 'cancelled'].forEach(function (s) {
                var on = st === s;
                var lab = s === '' ? 'Все' : ruPaymentStatus(s);
                var key = s === '' ? 'all' : s;
                html +=
                    '<button type="button" class="admin-pay-filter' +
                    (on ? ' admin-pay-filter--on' : '') +
                    '" data-st="' +
                    key +
                    '">' +
                    lab +
                    '</button>';
            });
            html += '</div></div><div class="admin-pay-list">';
            if (!d.payments.length) {
                html += '<p class="text-gray-500 text-sm py-2 px-1">Нет данных</p>';
            }
            d.payments.forEach(function (p) {
                html += generatePaymentRow(p);
            });
            var payTotal = d.total != null ? d.total : null;
            var payCanPrev = offset > 0;
            var payCanNext = payTotal != null
                ? offset + d.payments.length < payTotal
                : d.payments.length >= limit;
            html += '</div>';
            if (payCanPrev || payCanNext) {
                html += '<div class="admin-pay-pagebar">';
                if (payCanPrev) {
                    html += '<button type="button" id="payPrev">Назад</button>';
                }
                if (payCanNext) {
                    html += '<button type="button" id="payNext">Далее</button>';
                }
                html += '</div>';
            }
            subpageContent.innerHTML = html;
            lucide.createIcons();
            subpageContent.querySelectorAll('.admin-pay-filter').forEach(function (b) {
                b.addEventListener('click', function () {
                    var key = b.getAttribute('data-st') || 'all';
                    st = key === 'all' ? '' : key;
                    offset = 0;
                    load();
                });
            });
            var payP = document.getElementById('payPrev');
            if (payP) {
                payP.addEventListener('click', function () {
                    offset = Math.max(0, offset - limit);
                    load();
                });
            }
            var payN = document.getElementById('payNext');
            if (payN) {
                payN.addEventListener('click', function () {
                    offset += limit;
                    load();
                });
            }
        });
    }
    openSubpage('Платежи');
    load();
}

function renderPlans() {
    openSubpage('Тарифы');
    api('/api/admin/plans').then(function (r) { return r.json(); }).then(function (d) {
        if (!d.ok) {
            subpageContent.innerHTML = '<p class="text-red-600">Ошибка</p>';
            return;
        }
        var byCode = {};
        d.plans.forEach(function (p) { byCode[p.code] = p; });

        var html = '<button type="button" id="planScrollForm" class="w-full bg-[var(--brand-blue)] text-white font-medium py-3 rounded-2xl mb-2 active:scale-[0.98] transition-transform">+ Добавить тариф</button>' +
            '<div id="planFormWrap" class="bg-white p-4 rounded-3xl border border-gray-100 premium-shadow mb-3 hidden">' +
            '<input id="pCode" class="w-full border border-gray-200 rounded-2xl px-3 py-2 text-[15px] mb-2" placeholder="code">' +
            '<input id="pTitle" class="w-full border border-gray-200 rounded-2xl px-3 py-2 text-[15px] mb-2" placeholder="Название">' +
            '<div class="flex gap-2 mb-2"><input id="pPrice" type="number" class="w-1/2 border border-gray-200 rounded-2xl px-3 py-2 text-[15px]" placeholder="Цена ₽">' +
            '<input id="pDays" type="number" class="w-1/2 border border-gray-200 rounded-2xl px-3 py-2 text-[15px]" placeholder="Дней"></div>' +
            '<textarea id="pDesc" class="w-full border border-gray-200 rounded-2xl px-3 py-2 text-[15px] mb-2 h-20 resize-none" placeholder="Описание"></textarea>' +
            '<label class="flex items-center gap-2 text-[15px] mb-2"><input type="checkbox" id="pActive" checked> Активен</label>' +
            '<button type="button" id="pSave" class="w-full bg-gray-900 text-white font-medium py-2.5 rounded-2xl">Сохранить</button></div>';

        d.plans.forEach(function (p) {
            html += generatePlanRow(p.title, p.price_rub + ' ₽', p.description, p.is_active, p.code);
        });

        subpageContent.innerHTML = html;
        lucide.createIcons();

        document.getElementById('planScrollForm').addEventListener('click', function () {
            var w = document.getElementById('planFormWrap');
            w.classList.toggle('hidden');
            w.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });

        function fillForm(p) {
            document.getElementById('planFormWrap').classList.remove('hidden');
            document.getElementById('pCode').value = p.code;
            document.getElementById('pTitle').value = p.title;
            document.getElementById('pPrice').value = p.price_rub;
            document.getElementById('pDays').value = p.duration_days;
            document.getElementById('pDesc').value = p.description;
            document.getElementById('pActive').checked = p.is_active;
        }

        subpageContent.querySelectorAll('.plan-edit').forEach(function (b) {
            b.addEventListener('click', function () {
                var c = b.getAttribute('data-code');
                if (byCode[c]) fillForm(byCode[c]);
            });
        });
        subpageContent.querySelectorAll('.plan-toggle').forEach(function (b) {
            b.addEventListener('click', function () {
                var code = b.getAttribute('data-code');
                var active = b.getAttribute('data-next') === '1';
                api('/api/admin/plans/' + encodeURIComponent(code) + '/active', { method: 'POST', body: { active: active } })
                    .then(function (r) { return r.json(); })
                    .then(function (x) { if (x.ok) renderPlans(); else alert(x.error || 'Ошибка'); });
            });
        });
        document.getElementById('pSave').addEventListener('click', function () {
            api('/api/admin/plans', {
                method: 'POST',
                body: {
                    code: document.getElementById('pCode').value.trim(),
                    title: document.getElementById('pTitle').value.trim(),
                    price_rub: parseInt(document.getElementById('pPrice').value, 10),
                    duration_days: parseInt(document.getElementById('pDays').value, 10),
                    description: document.getElementById('pDesc').value.trim(),
                    is_active: document.getElementById('pActive').checked
                }
            }).then(function (r) { return r.json(); }).then(function (x) {
                alert(x.ok ? 'Сохранено' : (x.error || 'Ошибка'));
                if (x.ok) renderPlans();
            });
        });
    });
}

function renderSettings() {
    openSubpage('Настройки');
    api('/api/admin/settings').then(function (r) { return r.json(); }).then(function (d) {
        if (!d.ok) {
            subpageContent.innerHTML = '<p class="text-red-600">Нет доступа</p>';
            return;
        }
        var rows = [
            ['offer_url', 'Ссылка оферты', d.settings.offer_url || d.defaults.offer_url || '', 'short', 3],
            ['policy_url', 'Ссылка политики', d.settings.policy_url || d.defaults.policy_url || '', 'short', 3],
            ['channel_about_text', 'Текст канала', d.settings.channel_about_text || '', 'long', 10],
            ['tmpl_welcome', 'Шаблон приветствия', d.settings.tmpl_welcome || '', 'long', 10],
            ['promo_media_kind', 'Тип медиа (photo/video/document)', d.settings.promo_media_kind || '', 'short', 2],
            ['promo_media_file_id', 'file_id промо', d.settings.promo_media_file_id || '', 'short', 3]
        ];
        var html = '<div class="bg-white rounded-3xl border border-gray-100 premium-shadow flex flex-col gap-0 shrink-0">';
        rows.forEach(function (row, i) {
            var size = row[3];
            var taRows = row[4];
            var taClass =
                'w-full bg-gray-50 border border-gray-200 rounded-2xl p-3 text-[15px] outline-none focus:border-[var(--brand-blue)] resize-y box-border ' +
                (size === 'long' ? 'admin-settings-textarea--long' : 'admin-settings-textarea--short');
            html += '<div class="p-4 ' + (i < rows.length - 1 ? 'border-b border-gray-50' : '') + '">' +
                '<label class="text-[14px] font-medium text-gray-900 block mb-2">' + esc(row[1]) + '</label>' +
                '<textarea data-key="' + esc(row[0]) + '" rows="' + taRows + '" class="' + taClass + '">' + esc(row[2]) + '</textarea>' +
                '<button type="button" class="save-key mt-3 w-full bg-[var(--brand-blue)] text-white font-medium py-3 rounded-2xl text-[14px] active:scale-[0.99] transition-transform">Сохранить</button></div>';
        });
        html += '</div>';
        subpageContent.innerHTML = html;
        subpageContent.querySelectorAll('.save-key').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var wrap = btn.closest('div');
                var ta = wrap.querySelector('textarea');
                api('/api/admin/settings', { method: 'POST', body: { key: ta.getAttribute('data-key'), value: ta.value } })
                    .then(function (r) { return r.json(); })
                    .then(function (x) { alert(x.ok ? 'Сохранено' : (x.error || 'Ошибка')); });
            });
        });
    });
}

function renderSupport() {
    openSubpage('Поддержка');
    api('/api/admin/settings').then(function (r) { return r.json(); }).then(function (d) {
        if (!d.ok) {
            subpageContent.innerHTML = '<p class="text-red-600">Ошибка</p>';
            return;
        }
        var v = d.settings.support_text || '';
        subpageContent.innerHTML =
            '<div class="bg-white p-4 rounded-3xl border border-gray-100 premium-shadow flex flex-col gap-3 shrink-0">' +
            '<label class="text-sm font-medium text-gray-900">Текст поддержки</label>' +
            '<textarea id="supTa" rows="8" class="w-full bg-gray-50 border border-gray-200 rounded-2xl p-3 text-[15px] outline-none focus:border-[var(--brand-blue)] resize-y box-border admin-settings-textarea--long">' + esc(v) + '</textarea>' +
            '<button type="button" id="supSave" class="w-full bg-[var(--brand-blue)] text-white font-medium py-3 rounded-2xl active:scale-[0.98] transition-transform">Сохранить</button></div>';
        document.getElementById('supSave').addEventListener('click', function () {
            api('/api/admin/settings', { method: 'POST', body: { key: 'support_text', value: document.getElementById('supTa').value } })
                .then(function (r) { return r.json(); })
                .then(function (x) { alert(x.ok ? 'Сохранено' : (x.error || 'Ошибка')); });
        });
    });
}

function renderBroadcast() {
    if (window.adminBroadcastPoll) {
        clearInterval(window.adminBroadcastPoll);
        window.adminBroadcastPoll = null;
    }
    openSubpage('Рассылка');
    subpageContent.innerHTML =
        '<div class="admin-bc-card"><h3>Кому отправить</h3><div id="bcSegWrap" class="admin-bc-segments"></div>' +
        '<p class="admin-bc-audience">Получателей: <strong id="bcCount">—</strong></p></div>' +
        '<div class="admin-bc-card"><h3>Текст сообщения</h3>' +
        '<div class="admin-bc-text-shell"><textarea id="bcText" maxlength="4000" placeholder="До 4000 символов (лимит Telegram)"></textarea></div>' +
        '<p id="bcCounter" class="admin-bc-counter">0 / 4000</p></div>' +
        '<div class="admin-bc-card"><h3>Кнопки со ссылкой</h3><p class="text-[12px] text-gray-500 mb-2">Опционально, только http(s). До 8 шт.</p>' +
        '<div id="bcBtnRows"></div>' +
        '<button type="button" id="bcAddBtn" class="w-full mt-1 py-2.5 rounded-2xl border border-gray-200 bg-white text-[14px] font-medium text-gray-800 active:scale-[0.99] transition-transform">+ Добавить кнопку</button></div>' +
        '<div id="bcProgress" class="admin-bc-progress admin-bc-progress--run" style="display:none;"></div>' +
        '<div class="admin-bc-actions">' +
        '<button type="button" id="bcTest" class="admin-bc-secondary">Тест: отправить себе</button>' +
        '<button type="button" id="bcRun" class="admin-bc-primary">Запустить рассылку</button>' +
        '</div><p class="text-[11px] text-gray-400 px-1 mt-2 leading-relaxed">Между сообщениями ~0,05 с, чтобы не упереться в лимиты Telegram. Заблокировавшие бота не получат письмо (учтено в «пропущено»).</p>';

    var bcState = { segment: 'everyone', maxButtons: 8 };

    function collectBcButtons() {
        var out = [];
        subpageContent.querySelectorAll('.admin-bc-url-row').forEach(function (row) {
            var t = row.querySelector('.bc-btn-text');
            var u = row.querySelector('.bc-btn-url');
            if (t && u && t.value.trim() && u.value.trim()) {
                out.push({ text: t.value.trim(), url: u.value.trim() });
            }
        });
        return out;
    }

    function syncBcCounter() {
        var ta = document.getElementById('bcText');
        var c = document.getElementById('bcCounter');
        var n = ta && ta.value ? ta.value.length : 0;
        c.textContent = n + ' / 4000';
        c.className = 'admin-bc-counter' + (n >= 3800 ? ' admin-bc-counter--warn' : '');
    }

    function refreshBcCount() {
        document.getElementById('bcCount').textContent = '…';
        api('/api/admin/broadcast/count', { method: 'POST', body: { segment: bcState.segment } })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                document.getElementById('bcCount').textContent = d.ok ? String(d.count) : '—';
            });
    }

    function showBcProgress(msg, kind) {
        var el = document.getElementById('bcProgress');
        el.style.display = 'block';
        el.textContent = msg;
        el.className = 'admin-bc-progress ';
        if (kind === 'err') el.className += 'admin-bc-progress--err';
        else if (kind === 'run') el.className += 'admin-bc-progress--run';
        else el.className += 'admin-bc-progress--ok';
    }

    function pollBcJob(jobId) {
        if (window.adminBroadcastPoll) {
            clearInterval(window.adminBroadcastPoll);
            window.adminBroadcastPoll = null;
        }
        function tick() {
            api('/api/admin/broadcast/status?job_id=' + encodeURIComponent(jobId))
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d.ok || !d.job) return;
                    var j = d.job;
                    var runBtn = document.getElementById('bcRun');
                    var testBtn = document.getElementById('bcTest');
                    if (j.status === 'running') {
                        showBcProgress(
                            'Отправка: ' + j.sent + ' из ' + (j.total || '…') + ' · ошибок: ' + j.failed + ' · пропущено: ' + j.skipped,
                            'run'
                        );
                        if (runBtn) runBtn.disabled = true;
                        if (testBtn) testBtn.disabled = true;
                    } else {
                        if (window.adminBroadcastPoll) {
                            clearInterval(window.adminBroadcastPoll);
                            window.adminBroadcastPoll = null;
                        }
                        if (runBtn) runBtn.disabled = false;
                        if (testBtn) testBtn.disabled = false;
                        if (j.status === 'done') {
                            showBcProgress(
                                'Готово. Отправлено: ' + j.sent + ', ошибок: ' + j.failed + ', пропущено: ' + j.skipped,
                                'ok'
                            );
                        } else {
                            showBcProgress('Ошибка: ' + (j.error || 'неизвестно'), 'err');
                        }
                        if (tg.HapticFeedback) {
                            tg.HapticFeedback.notificationOccurred(j.status === 'done' ? 'success' : 'error');
                        }
                    }
                });
        }
        tick();
        window.adminBroadcastPoll = setInterval(tick, 900);
    }

    api('/api/admin/broadcast/meta')
        .then(function (r) { return r.json(); })
        .then(function (m) {
            if (!m.ok) {
                subpageContent.innerHTML = '<p class="text-red-600 text-sm p-2">Нет доступа к рассылке</p>';
                return;
            }
            if (m.max_buttons) bcState.maxButtons = m.max_buttons;
            var wrap = document.getElementById('bcSegWrap');
            var html = '';
            m.segments.forEach(function (s) {
                var on = s.id === bcState.segment;
                html +=
                    '<button type="button" class="admin-bc-seg' +
                    (on ? ' admin-bc-seg--on' : '') +
                    '" data-seg="' +
                    esc(s.id) +
                    '">' +
                    esc(s.title) +
                    '<small>' +
                    esc(s.hint) +
                    '</small></button>';
            });
            wrap.innerHTML = html;
            wrap.querySelectorAll('.admin-bc-seg').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    bcState.segment = btn.getAttribute('data-seg') || 'everyone';
                    wrap.querySelectorAll('.admin-bc-seg').forEach(function (b) {
                        b.classList.toggle('admin-bc-seg--on', b.getAttribute('data-seg') === bcState.segment);
                    });
                    refreshBcCount();
                });
            });
            refreshBcCount();
        });

    document.getElementById('bcText').addEventListener('input', syncBcCounter);
    syncBcCounter();

    document.getElementById('bcAddBtn').addEventListener('click', function () {
        var n = subpageContent.querySelectorAll('.admin-bc-url-row').length;
        if (n >= bcState.maxButtons) return;
        var row = document.createElement('div');
        row.className = 'admin-bc-url-row';
        row.innerHTML =
            '<input type="text" class="bc-btn-text" placeholder="Текст на кнопке" autocomplete="off">' +
            '<input type="url" class="bc-btn-url" placeholder="https://…" autocomplete="off">';
        document.getElementById('bcBtnRows').appendChild(row);
    });

    document.getElementById('bcTest').addEventListener('click', function () {
        var text = document.getElementById('bcText').value.trim();
        if (!text) {
            alert('Введите текст');
            return;
        }
        api('/api/admin/broadcast/test', { method: 'POST', body: { text: text, buttons: collectBcButtons() } })
            .then(function (r) { return r.json(); })
            .then(function (x) {
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(x.ok ? 'success' : 'error');
                alert(x.ok ? 'Отправлено вам в чат с ботом' : (x.error || 'Ошибка'));
            });
    });

    document.getElementById('bcRun').addEventListener('click', function () {
        var text = document.getElementById('bcText').value.trim();
        if (!text) {
            alert('Введите текст');
            return;
        }
        if (!confirm('Запустить рассылку? Сообщения уйдут выбранной категории с паузой между отправками.')) return;
        api('/api/admin/broadcast/start', {
            method: 'POST',
            body: { text: text, segment: bcState.segment, buttons: collectBcButtons() }
        })
            .then(function (r) { return r.json(); })
            .then(function (x) {
                if (!x.ok) {
                    alert(x.error || 'Ошибка');
                    if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
                    return;
                }
                showBcProgress('Рассылка запущена…', 'run');
                pollBcJob(x.job_id);
                if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            });
    });
}

function openSubpage(titleText) {
    if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    subpageTitle.textContent = titleText;
    subpage.classList.remove('translate-x-full');
    mainScreen.classList.add('scale-[0.97]', 'opacity-50');
    tg.BackButton.show();
}

function closeSubpage() {
    if (window.adminBroadcastPoll) {
        clearInterval(window.adminBroadcastPoll);
        window.adminBroadcastPoll = null;
    }
    if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    subpage.classList.add('translate-x-full');
    mainScreen.classList.remove('scale-[0.97]', 'opacity-50');
    tg.BackButton.hide();
}

var modeMap = {
    'Пользователи': ['all', 'Все пользователи'],
    'Все пользователи': ['all', 'Все пользователи'],
    'Активные': ['active', 'Активные'],
    'Просроченные': ['expired', 'Просроченные']
};

buttons.forEach(function (button) {
    button.addEventListener('click', function () {
        var title = this.getAttribute('data-target') || '';
        if (modeMap[title]) {
            renderUsersList(modeMap[title][1], modeMap[title][0]);
            return;
        }
        if (title === 'Платежи') { renderPayments(); return; }
        if (title === 'Тарифы') { renderPlans(); return; }
        if (title === 'Настройки') { renderSettings(); return; }
        if (title === 'Поддержка') { renderSupport(); return; }
        if (title === 'Текст рассылки') { renderBroadcast(); return; }
    });
});

closeSubpageBtn.addEventListener('click', closeSubpage);
tg.BackButton.onClick(closeSubpage);

if (tg.initData) {
    closeSubpageBtn.style.display = 'none';
    document.getElementById('subpageTitle').classList.add('ml-2');
}
