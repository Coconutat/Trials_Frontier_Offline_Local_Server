'use strict';
/* ============================================================================
   Trials Frontier 后台 · 前端
   ----------------------------------------------------------------------------
   约定：
     · 文案一律走 t()，字典在 /__admin/i18n.json（中英两节键必须一一对应，
       tools 侧有离线自检）。
     · **玩家可控的字符串（账号名、平台名、路径）只用 textContent 写入**，
       绝不拼 innerHTML —— 这些值直接来自游戏客户端上报，是本项目的信任边界。
     · 危险操作分两档：可撤销的（下发 / 回滚 / 清会话）给就地「撤销」；
       真正不可逆的（删账号）才弹二次确认。
   ========================================================================== */

// ─────────────────────────────────────────────── 弹簧缓动
// apple-design 要的是弹簧（阻尼 + 响应时长），不是固定时长 + 贝塞尔。
// 把一个阻尼谐振子的阶跃响应采样成 CSS linear() 缓动串：
//   x(t) = 1 − e^(−ζω₀t)·[cos(ω_d t) + (ζω₀/ω_d)·sin(ω_d t)],  ω₀ = 2π/response
// ζ=1（关键阻尼）时 ω_d→0，取极限就是 1 − e^(−ω₀t)(1+ω₀t)。
function springEase(damping, response) {
  const w0 = 2 * Math.PI / response;
  const N = 34;
  // 采样到「已经基本静止」为止：ζ=1 约 1.4 个响应，欠阻尼约 1.8 个。
  const settle = response * (damping >= 0.999 ? 1.4 : 1.8);
  const pts = [];
  for (let i = 0; i <= N; i++) {
    const tt = settle * i / N;
    const e = Math.exp(-damping * w0 * tt);
    let v;
    if (damping >= 0.999) {
      v = 1 - e * (1 + w0 * tt);
    } else {
      const wd = w0 * Math.sqrt(1 - damping * damping);
      v = 1 - e * (Math.cos(wd * tt) + (damping * w0 / wd) * Math.sin(wd * tt));
    }
    pts.push(Math.round(v * 1e4) / 1e4);
  }
  pts[0] = 0;
  pts[N] = 1;
  return { duration: settle * 1000, easing: 'linear(' + pts.join(',') + ')' };
}

// 自检：采样必须全是有限值、端点精确、关键阻尼不许冲过头、欠阻尼必须有回弹。
// （这几条任一不成立，动效就会变成跳动或 NaN，肉眼未必立刻看得出来。）
(function springSelfCheck() {
  const cases = [[1.0, 0.34], [1.0, 0.3], [0.8, 0.42]];
  for (const [z, r] of cases) {
    const s = springEase(z, r);
    const vals = s.easing.slice('linear('.length, -1).split(',').map(Number);
    console.assert(vals.every(Number.isFinite), 'spring 出现非有限值', z, r);
    console.assert(vals[0] === 0 && vals[vals.length - 1] === 1, 'spring 端点不对', z, r);
    console.assert(s.duration > 0 && s.duration < 2000, 'spring 时长离谱', z, r, s.duration);
    if (z >= 0.999) {
      console.assert(Math.max.apply(null, vals) <= 1.0001, '关键阻尼不许回弹', z, r);
    } else {
      console.assert(Math.max.apply(null, vals) > 1, '欠阻尼应当有回弹', z, r);
    }
  }
})();

const HAS_LINEAR = !!(window.CSS && CSS.supports &&
                      CSS.supports('transition-timing-function', 'linear(0,1)'));
const SPRING = HAS_LINEAR ? springEase(1.0, 0.34) : { duration: 340, easing: 'cubic-bezier(.32,.72,0,1)' };

function installSprings() {
  if (!HAS_LINEAR) return;                 // 老浏览器留在 CSS 里的 cubic-bezier 退路上
  const b = springEase(0.8, 0.34);
  const root = document.documentElement.style;
  root.setProperty('--spring', SPRING.easing);
  root.setProperty('--spring-bouncy', b.easing);
  root.setProperty('--dur', Math.round(SPRING.duration) + 'ms');
}

// ─────────────────────────────────────────────── 小工具

const $ = (sel, root) => (root || document).querySelector(sel);

function el(tag, props, ...kids) {
  const n = document.createElement(tag);
  if (props) {
    for (const k of Object.keys(props)) {
      const v = props[k];
      if (v == null || v === false) continue;
      if (k === 'text') n.textContent = String(v);
      else if (k === 'class') n.className = v;
      else if (k === 'style') n.style.cssText = v;
      else if (k === 'dataset') Object.assign(n.dataset, v);
      else if (k.slice(0, 2) === 'on' && typeof v === 'function') {
        n.addEventListener(k.slice(2).toLowerCase(), v);
      } else n.setAttribute(k, v === true ? '' : String(v));
    }
  }
  for (const kid of kids) {
    if (kid == null || kid === false) continue;
    const list = Array.isArray(kid) ? kid : [kid];
    for (const one of list) {
      if (one == null || one === false) continue;
      n.append(one instanceof Node ? one : document.createTextNode(String(one)));
    }
  }
  return n;
}

function fmtTime(sec) {
  const n = Number(sec);
  if (!n) return t('app.never');
  const d = new Date(n * 1000);
  if (isNaN(d.getTime())) return t('app.unknown');
  return d.toLocaleString(locale(), { year: 'numeric', month: '2-digit', day: '2-digit',
                                      hour: '2-digit', minute: '2-digit' });
}
function fmtNum(n) {
  const v = Number(n);
  return Number.isFinite(v) ? v.toLocaleString(locale()) : '—';
}
function dash() { return el('span', { class: 'muted', text: '—' }); }

async function copyText(s) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(s);
      return true;
    }
  } catch (e) { /* 继续走退路 */ }
  // 明文 HTTP 是**非安全上下文**，没有 clipboard API —— 而本项目恰恰只能走明文
  // （客户端 manifest 不接受 HTTPS），所以这条退路是常态而不是兜底。
  const ta = el('textarea', { style: 'position:fixed;top:-1000px;left:-1000px', text: s });
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function idCell(id) {
  const s = id == null ? '' : String(id);
  if (!s) return dash();
  const short = s.length > 16 ? s.slice(0, 8) + '…' + s.slice(-4) : s;
  return el('span', {
    class: 'mono', text: short, title: s, style: 'cursor:copy',
    onclick: async () => {
      const ok = await copyText(s);
      toast(ok ? t('app.copied') : s, { kind: ok ? 'good' : null, timeout: 1800 });
    },
  });
}

function urlCell(url) {
  // 一条要发给别人的地址（玩家注册入口 / 手机上的后台）。
  return el('span', { style: 'display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap' },
    el('span', { class: 'mono', text: url, style: 'user-select:all' }),
    el('button', {
      class: 'btn tiny', text: t('app.copy'),
      onclick: async () => {
        const ok = await copyText(url);
        toast(ok ? t('app.copied') : url, { kind: ok ? 'good' : null, timeout: 1800 });
      },
    }));
}

function table(cols, rows) {
  const thead = el('thead', null, el('tr', null,
    cols.map(c => el('th', { class: c.cls || null, text: c.label }))));
  const tbody = el('tbody', null, rows.map(r => el('tr', null, cols.map(c => {
    const td = el('td', { class: c.cls || null });
    const v = c.render ? c.render(r) : r[c.k];
    if (v instanceof Node) td.append(v);
    else if (v != null) td.textContent = String(v);
    return td;
  }))));
  return el('div', { class: 'scroll' }, el('table', { class: 'list' }, thead, tbody));
}

function reveal(nodes) {
  nodes.forEach((n, i) => {
    if (!(n instanceof HTMLElement) || typeof n.animate !== 'function') return;
    try {
      n.animate([{ opacity: 0, transform: 'translate3d(0,9px,0)' },
                 { opacity: 1, transform: 'none' }],
                { duration: SPRING.duration, delay: Math.min(i, 6) * 32,
                  easing: SPRING.easing, fill: 'both' });
    } catch (e) { /* 动画失败不该影响内容 */ }
  });
}

// ─────────────────────────────────────────────── i18n

let DICT = { cn: {}, en: {} };
let LANG = 'cn';

function locale() { return LANG === 'cn' ? 'zh-CN' : 'en-US'; }

function t(key, vars) {
  const s = (DICT[LANG] && DICT[LANG][key]) || DICT.cn[key] || key;
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

function applyI18n(root) {
  for (const n of root.querySelectorAll('[data-i18n]')) n.textContent = t(n.dataset.i18n);
}

function setLang(lang) {
  if (lang !== 'cn' && lang !== 'en') return;
  LANG = lang;
  try { localStorage.setItem('tf_lang', lang); } catch (e) { /* 隐私模式 */ }
  applyLang();
  document.title = t('app.name');
  if (!$('#shell').hidden) show(state.screen);
}

function applyLang() {
  document.documentElement.lang = locale();
  document.documentElement.dataset.lang = LANG;
  applyI18n(document);
  for (const b of document.querySelectorAll('#langSeg button')) {
    b.setAttribute('aria-pressed', String(b.dataset.lang === LANG));
  }
  const dot = $('#statusDot');
  if (dot.className.indexOf('on') >= 0) dot.title = t('status.online');
  else if (dot.className.indexOf('off') >= 0) dot.title = t('status.offline');
}

function pickLang() {
  let saved = null;
  try { saved = localStorage.getItem('tf_lang'); } catch (e) { /* 隐私模式 */ }
  if (saved === 'cn' || saved === 'en') return saved;
  return String(navigator.language || '').toLowerCase().indexOf('zh') === 0 ? 'cn' : 'en';
}

// ─────────────────────────────────────────────── HTTP

async function api(path, opts) {
  let res;
  try {
    res = await fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}));
  } catch (e) {
    throw Object.assign(new Error(t('msg.netError')), { net: true });
  }
  const txt = await res.text();
  let body = null;
  if (txt) { try { body = JSON.parse(txt); } catch (e) { body = { raw: txt }; } }
  if (res.status === 401) {
    throw Object.assign(new Error((body && body.message) || 'unauthorized'), { auth: true });
  }
  if (!res.ok) {
    throw Object.assign(new Error((body && (body.message || body.error)) || ('HTTP ' + res.status)),
                        { status: res.status, body });
  }
  return body;
}

function post(path, obj) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify(obj || {}) });
}

async function guarded(fn) {
  try {
    await fn();
  } catch (e) {
    if (e.auth) { showLogin(t('msg.authRequired')); return; }
    toast(e.message || t('app.error'), { kind: 'bad' });
    const pane = $('#pane');
    if (pane) pane.replaceChildren(el('section', { class: 'card' },
      el('div', { class: 'card-body' },
        el('h2', { text: t('app.error') }),
        el('p', { class: 'lead', text: e.message || '' }),
        el('button', { class: 'btn', text: t('app.retry'), onclick: () => show(state.screen) }))));
  }
}

// ─────────────────────────────────────────────── 提示条 / 确认框

function toast(msg, opts) {
  opts = opts || {};
  const node = el('div', { class: 'toast' + (opts.kind ? ' ' + opts.kind : '') },
    el('div', { class: 'grow', text: msg }),
    opts.action ? el('button', {
      class: 'btn tiny', text: opts.action.label,
      onclick: () => { close(); opts.action.run(); },
    }) : null,
    el('button', { class: 'btn tiny bare', text: t('app.close'), onclick: () => close() }));
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    node.classList.add('out');
    setTimeout(() => node.remove(), 240);
  }
  $('#toasts').append(node);
  const ms = opts.timeout == null ? (opts.action ? 15000 : 4200) : opts.timeout;
  if (ms) setTimeout(close, ms);
  return close;
}

function confirmDialog(o) {
  o = o || {};
  return new Promise(resolve => {
    const m = $('#modal'), ok = $('#modalOk'), cancel = $('#modalCancel'), body = $('#modalBody');
    $('#modalTitle').textContent = o.title || t('app.confirm');
    body.replaceChildren(o.body ? el('p', { text: o.body }) : document.createTextNode(''));
    ok.textContent = o.okLabel || t('app.confirm');
    m.hidden = false;
    ok.focus();
    function done(v) {
      m.hidden = true;
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      m.removeEventListener('click', onBg);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    }
    function onOk() { done(true); }
    function onCancel() { done(false); }
    function onBg(e) { if (e.target === m) done(false); }
    function onKey(e) { if (e.key === 'Escape') done(false); }
    ok.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    m.addEventListener('click', onBg);
    document.addEventListener('keydown', onKey);
  });
}

// ─────────────────────────────────────────────── 状态 / 路由

const state = { screen: 'accounts', saves: [], detail: null, grantProfile: '',
                itemSel: {}, itemOpen: {}, grantMode: 'add',
                pvpAmounts: {}, pvpMode: 'add' };

const SCREENS = {
  accounts: { titleKey: 'nav.accounts', load: screenAccounts },
  saves: { titleKey: 'nav.saves', load: screenSaves },
  grant: { titleKey: 'nav.grant', load: screenGrant },
};

function route() {
  const raw = location.hash.replace(/^#\/?/, '').split('?')[0];
  show(raw in SCREENS ? raw : 'accounts');
}

async function show(name) {
  state.screen = name;
  $('#pageTitle').textContent = t(SCREENS[name].titleKey);
  for (const a of document.querySelectorAll('.nav a')) {
    if (a.dataset.nav === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  movePill();
  const pane = $('#pane');
  pane.replaceChildren(el('div', { class: 'loading', text: t('app.loading') }));
  await guarded(async () => {
    const nodes = await SCREENS[name].load();
    pane.replaceChildren.apply(pane, nodes);
    reveal(Array.prototype.slice.call(pane.children));
  });
}

function movePill() {
  const link = document.querySelector('.nav a[data-nav="' + state.screen + '"]');
  const pill = $('#navPill');
  if (!link || !pill || getComputedStyle(pill).display === 'none') return;
  const nb = $('#nav').getBoundingClientRect(), lb = link.getBoundingClientRect();
  if (!lb.height) return;
  pill.style.opacity = '1';
  pill.style.height = lb.height + 'px';
  pill.style.transform = 'translateY(' + (lb.top - nb.top) + 'px)';
}

// ─────────────────────────────────────────────── 屏 · 账号

function items2Map(content) {
  const out = {};
  const pairs = content && content.items2;
  if (!Array.isArray(pairs)) return out;
  for (let i = 0; i + 1 < pairs.length; i += 2) {
    const k = Number(pairs[i]), v = Number(pairs[i + 1]);
    if (Number.isFinite(k)) out[k] = Number.isFinite(v) ? v : 0;
  }
  return out;
}

function richCell(n) {
  const v = Number(n) || 0;
  return el('span', { class: 'nowrap' },
    el('span', { class: 'num', text: fmtNum(v) }),
    v < 10 ? el('span', { class: 'badge bad', style: 'margin-left:6px', text: t('saves.lowRich') }) : null);
}

async function screenAccounts() {
  const [accs, devs, ses, info] = await Promise.all([
    api('/__accounts'), api('/__devices'), api('/__sessions'), api('/__api/admin/info')]);
  const perUser = {};
  for (const s of Object.values(ses.sessions || {})) {
    const u = s && s.user;
    if (u) perUser[u] = (perUser[u] || 0) + 1;
  }

  async function clearSessions(username) {
    const r = await post('/__api/admin/sessions/clear', username ? { username } : {});
    toast(t('accounts.sessions.cleared', { n: r.removed }), { kind: 'good' });
    show('accounts');
  }

  const sessCard = el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('accounts.sessions.title') }),
      el('span', { class: 'badge', text: t('app.count', { n: ses.count }) }),
      el('button', {
        class: 'btn tiny danger', text: t('accounts.sessions.clearAll'),
        onclick: async () => {
          if (!await confirmDialog({ title: t('accounts.sessions.confirmTitle'),
                                     body: t('accounts.sessions.confirmBody', { n: ses.count }),
                                     okLabel: t('accounts.sessions.clearAll') })) return;
          await clearSessions(null);
        },
      })),
    el('div', { class: 'card-body' },
      el('p', { class: 'lead', text: t('accounts.sessions.lead') })));

  const cols = [
    { label: t('accounts.col.user'), render: a => el('span', null,
        el('b', { text: a.username }),
        a.banned ? el('span', { class: 'badge bad', style: 'margin-left:6px', text: t('accounts.banned') }) : null) },
    { label: t('accounts.col.profile'), render: a => idCell(a.profileId) },
    { label: t('accounts.col.platform'), render: a => a.nameOnPlatform || dash() },
    { label: t('accounts.col.created'), cls: 'nowrap', render: a => fmtTime(a.created) },
    { label: t('accounts.col.lastLogin'), cls: 'nowrap', render: a => fmtTime(a.last_login) },
    { label: t('accounts.col.logins'), cls: 'r num', render: a => fmtNum(a.logins) },
    { label: t('accounts.col.remember'), render: a => a.rememberTicket
        ? el('span', { class: 'badge acc', text: fmtNum(a.remember_uses) })
        : dash() },
    { label: t('accounts.sessions.title'), cls: 'r num',
      render: a => fmtNum(perUser[a.username] || 0) },
    { label: t('accounts.col.actions'), cls: 'act', render: a => el('span',
        { style: 'display:inline-flex;gap:6px' },
        el('button', { class: 'btn tiny', text: t('accounts.sessions.clearOne'),
                       onclick: () => guarded(() => clearSessions(a.username)) }),
        el('button', { class: 'btn tiny danger', text: t('accounts.delete'),
                       onclick: () => guarded(async () => {
                         if (!await confirmDialog({
                           title: t('accounts.deleteConfirmTitle', { name: a.username }),
                           body: t('accounts.deleteConfirmBody'),
                           okLabel: t('accounts.delete') })) return;
                         await post('/__api/delete', { username: a.username });
                         toast(t('accounts.deleteDone', { name: a.username }), { kind: 'good' });
                         show('accounts');
                       }) })) },
  ];

  const accCard = el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('accounts.title') }),
      el('span', { class: 'badge', text: t('app.count', { n: accs.count }) })),
    table(cols, accs.accounts || []));

  const devCols = [
    { label: t('accounts.devices.col.device'), render: d => el('span', { class: 'mono', text: d.deviceId }) },
    { label: t('accounts.devices.col.profile'), render: d => idCell(d.profileId) },
    { label: t('accounts.devices.col.platform'), render: d => d.nameOnPlatform || dash() },
    { label: t('accounts.devices.col.lastSeen'), cls: 'nowrap', render: d => fmtTime(d.last_seen) },
    { label: t('accounts.devices.col.sessions'), cls: 'r num', render: d => fmtNum(d.sessions) },
  ];
  const devCard = el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('accounts.devices.title') }),
      el('span', { class: 'badge', text: t('app.count', { n: devs.count }) })),
    el('div', { class: 'card-body' },
      el('p', { class: 'lead', text: t('accounts.devices.lead') })),
    table(devCols, devs.devices || []));

  // 玩家注册入口 —— 以前后台完全看不到它，要发给别人时只能自己拼地址。
  const regRow = (label, url) => el('div',
    { style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0' },
    el('span', { class: 'muted', text: label, style: 'min-width:8em' }), urlCell(url));
  const regCard = el('section', { class: 'card pad' },
    el('h2', { text: t('accounts.register.title') }),
    el('p', { class: 'lead', text: t('accounts.register.lead') }),
    regRow(t('accounts.register.player'), info.register_url),
    regRow(t('accounts.register.admin'), info.admin_url));

  const pwInput = el('input', { type: 'password', autocomplete: 'new-password',
                                placeholder: t('accounts.admin.placeholder'),
                                style: 'max-width:260px' });
  const pwBtn = el('button', {
    class: 'btn primary', text: t('accounts.admin.set'),
    onclick: () => guarded(async () => {
      if (pwInput.value.length < 8) { toast(t('accounts.admin.tooShort'), { kind: 'bad' }); return; }
      pwBtn.disabled = true;
      try {
        await post('/__api/admin/password', { password: pwInput.value });
        pwInput.value = '';
        toast(t('accounts.admin.done'), { kind: 'good' });
      } finally { pwBtn.disabled = false; }
    }),
  });
  const pwCard = el('section', { class: 'card pad' },
    el('h2', { text: t('accounts.admin.title') }),
    el('p', { class: 'lead', text: t('accounts.admin.lead') }),
    el('div', { style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap' }, pwInput, pwBtn));

  return [regCard, sessCard, accCard, devCard, pwCard];
}

// ─────────────────────────────────────────────── 屏 · 存档

function snapshotLabel(ts) {
  const s = String(ts);
  if (s.indexOf('pre_grant_') === 0) return t('saves.snapshotGrant');
  if (s.indexOf('pre_restore_') === 0) return t('saves.snapshotRestore');
  const n = Number(s);
  return Number.isFinite(n) && n > 1e9 ? fmtTime(n) : s;
}

function kindBadge(s) {
  if (s.kind === 'anon') return el('span', { class: 'badge', text: t('saves.kind.anon') });
  if (s.kind === 'account') return el('span', { class: 'badge acc', text: t('saves.kind.account') });
  return el('span', { class: 'badge warn', text: t('saves.kind.none') });
}

async function doRollback(profileId, ts, curRich, newRich) {
  if (!await confirmDialog({
    title: t('saves.rollbackConfirmTitle', { ts: snapshotLabel(ts) }),
    body: t('saves.rollbackConfirmBody', { rich: curRich, new: newRich }),
    okLabel: t('saves.rollback'),
  })) return;
  const r = await post('/__api/admin/rollback', { profile: profileId, ts });
  toast(t('saves.rollbackDone', { ts: snapshotLabel(ts) }), {
    kind: 'good',
    action: r.snapshot ? {
      label: t('saves.undoRollback'),
      run: () => guarded(async () => {
        await post('/__api/admin/revert', { profile: profileId, snapshot: r.snapshot });
        toast(t('saves.undoRollbackDone', { ts: snapshotLabel(r.snapshot) }), { kind: 'good' });
        show('saves');
      }),
    } : null,
  });
  show('saves');
}

function snapshotList(profileId, curRich, hist) {
  if (!hist.length) return el('p', { class: 'hint', text: t('saves.noHistory') });
  return el('div', { class: 'snaps' }, hist.map(h => el('div', { class: 'row' },
    el('div', { class: 'grow' },
      el('div', null, el('b', { text: snapshotLabel(h.ts) })),
      el('div', { class: 'nm muted', text: h.ts + '  ·  ' + (h.saved_at_iso || '') })),
    el('span', { class: 'nowrap muted' },
      t('saves.col.items') + ' ' + fmtNum(h.items) + ' · ' +
      t('saves.col.tracks') + ' ' + fmtNum(h.tracks)),
    richCell(h.richness),
    el('button', { class: 'btn tiny', text: t('saves.rollback'),
                   onclick: () => guarded(() => doRollback(profileId, h.ts, curRich, h.richness)) }))));
}

function saveDetailCard(d) {
  const m = items2Map(d.doc && d.doc.content);
  const kv = el('div', { class: 'kv' },
    el('div', null, el('div', { class: 'k', text: t('saves.coins') }),
        el('div', { class: 'v', text: fmtNum(m[1]) })),
    el('div', null, el('div', { class: 'k', text: t('saves.gems') }),
        el('div', { class: 'v', text: fmtNum(m[2]) })),
    el('div', null, el('div', { class: 'k', text: t('saves.item135') }),
        el('div', { class: 'v', text: m[135] == null ? '—' : fmtNum(m[135]) })),
    el('div', null, el('div', { class: 'k', text: t('saves.version') }),
        el('div', { class: 'v', text: fmtNum((d.doc && d.doc.version) || 0) })),
    el('div', null, el('div', { class: 'k', text: t('saves.col.richness') }),
        el('div', { class: 'v', text: fmtNum(d.row ? d.row.richness : 0) })));
  return el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('saves.detailTitle') }),
      el('span', { class: 'mono muted', text: d.profileId }),
      el('button', { class: 'btn tiny', text: t('app.close'),
                     onclick: () => { state.detail = null; show('saves'); } })),
    el('div', { class: 'card-body' },
      kv,
      el('p', { class: 'hint', text: t('saves.versionHint') }),
      el('p', { class: 'hint', text: t('saves.richnessHint') })),
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('saves.historyTitle') }),
      el('span', { class: 'badge', text: t('app.count', { n: d.history.length }) })),
    el('div', { class: 'card-body' }, el('p', { class: 'lead', text: t('saves.historyLead') })),
    snapshotList(d.profileId, d.row ? d.row.richness : 0, d.history));
}

async function screenSaves() {
  const data = await api('/__saves');
  state.saves = data.saves || [];
  const nodes = [el('p', { class: 'lead', text: t('saves.lead') })];

  if (state.detail) nodes.push(saveDetailCard(state.detail));

  const cols = [
    { label: t('saves.col.profile'), render: s => idCell(s.profileId) },
    { label: t('saves.col.account'), render: s => s.account || el('span', { class: 'muted', text: t('saves.anonAccount') }) },
    { label: t('saves.col.kind'), render: s => kindBadge(s) },
    { label: t('saves.col.items'), cls: 'r num', render: s => fmtNum(s.items) },
    { label: t('saves.col.tracks'), cls: 'r num', render: s => fmtNum(s.tracks) },
    { label: t('saves.col.richness'), cls: 'r', render: s => richCell(s.richness) },
    { label: t('saves.col.savedAt'), cls: 'nowrap', render: s => fmtTime(s.saved_at) },
    { label: t('app.actions'), cls: 'act', render: s => el('button', {
        class: 'btn tiny', text: t('saves.inspect'),
        onclick: () => guarded(async () => {
          const [doc, hist] = await Promise.all([
            api('/__save?profile=' + encodeURIComponent(s.profileId)),
            api('/__history?profile=' + encodeURIComponent(s.profileId))]);
          state.detail = { profileId: s.profileId, row: s, doc: doc,
                           history: hist.history || [] };
          show('saves');
        }) }) },
  ];

  nodes.push(el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('saves.title') }),
      el('span', { class: 'badge', text: t('app.count', { n: state.saves.length }) })),
    state.saves.length ? table(cols, state.saves)
                       : el('div', { class: 'empty', text: t('app.empty') })));
  return nodes;
}

// ─────────────────────────────────────────────── 屏 · 下发物品

// 竞技场余额：改服务端 pvp_state.json，客户端下次读 PVP 响应就看到，无需玩家操作。
const PVP_ITEMS = ['golden_ticket', 'chips'];

const PVP_LABEL = { golden_ticket: 'grant.pvpGolden', chips: 'grant.pvpChips' };

function modeSeg(cur, onpick) {
  return el('div', { class: 'seg' }, ['add', 'set'].map(mo => el('button', {
    type: 'button', text: mo === 'add' ? t('grant.modeAdd') : t('grant.modeSet'),
    'aria-pressed': String(cur === mo),
    onclick: () => onpick(mo),
  })));
}

// 官方物品目录：server/admin/items.json，由 tools/build_item_catalog.py 从游戏自带的
// 物品表里抽出来，中文名直接取自游戏自己的本地化表（LOCF 1523），不是我们翻的。
let CATALOG = null;

async function catalog() {
  if (!CATALOG) CATALOG = await api('/__admin/items.json');
  return CATALOG;
}

function itemName(it) { return (LANG === 'cn' ? it.cn : it.en) || it.en || ('#' + it.id); }
function catLabel(c) { return (LANG === 'cn' ? c.cn : c.en) || c.key; }

// 真机存档里服装部件是 0/1 标志（225=1），不是计数器 ⇒ 只能「解锁」，不给数量。
// ★ 蓝图**不是**标志：真机档里 379=7 片、404=3 片、429=1004，是碎片计数器 ⇒ 必须有数量框。
const FLAG_CATS = { outfit: 1 };

// 折叠清单：分类 → 打勾 → 填数量。勾选/展开/搜索只改 DOM，不重渲染 —— 四百条物品
// 重渲染一次既会闪，也会把正在输入的数量框焦点弄丢。
function itemPicker(cat, cur) {
  const groups = cat.categories
    .map(c => ({ meta: c, items: Object.keys(cat.items).map(k => cat.items[k])
                 .filter(it => it.cat === c.key).sort((a, b) => a.id - b.id) }))
    .filter(g => g.items.length);

  // 服装按「套」列，不按件：240 件里 99 件任何配置里都没有（隐藏套装），而且一件件点
  // 没有意义 —— 套装效果是集齐才生效的。套装表来自 customization.txt（见 build_item_catalog.py）。
  const sets = Object.keys(cat.outfits || {}).map(k => cat.outfits[k])
    .sort((a, b) => a.id - b.id);
  const setOf = id => (cat.items[id] || {}).set;

  // 涂装：108 款，编号**不是** items2 的键 —— 存档里每辆车一个 24 位拥有位掩码
  // （键 = 664 + 车号，位 = 该车第几款涂装，见 build_item_catalog.py 开头 ★ 涂装），
  // 所以按「车」分组列：一辆车一组，勾一款 = 给那一位置 1。
  const paints = Object.keys(cat.paints || {}).map(k => cat.paints[k]);
  const bikeGroups = [];
  for (const p of paints) {
    let g = bikeGroups.filter(x => x.bike === p.bike)[0];
    if (!g) bikeGroups.push(g = { bike: p.bike, name: p.bike_en, key: 664 + p.bike, rows: [] });
    g.rows.push(p);
  }
  for (const g of bikeGroups) g.rows.sort((a, b) => a.slot - b.slot);
  bikeGroups.sort((a, b) => a.bike - b.bike);
  const paintVal = p => Number(cur[p.key]) || 0;
  const isOwned = p => (paintVal(p) & p.bit) !== 0;
  if (paints.length) {
    groups.push({ meta: { key: 'paint', en: 'Bike paints', cn: '车漆涂装' }, items: paints });
  }

  const root = el('div', { class: 'acclist' });
  const total = el('span', { class: 'hint', text: t('grant.list.selected', { n: 0 }) });
  const empty = el('p', { class: 'hint', hidden: true, text: t('grant.list.empty') });
  const accs = {};
  const bikeBadges = [];

  // 勾一件服装 = 勾这一套的三件（头盔/上衣/裤装），所以徽标按「套」数，不按件数；
  // 涂装按「款」数（每款一个键 'p<id>'，跟物品 id 不会撞 —— 存档 id 都是数字）。
  const selKeys = () => Object.keys(state.itemSel);
  const selectedIn = key => {
    if (key === 'outfit') return new Set(selKeys().map(k => setOf(Number(k))).filter(Boolean)).size;
    if (key === 'paint') return selKeys().filter(k => k.charAt(0) === 'p').length;
    return selKeys().filter(k => (cat.items[Number(k)] || {}).cat === key).length;
  };
  const refresh = () => {
    for (const k in accs) {
      const n = selectedIn(k);
      accs[k].badge.textContent = String(n);
      accs[k].badge.hidden = !n;
    }
    for (const b of bikeBadges) {
      const n = bikeGroups[b.i].rows.filter(p => ('p' + p.id) in state.itemSel).length;
      b.badge.textContent = String(n);
      b.badge.hidden = !n;
    }
    total.textContent = t('grant.list.selected', { n: Object.keys(state.itemSel).length });
  };

  const head = (key, label, count, open) => {
    const b = el('span', { class: 'badge sel', hidden: true });
    const btn = el('button', { type: 'button', class: 'acchead', 'aria-expanded': String(open) },
      el('span', { class: 'chev' }),
      el('span', { class: 'grow', text: label }),
      el('span', { class: 'hint mono', text: String(count) }),
      b);
    return { btn, badge: b };
  };

  // 一套服装一行：勾上就把三件一起写成 1（存档里这三件是 0/1 标志，不能给数量）。
  const setRow = o => {
    const name = (LANG === 'cn' ? o.cn : o.en) || o.en || o.key;
    const own = o.parts.filter(p => Number(cur[p]) > 0).length;
    const box = el('input', { type: 'checkbox', class: 'tick' });
    box.checked = o.parts.every(p => p in state.itemSel);
    box.onchange = () => {
      for (const p of o.parts) {
        if (box.checked) state.itemSel[p] = 1; else delete state.itemSel[p];
      }
      refresh();
    };
    const note = el('span', { class: 'setnote' });
    if (o.hidden) note.append(el('span', { class: 'pill', text: t('grant.list.hidden') }));
    // 官方中文名有时跟内部代号差很多（The High Roller 官方中文叫「摩天轮」），两个都给。
    if (o.comment && o.comment !== name) note.append(el('span', { class: 'hint', text: o.comment }));
    if (o.bonus) note.append(el('span', { class: 'bonust',
      text: (LANG === 'cn' ? o.bonus_cn : o.bonus_en) || o.bonus }));
    note.append(el('span', { class: 'hint', text: t('grant.list.setOwned', { n: own }) }));
    const q = [name, o.parts.join(' '), o.comment, o.bonus_en, o.bonus_cn].join(' ').toLowerCase();
    return el('div', { class: 'irow setrow', dataset: { q } },
      el('label', { class: 'ibox' }, box),
      el('span', { class: 'iname' }, el('span', { class: 'setname', text: name }), note),
      el('span', { class: 'hint mono', text: '#' + o.parts.join(' ') }),
      el('span', { class: 'hint', text: t('grant.list.unlock') }));
  };

  // 一款涂装一行。存档里没有「涂装 id -> 有无」这种东西：每辆车只有 items2[664+车号]
  // 一条值，低 24 位是「这辆车每一款涂装拥有与否」的位掩码，高 8 位是当前装备的那一款。
  // 所以勾一款 = 把那一位置 1（客户端自己会按位读；服务器写的也是这条）。
  const paintRow = p => {
    const name = (LANG === 'cn' ? p.cn : p.en) || p.en || p.name || ('#' + p.id);
    const selKey = 'p' + p.id;
    const owned = isOwned(p);
    const box = el('input', { type: 'checkbox', class: 'tick' });
    box.checked = selKey in state.itemSel;
    box.onchange = () => {
      if (box.checked) state.itemSel[selKey] = 1; else delete state.itemSel[selKey];
      refresh();
    };
    const note = el('span', { class: 'setnote' });
    if (!p.verified) note.append(el('span', { class: 'hint', text: t('grant.list.noloc') }));
    // SkinData 里的内部名（Snakebite / Boogeyman …）跟商店名常常不是一回事，两个都给。
    if (p.comment && p.comment !== name) note.append(el('span', { class: 'hint', text: p.comment }));
    if (p.diamond) note.append(el('span', { class: 'hint',
      text: t('grant.list.price', { n: fmtNum(p.diamond) }) }));
    const q = [name, p.id, p.name, p.bike_en, p.comment].join(' ').toLowerCase();
    return el('div', { class: 'irow setrow', dataset: { q } },
      el('label', { class: 'ibox' }, box),
      el('span', { class: 'iname' }, el('span', { class: 'setname', text: name }), note),
      el('span', { class: 'hint mono', text: '#' + p.id + '　' + t('grant.list.slot', { n: p.slot }) }),
      owned ? el('span', { class: 'pill', text: t('grant.list.owned') })
            : el('span', { class: 'hint', text: t('grant.list.unlock') }));
  };

  // 蓝图是**碎片计数器**：一辆车一个编号（`(车号+72)*5+4`），每辆车要的片数不同
  // （upgrades.txt 的 `BP`：Tango 4、Bronco 20、KTM 450 RALLY 30、Stallion 50…），
  // 所以按车列一行、带数量框。19 辆车里只有 12 辆有碎片编号，其余 7 辆只能金币买。
  const bpItems = Object.keys(cat.items).map(k => cat.items[k])
    .filter(it => it.cat === 'blueprint').sort((a, b) => a.bike - b.bike);

  const bpRow = it => {
    const name = itemName(it);
    const own = Number(cur[it.id]) || 0;
    const need = Number(it.need) || 0;
    const box = el('input', { type: 'checkbox', class: 'tick' });
    const qty = el('input', { type: 'number', min: '0', step: '1', class: 'qty',
                              placeholder: '1', disabled: true, 'aria-label': t('grant.amount') });
    box.checked = it.id in state.itemSel;
    if (box.checked) { qty.value = String(state.itemSel[it.id]); qty.disabled = false; }
    box.onchange = () => {
      qty.disabled = !box.checked;
      if (box.checked) {
        // 默认填「还差几片」——勾一下就能凑齐，不用自己算。
        if (!qty.value) qty.value = String(Math.max(need - own, 1));
        state.itemSel[it.id] = Number(qty.value) || 0;
      } else delete state.itemSel[it.id];
      refresh();
    };
    qty.oninput = () => { if (box.checked) state.itemSel[it.id] = Number(qty.value) || 0; };
    const note = el('span', { class: 'setnote' });
    if (it.bike_en) note.append(el('span', { class: 'hint', text: it.bike_en }));
    if (need) note.append(el('span', { class: 'hint', text: t('grant.list.bpNeed', { n: need }) }));
    // 374/379/439 的官方名被 RedLynx 复制粘贴成了 Tango 的 Redlynx 涂装名，旧名留在这里。
    if (it.alias) note.append(el('span', { class: 'hint', text: it.alias }));
    if (!it.verified) note.append(el('span', { class: 'hint', text: t('grant.list.noloc') }));
    note.append(el('span', { class: 'hint', text: t('grant.list.bpOwned', { n: own, m: need }) }));
    const q = [name, it.id, it.bike_en, it.need, it.alias].join(' ').toLowerCase();
    return el('div', { class: 'irow setrow', dataset: { q } },
      el('label', { class: 'ibox' }, box),
      el('span', { class: 'iname' }, el('span', { class: 'setname', text: name }), note),
      el('span', { class: 'hint mono', text: '#' + it.id }),
      qty);
  };

  // 一辆车一组（嵌套折叠）：108 款摊平了没法看，而位掩码本来就是按车分的。
  const bikeGroup = (g, i) => {
    const own = g.rows.filter(isOwned).length;
    const inner = el('div', { class: 'accbody' });
    for (const p of g.rows) inner.append(paintRow(p));
    const key = 'paint:' + g.bike;
    const h = head(key, g.name || ('#' + g.bike),
                   t('grant.list.skinOwned', { n: own, m: g.rows.length }), !!state.itemOpen[key]);
    const acc = el('div', { class: 'acc acc-sub' + (state.itemOpen[key] ? ' open' : ''), dataset: { k: key } },
                   h.btn, inner);
    h.btn.addEventListener('click', () => {
      const on = acc.classList.toggle('open');
      state.itemOpen[key] = on;
      h.btn.setAttribute('aria-expanded', String(on));
    });
    bikeBadges.push({ i, badge: h.badge });
    return acc;
  };

  for (const g of groups) {
    const flag = !!FLAG_CATS[g.meta.key];
    // 「未验证」是按物品带的（存档里真的没确认过怎么写），不是按分类配的：
    // 一个类里只要有一条没验证过就提醒，别拿 meta.verified 判断（categories 里没这个字段，
    // 用它会变成「每个类都挂警告」）。
    const unverified = g.items.some(it => !it.verified);
    const body = el('div', { class: 'accbody' });
    if (g.meta.key === 'outfit' && sets.length) {
      body.append(el('p', { class: 'hint p-warn', text: t('grant.list.derived') }));
      for (const o of sets) body.append(setRow(o));
      const h = head(g.meta.key, catLabel(g.meta), sets.length, !!state.itemOpen[g.meta.key]);
      const acc = el('div', { class: 'acc' + (state.itemOpen[g.meta.key] ? ' open' : '') }, h.btn, body);
      h.btn.addEventListener('click', () => {
        const on = acc.classList.toggle('open');
        state.itemOpen[g.meta.key] = on;
        h.btn.setAttribute('aria-expanded', String(on));
      });
      accs[g.meta.key] = { acc, badge: h.badge, body };
      root.append(acc);
      continue;
    }
    if (g.meta.key === 'paint' && paints.length) {
      body.append(el('p', { class: 'hint', text: t('grant.list.paintHint') }));
      bikeGroups.forEach((bg, i) => body.append(bikeGroup(bg, i)));
      const h = head(g.meta.key, t('grant.list.paintCard'), paints.length,
                     !!state.itemOpen[g.meta.key]);
      const acc = el('div', { class: 'acc' + (state.itemOpen[g.meta.key] ? ' open' : '') }, h.btn, body);
      h.btn.addEventListener('click', () => {
        const on = acc.classList.toggle('open');
        state.itemOpen[g.meta.key] = on;
        h.btn.setAttribute('aria-expanded', String(on));
      });
      accs[g.meta.key] = { acc, badge: h.badge, body };
      root.append(acc);
      continue;
    }
    if (g.meta.key === 'blueprint' && bpItems.length) {
      body.append(el('p', { class: 'hint', text: t('grant.list.bpHint',
        { names: ((cat.source || {}).no_blueprint_bikes || []).join(' / ') }) }));
      for (const it of bpItems) body.append(bpRow(it));
      const h = head(g.meta.key, catLabel(g.meta), bpItems.length, !!state.itemOpen[g.meta.key]);
      const acc = el('div', { class: 'acc' + (state.itemOpen[g.meta.key] ? ' open' : '') }, h.btn, body);
      h.btn.addEventListener('click', () => {
        const on = acc.classList.toggle('open');
        state.itemOpen[g.meta.key] = on;
        h.btn.setAttribute('aria-expanded', String(on));
      });
      accs[g.meta.key] = { acc, badge: h.badge, body };
      root.append(acc);
      continue;
    }
    if (unverified) body.append(el('p', { class: 'hint p-warn', text: t('grant.list.unverified') }));
    for (const it of g.items) {
      const box = el('input', { type: 'checkbox', class: 'tick' });
      const qty = el('input', { type: 'number', min: '0', step: '1', class: 'qty',
                                placeholder: '1', disabled: true, 'aria-label': t('grant.amount') });
      box.checked = it.id in state.itemSel;
      if (box.checked) { qty.value = String(state.itemSel[it.id]); qty.disabled = false; }
      box.onchange = () => {
        qty.disabled = !box.checked;
        if (box.checked) {
          if (!qty.value) qty.value = '1';
          state.itemSel[it.id] = Number(qty.value) || 0;
        } else delete state.itemSel[it.id];
        refresh();
      };
      qty.oninput = () => { if (box.checked) state.itemSel[it.id] = Number(qty.value) || 0; };
      body.append(el('div', { class: 'irow', dataset: { q: (itemName(it) + ' ' + it.id).toLowerCase() } },
        el('label', { class: 'ibox' }, box),
        el('span', { class: 'iname', text: itemName(it) }),
        el('span', { class: 'hint mono', text: '#' + it.id }),
        el('span', { class: 'ibal', text: cur[it.id] == null ? '—' : fmtNum(cur[it.id]) }),
        flag ? el('span', { class: 'hint', text: t('grant.list.unlock') }) : qty));
    }
    const h = head(g.meta.key, catLabel(g.meta), g.items.length, !!state.itemOpen[g.meta.key]);
    const acc = el('div', { class: 'acc' + (state.itemOpen[g.meta.key] ? ' open' : '') }, h.btn, body);
    h.btn.addEventListener('click', () => {
      const on = acc.classList.toggle('open');
      state.itemOpen[g.meta.key] = on;
      h.btn.setAttribute('aria-expanded', String(on));
    });
    accs[g.meta.key] = { acc, badge: h.badge, body };
    root.append(acc);
  }

  const filter = el('input', { type: 'search', class: 'filter', placeholder: t('grant.list.search') });
  filter.addEventListener('input', () => {
    const qq = filter.value.trim().toLowerCase();
    let shown = 0;
    for (const g of groups) {
      let vis = 0;
      for (const row of accs[g.meta.key].body.querySelectorAll('.irow')) {
        const hit = !qq || row.dataset.q.indexOf(qq) >= 0;
        row.hidden = !hit;
        if (hit) vis++;
      }
      accs[g.meta.key].acc.hidden = !vis;
      if (qq && vis) accs[g.meta.key].acc.classList.add('open');
      // 涂装是嵌套折叠：搜索时把「有命中的那辆车」展开，清空搜索后恢复玩家自己的展开状态。
      for (const a of accs[g.meta.key].body.querySelectorAll('.acc-sub')) {
        a.classList.toggle('open',
          qq ? a.querySelector('.irow:not([hidden])') !== null : !!state.itemOpen[a.dataset.k]);
      }
      shown += vis;
    }
    empty.hidden = shown > 0;
  });
  refresh();
  return { root, filter, total, empty,
    picks: () => Object.keys(state.itemSel).map(id => ({
      item_id: Number(id), amount: Number(state.itemSel[id]) || 0,
      mode: FLAG_CATS[(cat.items[id] || {}).cat] ? 'set' : state.grantMode,
    })).filter(x => x.amount !== 0 && cat.items[x.item_id]),
    // 涂装不走 items2 的 id（每个编号一半还同时是零件号），单独一堆 id 交给服务端写位。
    paintPicks: () => selKeys().filter(k => k.charAt(0) === 'p').map(k => Number(k.slice(1))),
    paintName: id => {
      const p = (cat.paints || {})[id];
      return p ? ((LANG === 'cn' ? p.cn : p.en) || p.en || p.name || ('#' + id)) : ('#' + id);
    },
    name: id => (cat.items[id] && itemName(cat.items[id])) || ('#' + id),
    clear: () => { state.itemSel = {}; } };
}

async function screenGrant() {
  const data = await api('/__saves');
  state.saves = data.saves || [];
  const nodes = [el('p', { class: 'lead', text: t('grant.lead') })];

  if (!state.saves.length) {
    nodes.push(el('section', { class: 'card' },
      el('div', { class: 'empty', text: t('grant.noSave') })));
    return nodes;
  }
  if (!state.saves.some(s => s.profileId === state.grantProfile)) {
    state.grantProfile = state.saves[0].profileId;
  }

  const sel = el('select', { id: 'grantSlot', onchange: e => {
    state.grantProfile = e.target.value;
    state.grantAmounts = {};
    state.pvpAmounts = {};
    show('grant');
  } }, state.saves.map(s => el('option', {
    value: s.profileId, selected: s.profileId === state.grantProfile,
    text: (s.account || t('saves.anonAccount')) + ' · ' + s.profileId.slice(0, 8) +
          ' · ' + t('saves.col.richness') + ' ' + s.richness,
  })));

  let doc = null;
  try {
    doc = await api('/__save?profile=' + encodeURIComponent(state.grantProfile));
  } catch (e) {
    if (e.auth || e.net) throw e;
    nodes.push(el('section', { class: 'card' },
      el('div', { class: 'empty', text: t('grant.noSave') })));
    return nodes;
  }
  // 竞技场读不到不算致命（刚建的槽可能还没打过 PVP），照常渲染，数值显示 —。
  let pvp = null;
  try {
    pvp = (await api('/__api/admin/pvp?profile=' + encodeURIComponent(state.grantProfile))).player;
  } catch (e) { if (e.auth || e.net) throw e; }

  const m = items2Map(doc && doc.content);
  const row = state.saves.filter(s => s.profileId === state.grantProfile)[0];
  const bal = n => (n == null ? '—' : fmtNum(n));

  const pick = el('section', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', { class: 'grow', text: t('grant.pick') })),
    el('div', { class: 'card-body' },
      sel,
      row ? el('div', { class: 'kv' },
        el('div', null, el('div', { class: 'k', text: t('saves.col.richness') }),
            el('div', { class: 'v', text: fmtNum(row.richness) })),
        el('div', null, el('div', { class: 'k', text: t('saves.version') }),
            el('div', { class: 'v', text: fmtNum(doc && doc.version) }))) : null));

  // ── 竞技场：服务端即时生效 ────────────────────────────────────────────────
  const pvpRows = PVP_ITEMS.map(name => el('div', { class: 'itemrow' },
    el('div', { class: 'nm' },
      el('b', { text: t(PVP_LABEL[name]) }),
      el('span', { class: 'hint mono', text: name })),
    el('div', { class: 'bal', text: t('grant.balance') + ' ' + bal(pvp && pvp[name]) }),
    el('input', {
      type: 'number', min: '0', step: '1', value: state.pvpAmounts[name] || '',
      placeholder: '0', oninput: e => { state.pvpAmounts[name] = e.target.value; },
    })));

  const pvpSubmit = el('button', {
    class: 'btn primary', text: t('grant.pvpSubmit'),
    onclick: () => guarded(async () => {
      const fields = {};
      PVP_ITEMS.forEach(n => {
        const v = Number(state.pvpAmounts[n] || 0);
        if (v) fields[n] = v;
      });
      if (!Object.keys(fields).length) { toast(t('grant.zero'), { kind: 'bad' }); return; }
      pvpSubmit.disabled = true;
      try {
        const r = await post('/__api/admin/pvp',
          { profile: state.grantProfile, fields, mode: state.pvpMode });
        toast(t('grant.pvpDone', { summary: r.applied.map(a =>
          t(PVP_LABEL[a.field]) + ' ' + fmtNum(a.before) + ' → ' + fmtNum(a.after)
        ).join('　') }), { kind: 'good' });
        state.pvpAmounts = {};
        show('grant');
      } finally { pvpSubmit.disabled = false; }
    }),
  });

  const pvpCard = el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('grant.pvpTitle') }),
      modeSeg(state.pvpMode, mo => { state.pvpMode = mo; show('grant'); })),
    el('div', { class: 'card-body' },
      el('p', { class: 'lead', text: t('grant.pvpLead') }),
      el('p', { class: 'hint mono', text: t('grant.pvpPlace') }),
      pvpRows,
      el('p', { class: 'hint', text: (pvp && pvp.known) ? [
        t('grant.pvpRank') + ' ' + bal(pvp.rank),
        t('grant.pvpStar') + ' ' + bal(pvp.star),
        t('grant.pvpSeason') + ' ' + bal(pvp.season),
        t('grant.pvpStreak') + ' ' + bal(pvp.win_streak),
      ].join('　') : t('grant.pvpNever') })),
    el('div', { class: 'card-head' }, el('span', { class: 'grow' }), pvpSubmit));

  // ── 存档物品：官方目录清单，按类折叠 ───────────────────────────────────────
  let cat = null;
  try {
    cat = await catalog();
  } catch (e) { if (e.auth || e.net) throw e; }
  const list = cat ? itemPicker(cat, m) : null;

  const submit = el('button', {
    class: 'btn primary', text: t('grant.submit'),
    onclick: () => guarded(async () => {
      const items = list ? list.picks() : [];
      const paints = list ? list.paintPicks() : [];
      if (!items.length && !paints.length) { toast(t('grant.zero'), { kind: 'bad' }); return; }
      submit.disabled = true;
      try {
        const r = await post('/__api/admin/grant', { profile: state.grantProfile, items, paints });
        const summary = r.applied.map(a =>
          (list ? list.name(a.item_id) : '#' + a.item_id) + ' ' +
          fmtNum(a.before) + ' → ' + fmtNum(a.after))
          .concat((r.paint_applied || []).map(a =>
            (list ? list.paintName(a.paint_id) : '#' + a.paint_id) + ' ' +
            t('grant.list.owned') + '（' + t('grant.list.slot', { n: a.slot }) + '）')).join('　');
        toast(t('grant.doneBody', {
          profile: state.grantProfile.slice(0, 8),
          summary: summary,
          from: r.server_version - 1,
          to: r.server_version,
        }), {
          kind: 'good',
          action: { label: t('grant.undo'), run: () => guarded(async () => {
            await post('/__api/admin/revert', { profile: state.grantProfile, snapshot: r.snapshot });
            toast(t('grant.undone', { ts: snapshotLabel(r.snapshot) }), { kind: 'good' });
            show('grant');
          }) },
        });
        if (list) list.clear();
        show('grant');
      } finally { submit.disabled = false; }
    }),
  });

  const warn = el('section', { class: 'card pad', style: 'border-color:color-mix(in srgb, var(--warn) 40%, transparent)' },
    el('h2', null, el('span', { class: 'badge warn', text: '!' }), ' ', t('grant.warnTitle')),
    el('p', { class: 'lead', text: t('grant.warnBody') }),
    el('p', { class: 'lead p-warn', text: t('grant.warnBody2') }));

  const listCard = el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: t('grant.saveTitle') }),
      el('span', { class: 'hint', text: t('grant.modeHint') }),
      modeSeg(state.grantMode, mo => { state.grantMode = mo; show('grant'); })),
    el('div', { class: 'card-body' },
      list ? el('div', { class: 'listbar' }, list.filter, list.total) : null,
      list ? list.root : el('div', { class: 'empty', text: t('grant.noSave') }),
      list ? list.empty : null,
      el('p', { class: 'hint', text: t('grant.whitelist') })),
    el('div', { class: 'card-head' }, el('span', { class: 'grow' }), submit));

  nodes.push(pick, pvpCard, warn, listCard);
  return nodes;
}

// ─────────────────────────────────────────────── 壳 / 登录

function showLogin(msg) {
  $('#shell').hidden = true;
  $('#login').hidden = false;
  const err = $('#loginErr');
  if (msg) { err.textContent = msg; err.hidden = false; } else { err.hidden = true; }
}

function enterShell(username) {
  $('#login').hidden = true;
  $('#shell').hidden = false;
  $('#whoami').textContent = username || '—';
  route();
  // 侧栏 pill 要等布局稳定后再量位置（首帧里 sidebar 还没铺开）。
  requestAnimationFrame(movePill);
}

async function onLogin(e) {
  e.preventDefault();
  const form = e.target, err = $('#loginErr');
  const btn = form.querySelector('button[type=submit]');
  err.hidden = true;
  btn.disabled = true;
  try {
    const r = await post('/__api/admin/login', {
      username: form.username.value, password: form.password.value });
    form.password.value = '';
    enterShell(r.username);
    toast(t('login.welcome', { name: r.username }), { kind: 'good', timeout: 2600 });
    ping();
  } catch (e2) {
    err.textContent = e2.message || t('login.fail');
    err.hidden = false;
  } finally { btn.disabled = false; }
}

async function onLogout() {
  try { await post('/__api/admin/logout', {}); } catch (e) { /* 本来就要退出 */ }
  showLogin();
}

async function ping() {
  const d = $('#statusDot');
  try {
    const r = await fetch('/__ping', { credentials: 'same-origin' });
    d.className = 'dot ' + (r.ok ? 'on' : 'off');
    d.title = r.ok ? t('status.online') : t('status.offline');
  } catch (e) {
    d.className = 'dot off';
    d.title = t('status.offline');
  }
}

async function boot() {
  installSprings();
  try {
    const r = await fetch('/__admin/i18n.json', { credentials: 'same-origin' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    DICT = await r.json();
  } catch (e) {
    // 文案都没了就别装作能用，直接摊开说。
    document.body.replaceChildren(el('div', { class: 'empty',
      text: 'i18n.json 加载失败 / failed to load i18n.json: ' + e.message }));
    return;
  }
  LANG = pickLang();
  document.title = t('app.name');
  applyLang();

  $('#loginForm').addEventListener('submit', onLogin);
  $('#btnLogout').addEventListener('click', onLogout);
  $('#btnRefresh').addEventListener('click', () => show(state.screen));
  $('#langSeg').addEventListener('click', e => {
    const b = e.target.closest('button[data-lang]');
    if (b) setLang(b.dataset.lang);
  });
  window.addEventListener('hashchange', route);
  window.addEventListener('resize', movePill);

  $('#boot').hidden = true;
  try {
    const me = await api('/__api/admin/me');
    if (me && me.username) { enterShell(me.username); ping(); return; }
  } catch (e) { /* 没登录就是这里，正常 */ }
  showLogin();
}

boot();
