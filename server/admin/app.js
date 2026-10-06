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
    // o.input:{label,value,placeholder} ⇒ 弹一个输入框，确认时 resolve 输入内容（取消仍是 false）。
    // 模板改名/复制要的就是这个：不问名字只让确认，等于逼人重存一遍。
    const kids = [];
    if (o.body) kids.push(el('p', { text: o.body }));
    let inp = null;
    if (o.input) {
      inp = el('input', { type: 'text', maxlength: String(o.input.maxlength || 40),
                          value: o.input.value == null ? '' : String(o.input.value) });
      if (o.input.placeholder) inp.placeholder = String(o.input.placeholder);
      inp.setAttribute('aria-label', o.input.label || o.title || t('app.confirm'));
      kids.push(el('div', { class: 'field' }, o.input.label ? el('span', { text: o.input.label }) : null, inp));
    }
    body.replaceChildren.apply(body, kids.length ? kids : [document.createTextNode('')]);
    ok.textContent = o.okLabel || t('app.confirm');
    m.hidden = false;
    if (inp) { inp.focus(); inp.select(); } else ok.focus();
    function done(v) {
      m.hidden = true;
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      m.removeEventListener('click', onBg);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    }
    function onOk() { done(inp ? inp.value : true); }
    function onCancel() { done(false); }
    function onBg(e) { if (e.target === m) done(false); }
    function onKey(e) {
      if (e.key === 'Escape') done(false);
      else if (e.key === 'Enter' && inp) { e.preventDefault(); done(inp.value); }
    }
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
  weekly: { titleKey: 'nav.weekly', load: screenWeekly },
  bunker: { titleKey: 'nav.bunker', load: screenBunker },
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

// ─────────────────────────────────────────────── 屏 · 午夜杯（周赛运营）

// 这一屏只改服务端 `weekly.*` 段。配置按文件 mtime 热加载 ⇒ 保存即生效：不重启服务、
// 不动客户端契约、玩家不用做任何事。★ 例外是奖励池子 —— 客户端只在「进入午夜杯」那一刻
// 读一次 reward_config，所以奖励改完要让玩家退出午夜杯再进（不是重启游戏）。

// 键名放表里、t() 收变量。I18n 测试会单独核这些键（tests/test_admin_webui.py 的 KEYS）。
const WEEKLY_FIELD = {
  track_id: 'weekly.f.track', leaderboard_id: 'weekly.f.board',
  bike_id: 'weekly.f.bike', loan_upgrade: 'weekly.f.loan',
  fake_field: 'weekly.f.fake', fake_field_base_ms: 'weekly.f.base',
  fake_field_fast_pct: 'weekly.f.fast', fake_field_slow_pct: 'weekly.f.slow',
  left_retry_times: 'weekly.f.retry', cooldown_seconds: 'weekly.f.cool',
  week_offset: 'weekly.f.offset', reward_slots: 'weekly.f.slots',
  window_days: 'weekly.f.days', reward_ids: 'weekly.f.rewardIds',
};

// 车表（服务端下发：`/conf/bikes.txt` 的 19 台，带级别与「剧情车」标记）。
// 两屏共用：午夜杯的「本届车」下拉、碉堡的「固定车辆」下拉、审计列里的车号翻译。
let BIKES = [];
function bikeName(id) {
  const n = Number(id);
  const hit = BIKES.filter(x => Number(x.id) === n)[0];
  return hit ? ((LANG === 'cn' ? hit.name_cn : hit.name) || hit.name || '') : '';
}
// 车号 -> 人读的一行；0 / 空 = 自动（午夜杯专用：按赛道级别随机）。
function bikeLabel(id) {
  const n = Number(id);
  if (!n) return t('weekly.bike.autoVal');
  return '#' + n + (bikeName(n) ? ' ' + bikeName(n) : '');
}

// 车辆级别 -> 界面文字：0/1/2 = T0/T1/T2（车和图必须同级），255 / 缺 = 不限。
// 规则来自客户端 `LevelManager::isCorrectBikeTier @0x47c170`。
function tierText(b) {
  return (b === 255 || b === null || b === undefined) ? t('app.tier.any') : 'T' + b;
}

function bikeTierOf(id) {
  const hit = BIKES.filter(x => Number(x.id) === Number(id))[0];
  return hit ? hit.tier : null;
}

const WEEKLY_TIERS = ['platinum', 'gold', 'silver', 'bronze', 'wood'];

const TIER_LABEL = { platinum: 'weekly.tier.platinum', gold: 'weekly.tier.gold',
                     silver: 'weekly.tier.silver', bronze: 'weekly.tier.bronze',
                     wood: 'weekly.tier.wood' };

// 服务端 _WEEK_SECONDS / 86400。只有 7 天在真机验过，别的天数界面挂「实验性」。
const WEEKLY_DAYS = 7;

// 秒 → 「x 天 y 小时」。窗口和冷却都是一周量级，纯秒数没人读得出来。
function spanText(sec) {
  let s = Math.max(0, Math.floor(Number(sec) || 0));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d) return t('app.span.dh', { d: fmtNum(d), h: fmtNum(h) });
  if (h) return t('app.span.hm', { h: fmtNum(h), m: fmtNum(m) });
  return t('app.span.m', { m: fmtNum(m) });
}

// 一个运营参数 → 人能读的一行。reward_ids 是 {档位: [池子编号]}，要摊平。
function weeklyVal(key, v) {
  if (key === 'reward_ids') {
    const parts = WEEKLY_TIERS.filter(ti => ((v && v[ti]) || []).length)
                              .map(ti => t(TIER_LABEL[ti]) + ' ' + v[ti].join('/'));
    return parts.length ? parts.join(' · ') : t('weekly.rewards.builtin');
  }
  if (v === null || v === undefined || v === '') return '—';
  if (key === 'window_days') return t('app.days', { n: fmtNum(v) });
  if (key === 'cooldown_seconds') return spanText(v);
  if (key === 'fake_field_base_ms') return fmtNum(v) + ' ms';
  if (key === 'track_id') return '#' + v;
  if (key === 'bike_id') return bikeLabel(v);
  if (key === 'loan_upgrade') return Number(v) ? t('weekly.loan.lv', { n: fmtNum(v) }) : t('weekly.loan.off');
  return fmtNum(v);
}

function kvItem(k, v) {
  return el('div', null, el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v }));
}

// 表单行：左边标签+说明，右边控件。窄屏自动变单列（见 app.css 的 .frow）。
// `fRowRaw` 收现成文案 —— 碉堡页的标签来自服务端的字段表（中英双语写在表里），
// 不经过 i18n.json。`wide` = 控件铺满整张卡（赛道清单 / 星章表这种宽控件）。
function fRowRaw(label, control, hint, wide) {
  return el('div', { class: 'frow' + (wide ? ' wide' : '') },
    el('div', { class: 'fl' },
      el('div', { class: 'fk', text: label }),
      hint ? el('div', { class: 'hint', text: hint }) : null),
    el('div', { class: 'fc' }, ...(Array.isArray(control) ? control : [control])));
}

function fRow(labelKey, control, hint) { return fRowRaw(t(labelKey), control, hint); }

// 数字框：空 ⇒ null（= 删掉这个键、回到代码默认值），否则 Number。整数校验在服务端。
function numBox(value, onchange, o) {
  o = o || {};
  const inp = el('input', { type: 'number', inputmode: 'numeric',
                            value: value === null || value === undefined ? '' : String(value) });
  if (o.min !== undefined) inp.min = String(o.min);
  if (o.max !== undefined) inp.max = String(o.max);
  if (o.list) inp.setAttribute('list', o.list);
  inp.addEventListener('input', () => onchange(inp.value === '' ? null : Number(inp.value)));
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') inp.blur(); });
  return inp;
}

// 卡片右下角的提交行（左列留空 ⇒ 按钮落在控件那一列）。
function cardFoot(...btns) {
  return el('div', { class: 'frow' }, el('div', { class: 'fl' }), el('div', { class: 'fc' }, ...btns));
}

function wCardRaw(label, hint, ...body) {
  return el('section', { class: 'card' },
    el('div', { class: 'card-head' },
      el('h2', { class: 'grow', text: label }),
      hint ? el('span', { class: 'hint', text: hint }) : null),
    el('div', { class: 'card-body' }, ...body));
}

function wCard(titleKey, hint, ...body) { return wCardRaw(t(titleKey), hint, ...body); }

function wSub(labelKey, ...body) {
  return el('div', { class: 'grp' }, el('div', { class: 'sub', text: t(labelKey) }), ...body);
}

// 「怎么运作」引导卡：静态规则，一句一行。★ 这类文案跟界面语言走、放在 i18n 里；
// 服务端字段表里只放「参数」的标签与说明。凡是「改了参数以后坏了」的坑都写在这里。
function guideCard(titleKey, ...lines) {
  return wCard(titleKey, null, ...lines.map(l => el('p', { class: 'hint', text: l })));
}

async function screenWeekly() {
  const data = await api('/__api/admin/weekly');
  const cfg = data.config || {}, st = data.status || {}, tracks = data.tracks || [];
  BIKES = st.bikes || [];
  const draft = Object.assign({}, cfg);   // 只有本屏改得动的键；保存时只发真的变了的
  const nodes = [el('p', { class: 'lead', text: t('weekly.lead') })];
  // ── ⓪ 引导：午夜杯没有开关（届号是算出来的）。先说清楚，再动参数。
  nodes.push(guideCard('weekly.guide.title',
    t('weekly.guide.l1'), t('weekly.guide.l2'), t('weekly.guide.l3'),
    t('weekly.guide.l4'), t('weekly.guide.l5'), t('weekly.guide.l6')));
  const trackName = id => {
    const hit = tracks.filter(x => Number(x.id) === Number(id))[0];
    return hit ? ((LANG === 'cn' ? hit.name_cn : hit.name) || hit.name || '') : '';
  };

  // 保存：只发改动的键（服务端按键审计 ⇒ 没动就不该留记录）。成功后在 toast 里给撤销。
  async function saveFields(fields, okKey) {
    return guarded(async () => {
      const keys = Object.keys(fields);
      if (!keys.length) { toast(t('weekly.noChange'), { kind: 'warn', timeout: 2600 }); return; }
      const r = await post('/__api/admin/weekly', { fields });
      const applied = r.applied || [];
      const sum = applied.map(a => (WEEKLY_FIELD[a.key] ? t(WEEKLY_FIELD[a.key]) : a.key) + ' ' + weeklyVal(a.key, a.after)).join('　');
      const ids = applied.map(a => a.audit).filter(Boolean);
      const opts = { kind: 'good' };
      if (ids.length) opts.action = { label: t('weekly.undo'), run: () => guarded(async () => {
        for (const id of ids) await post('/__api/admin/undo', { id });
        show('weekly');
      }) };
      toast(t(okKey) + (sum ? ' · ' + sum : ''), opts);
      show('weekly');
    });
  }
  function diffFields(keys) {
    const out = {};
    for (const k of keys) {
      const a = draft[k] === undefined ? null : draft[k];
      const b = cfg[k] === undefined ? null : cfg[k];
      if (JSON.stringify(a) !== JSON.stringify(b)) out[k] = (a === '' ? null : a);
    }
    return out;
  }

  // ── ① 现状：全只读。数字都由服务端实时算（status），界面不自己推。
  const expBadge = el('span', { class: 'badge warn', text: t('weekly.experimental') });
  expBadge.hidden = Number(st.window_days) === WEEKLY_DAYS;
  const nowKv = el('div', { class: 'kv' },
    kvItem(t('weekly.now.track'), '#' + st.track_id + (trackName(st.track_id) ? ' ' + trackName(st.track_id) : '')),
    // 本周发给所有人的那台车（租借升级 = 玩家升级不够时补到的等级）。只读，实时算。
    kvItem(t('weekly.now.bike'), bikeLabel(st.effective_bike) + ' · ' +
      (Number(cfg.loan_upgrade) ? t('weekly.loan.lv', { n: fmtNum(cfg.loan_upgrade) }) : t('weekly.loan.off'))),
    kvItem(t('weekly.now.window'), fmtTime(st.week_start) + ' → ' + fmtTime(st.week_end)),
    kvItem(t('weekly.now.left'), spanText(st.week_end - st.now)),
    kvItem(t('weekly.now.week'), '#' + st.week_index),
    kvItem(t('weekly.now.entries'), fmtNum(st.entries) + ' · ' + t('weekly.now.fake') + ' ' + fmtNum(st.fake)),
    kvItem(t('weekly.now.rules'), fmtNum(st.retry_limit) + ' × / ' + spanText(st.cooldown_seconds)),
    kvItem(t('weekly.now.base'), fmtNum(st.base_ms) + ' ms'),
    kvItem(t('weekly.now.health'), fmtNum(st.ghosts) + ' / ' + fmtNum(st.board_rows)),
    kvItem(t('weekly.now.days'), t('app.days', { n: st.window_days })));
  nodes.push(el('section', { class: 'card' },
    el('div', { class: 'card-head' }, el('h2', { class: 'grow', text: t('weekly.now.title') }), expBadge),
    el('div', { class: 'card-body' },
      nowKv,
      el('p', { class: 'lead p-warn', text: t('weekly.now.warn') }),
      // 预检：赛道没幽灵 / 周榜 ID 指到空榜 / 窗口不是 7 天 —— 都是「改完就进不去」的坑。
      ...(st.warnings || []).map(w => el('p', { class: 'lead p-warn',
        text: (LANG === 'cn' ? w.cn : (w.en || w.cn)) || '' })),
      wSub('weekly.now.playersTitle',
        (st.players || []).length
          ? table([
              { label: t('weekly.col.profile'), k: 'profile', render: r => el('span', { class: 'mono', text: String(r.profile).slice(0, 12) }) },
              { label: t('weekly.col.used'), k: 'used', cls: 'r' },
              { label: t('weekly.col.left'), k: 'left', cls: 'r' },
              { label: t('weekly.col.last'), k: 'last_attempt', render: r => (r.last_attempt ? fmtTime(r.last_attempt) : dash()) },
              { label: t('weekly.col.week'), k: 'this_week', render: r => el('span', { class: 'badge' + (r.this_week ? ' ok' : ''), text: r.this_week ? t('weekly.col.thisWeek') : t('weekly.col.oldWeek') }) },
            ], st.players)
          : el('div', { class: 'empty', text: t('weekly.now.noPlayers') })),
      wSub('weekly.now.auditTitle',
        (data.audit || []).length
          ? table([
              { label: t('weekly.col.time'), k: 'at', render: r => fmtTime(r.at) },
              { label: t('weekly.col.param'), k: 'path', render: r => {
                  const k = (r.path || []).slice(-1)[0];
                  return (WEEKLY_FIELD[k] ? t(WEEKLY_FIELD[k]) : String(k)) + (r.kind === 'undo' ? ' · ' + t('weekly.kindUndo') : '');
                } },
              { label: t('weekly.col.change'), k: 'after', render: r => {
                  const k = (r.path || []).slice(-1)[0];
                  return (r.existed === false ? '—' : weeklyVal(k, r.before)) + ' → ' + weeklyVal(k, r.after);
                } },
              { label: '', cls: 'act', render: r => el('button', { class: 'btn tiny', type: 'button', text: t('weekly.undoBtn'),
                  onclick: () => guarded(async () => {
                    await post('/__api/admin/undo', { id: r.id });
                    toast(t('weekly.undone'), { kind: 'good', timeout: 2600 });
                    show('weekly');
                  }) }) },
            ], data.audit)
          : el('div', { class: 'empty', text: t('weekly.now.noAudit') })))));

  // ── ② 时间：窗口长度 + 翻周。翻周靠 week_offset —— 服务端按周给玩家次数分桶，
  //     所以周号一变，本周次数自然从头开始，不用去清内存里的计数。
  const preview = el('div', { class: 'hint' });
  function weekPreview() {
    const span = Math.max(1, Math.min(30, Number(draft.window_days) || WEEKLY_DAYS)) * 86400;
    const off = Number(draft.week_offset) || 0;
    const start = Math.floor(st.now / span) * span + off * span;
    preview.textContent = t('weekly.time.preview') + ' ' + fmtTime(start) + ' → ' + fmtTime(start + span);
  }
  const daysIn = numBox(draft.window_days, v => {
    draft.window_days = v;
    expBadge.hidden = Number(v) === WEEKLY_DAYS;
    weekPreview();
  }, { min: 1, max: 30 });
  const offBtns = [-1, 0, 1].map(off => el('button', {
    type: 'button', 'aria-pressed': String(Number(cfg.week_offset) === off),
    text: off < 0 ? t('weekly.time.prev') : (off > 0 ? t('weekly.time.next') : t('weekly.time.this')),
    onclick: () => {
      draft.week_offset = off;
      offBtns.forEach((b, i) => b.setAttribute('aria-pressed', String(i === off + 1)));
      weekPreview();
    },
  }));
  const resetBtn = el('button', { class: 'btn danger', type: 'button', text: t('weekly.time.reset'),
    onclick: () => guarded(async () => {
      const yes = await confirmDialog({ title: t('weekly.time.reset'), body: t('weekly.time.resetBody'),
                                        okLabel: t('weekly.time.reset') });
      if (!yes) return;
      const r = await post('/__api/admin/weekly', { fields: { week_offset: Number(cfg.week_offset) + 1 } });
      const id = ((r.applied || [])[0] || {}).audit;
      const opts = { kind: 'good' };
      if (id) opts.action = { label: t('weekly.undo'), run: () => guarded(async () => {
        await post('/__api/admin/undo', { id }); show('weekly');
      }) };
      toast(t('weekly.time.resetDone', { n: r.config.week_offset }), opts);
      show('weekly');
    }) });
  weekPreview();
  nodes.push(wCard('weekly.time.title', t('weekly.time.hint'),
    fRow('weekly.f.days', [daysIn, expBadge, el('span', { class: 'hint', text: t('weekly.f.daysHint') })], null),
    fRow('weekly.f.offset', [el('div', { class: 'seg' }, offBtns), preview], t('weekly.f.offsetHint')),
    fRow('weekly.time.reset', resetBtn, t('weekly.time.resetHint')),
    cardFoot(el('button', { class: 'btn primary', type: 'button', text: t('weekly.save'),
      onclick: () => saveFields(diffFields(['window_days', 'week_offset']), 'weekly.saved') }))));

  // ── ③ 挑战规则：每周次数 + 冷却。冷却用秒输入 —— 分钟取整会造成玩家看不见的漂移。
  const coolHint = el('span', { class: 'hint', text: spanText(draft.cooldown_seconds) });
  const coolIn = numBox(draft.cooldown_seconds, v => {
    draft.cooldown_seconds = v;
    coolHint.textContent = spanText(v);
  }, { min: 0, max: 30 * 24 * 3600 });
  const coolPresets = [[60, 'weekly.rules.p1'], [600, 'weekly.rules.p10'],
                       [3600, 'weekly.rules.p1h'], [21600, 'weekly.rules.p6h']]
    .map(p => el('button', { class: 'btn tiny', type: 'button', text: t(p[1]), onclick: () => {
      draft.cooldown_seconds = p[0];
      coolIn.value = String(p[0]);
      coolHint.textContent = spanText(p[0]);
    } }));
  nodes.push(wCard('weekly.rules.title', null,
    fRow('weekly.f.retry', [numBox(draft.left_retry_times, v => { draft.left_retry_times = v; }, { min: 0, max: 99 }),
                            el('span', { class: 'hint', text: t('weekly.rules.retryHint') })], null),
    fRow('weekly.f.cool', [coolIn, ...coolPresets, coolHint], null),
    el('p', { class: 'hint', text: t('weekly.rules.note') }),
    cardFoot(el('button', { class: 'btn primary', type: 'button', text: t('weekly.save'),
      onclick: () => saveFields(diffFields(['left_retry_times', 'cooldown_seconds']), 'weekly.saved') }))));

  // ── ④ 赛道与对手：赛道下拉来自 server/admin/items.json 的 levels 段（客户端原表），
  //     没有那段就退化成手填编号。
  const trHint = el('span', { class: 'hint' });
  function updTrack() {
    const nm = trackName(draft.track_id);
    const tb = tracks.filter(x => Number(x.id) === Number(draft.track_id))[0];
    trHint.textContent = (nm ? '#' + draft.track_id + ' ' + nm : t('weekly.track.unknown')) +
      (tb ? ' · ' + t('app.tier.lv') + ' ' + tierText(tb.bike) : '');
  }
  const dl = el('datalist', { id: 'tfTracks' });
  tracks.forEach(x => dl.appendChild(el('option', { value: String(x.id),
    text: (LANG === 'cn' ? x.name_cn : x.name) || x.name || '' })));
  const trackIn = numBox(draft.track_id, v => { draft.track_id = v; updTrack(); },
                         { min: 1, max: 1000000, list: 'tfTracks' });
  updTrack();
  // 本届的车：0 = 自动（按赛道级别从剧情车里随机，按周号播种 ⇒ 整周不变）；填车号 =
  // 整届固定发这台（玩家没有或升级更低时客户端发租借车，不入他的车库）。
  const bikeHit = id => BIKES.filter(x => Number(x.id) === Number(id))[0];
  const bikeDl = el('datalist', { id: 'tfBikes' });
  BIKES.forEach(b => bikeDl.appendChild(el('option', { value: String(b.id),
    text: '#' + b.id + ' ' + ((LANG === 'cn' ? b.name_cn : b.name) || b.name || '') })));
  const bikeHint = el('span', { class: 'hint' });
  function updBike() {
    const n = Number(draft.bike_id) || 0;
    const hit = bikeHit(n);
    bikeHint.textContent = n
      ? '#' + n + ' ' + (bikeName(n) || t('weekly.bike.unknown')) +
        (hit ? ' · ' + tierText(hit.tier) + (hit.story ? '' : ' · ' + t('weekly.bike.notStory')) : '')
      : t('weekly.bike.autoVal') + ' → ' + bikeLabel(st.effective_bike);
  }
  updBike();
  nodes.push(wCard('weekly.track.title', null,
    fRow('weekly.f.track', [trackIn, dl, trHint], tracks.length ? null : t('weekly.track.noCatalog')),
    fRow('weekly.f.bike', [numBox(draft.bike_id, v => { draft.bike_id = v; updBike(); },
                                  { min: 0, max: 64, list: 'tfBikes' }), bikeDl, bikeHint],
         BIKES.length ? t('weekly.bike.hint') : t('weekly.bike.noCatalog')),
    fRow('weekly.f.loan', [numBox(draft.loan_upgrade, v => { draft.loan_upgrade = v; }, { min: 0, max: 10 }),
                           el('span', { class: 'hint', text: t('weekly.loan.hint') })], null),
    fRow('weekly.f.board', [numBox(draft.leaderboard_id, v => { draft.leaderboard_id = v; }, { min: 0, max: 0xFFFFFF }),
                            el('span', { class: 'hint', text: t('weekly.track.boardLive') + ' ' + fmtNum(st.board) })], null),
    fRow('weekly.f.fake', [numBox(draft.fake_field, v => { draft.fake_field = v; }, { min: 0, max: 500 }),
                           el('span', { class: 'hint', text: t('weekly.track.fakeHint') + ' ' + fmtNum(st.fake) })], null),
    fRow('weekly.f.base', [numBox(draft.fake_field_base_ms, v => { draft.fake_field_base_ms = v; }, { min: 0, max: 3600000 }),
                           el('span', { class: 'hint', text: t('weekly.track.baseLive') + ' ' + fmtNum(st.base_ms) + ' ms' })], null),
    fRow('weekly.f.fast', [numBox(draft.fake_field_fast_pct, v => { draft.fake_field_fast_pct = v; }, { min: 0, max: 50 }),
                           el('span', { class: 'hint', text: t('weekly.track.pctHint') })], null),
    fRow('weekly.f.slow', [numBox(draft.fake_field_slow_pct, v => { draft.fake_field_slow_pct = v; }, { min: 0, max: 200 }),
                           el('span', { class: 'hint', text: t('weekly.track.pctHint') })], null),
    el('p', { class: 'hint', text: t('weekly.track.note') }),
    cardFoot(el('button', { class: 'btn primary', type: 'button', text: t('weekly.save'),
      onclick: () => saveFields(diffFields(['track_id', 'leaderboard_id', 'bike_id', 'loan_upgrade',
        'fake_field', 'fake_field_base_ms',
        'fake_field_fast_pct', 'fake_field_slow_pct']), 'weekly.saved') }))));

  // ── ⑤ 奖励池子：服务端只下发池子编号 1..15，具体给什么在客户端自己的奖励表里。
  //     ★ 客户端只在进入午夜杯时读一次 ⇒ 改完要让玩家退出重进（不是重启游戏）。
  const picked = {};
  WEEKLY_TIERS.forEach(ti => { picked[ti] = new Set(((cfg.reward_ids || {})[ti]) || []); });
  const tierRows = WEEKLY_TIERS.map(ti => {
    const note = el('span', { class: 'hint' });
    const setNote = () => { note.textContent = picked[ti].size ? '' : t('weekly.rewards.builtin'); };
    const chips = [];
    for (let n = 1; n <= 15; n++) {
      const b = el('button', { class: 'chip', type: 'button', text: String(n),
        'aria-pressed': String(picked[ti].has(n)),
        onclick: () => {
          if (picked[ti].has(n)) picked[ti].delete(n); else picked[ti].add(n);
          b.setAttribute('aria-pressed', String(picked[ti].has(n)));
          setNote();
        } });
      chips.push(b);
    }
    setNote();
    return el('div', { class: 'tierrow' },
      el('div', { class: 'tiername' },
        el('div', { class: 'fk', text: t(TIER_LABEL[ti]) }),
        note),
      el('div', { class: 'chips' }, chips));
  });
  const rewardMap = () => {
    const out = {};
    WEEKLY_TIERS.forEach(ti => { if (picked[ti].size) out[ti] = Array.from(picked[ti]).sort((a, b) => a - b); });
    return out;
  };
  nodes.push(wCard('weekly.rewards.title', null,
    fRow('weekly.f.slots', [numBox(draft.reward_slots, v => { draft.reward_slots = v; }, { min: 1, max: 8 }),
                            el('span', { class: 'hint', text: t('weekly.rewards.slotsHint') })], null),
    el('p', { class: 'hint', text: t('weekly.rewards.how') }),
    ...tierRows,
    el('p', { class: 'hint', text: t('weekly.rewards.reentry') }),
    cardFoot(el('button', { class: 'btn primary', type: 'button', text: t('weekly.save'),
      onclick: () => {
        const fields = diffFields(['reward_slots']);
        if (JSON.stringify(rewardMap()) !== JSON.stringify(cfg.reward_ids || {})) fields.reward_ids = rewardMap();
        return saveFields(fields, 'weekly.saved');
      } }))));

  // ── ⑥ 模板：整页参数快照。存/改名/复制/删除**不进审计**（没生效就不该进改动记录），
  //     只有「套用」会按键写审计 ⇒ 套错了能一条条撤。
  const tplName = el('input', { type: 'text', maxlength: '40', value: '',
                                placeholder: t('weekly.templates.nameHint') });
  const curKv = el('div', { class: 'kv' },
    Object.keys(WEEKLY_FIELD).map(k => kvItem(t(WEEKLY_FIELD[k]), weeklyVal(k, cfg[k]))));
  async function tplPost(body, okKey) {
    return guarded(async () => {
      const r = await post('/__api/admin/templates', body);
      toast(t(okKey), { kind: 'good', timeout: 2600 });
      show('weekly');
      return r;
    });
  }
  const tplRows = (data.templates || []).map(tp => el('div', { class: 'tplrow' },
    el('div', { class: 'grow' },
      el('div', { class: 'tname', text: tp.name }),
      el('div', { class: 'hint', text: fmtTime(tp.saved_at) })),
    el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.applyAll'),
      onclick: () => guarded(async () => {
        const r = await post('/__api/admin/templates', { page: 'weekly', action: 'apply', name: tp.name, parts: 'all' });
        const sum = (r.applied || []).map(a => (WEEKLY_FIELD[a.key] ? t(WEEKLY_FIELD[a.key]) : a.key) + ' → ' + weeklyVal(a.key, a.after)).join('　');
        const ids = (r.applied || []).map(a => a.audit).filter(Boolean);
        const opts = { kind: 'good' };
        if (ids.length) opts.action = { label: t('weekly.undo'), run: () => guarded(async () => {
          for (const id of ids) await post('/__api/admin/undo', { id }); show('weekly');
        }) };
        toast(t('weekly.templates.applied', { name: tp.name }) + (sum ? ' · ' + sum : ''), opts);
        show('weekly');
      }) }),
    el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.applyRewards'),
      onclick: () => guarded(async () => {
        const r = await post('/__api/admin/templates', { page: 'weekly', action: 'apply', name: tp.name, parts: 'rewards' });
        toast(t('weekly.templates.applied', { name: tp.name }) + ' · ' +
              weeklyVal('reward_ids', (r.config || {}).reward_ids), { kind: 'good', timeout: 4000 });
        show('weekly');
      }) }),
    el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.rename'),
      onclick: () => guarded(async () => {
        const to = await confirmDialog({ title: t('weekly.templates.rename'), okLabel: t('weekly.templates.rename'),
                                         input: { label: t('weekly.templates.name'), value: tp.name } });
        if (!to || String(to).trim() === tp.name) return;
        await tplPost({ page: 'weekly', action: 'rename', name: tp.name, new_name: String(to).trim() },
                      'weekly.templates.renamed');
      }) }),
    el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.copy'),
      onclick: () => guarded(async () => {
        const to = await confirmDialog({ title: t('weekly.templates.copy'), okLabel: t('weekly.templates.copy'),
                                         input: { label: t('weekly.templates.name'),
                                                  value: tp.name + t('weekly.templates.copySuffix') } });
        if (!to || !String(to).trim()) return;
        await tplPost({ page: 'weekly', action: 'copy', name: tp.name, new_name: String(to).trim() },
                      'weekly.templates.copied');
      }) }),
    el('button', { class: 'btn tiny danger', type: 'button', text: t('weekly.templates.delete'),
      onclick: () => guarded(async () => {
        const yes = await confirmDialog({ title: t('weekly.templates.delete'), okLabel: t('weekly.templates.delete'),
                                          body: t('weekly.templates.deleteBody', { name: tp.name }) });
        if (!yes) return;
        await tplPost({ page: 'weekly', action: 'delete', name: tp.name }, 'weekly.templates.deleted');
      }) })));

  nodes.push(wCard('weekly.templates.title', null,
    wSub('weekly.templates.currentTitle',
      curKv,
      el('p', { class: 'hint', text: t('weekly.templates.currentHint') })),
    wSub('weekly.templates.saveTitle',
      fRow('weekly.templates.name', [tplName,
        el('button', { class: 'btn primary', type: 'button', text: t('weekly.templates.save'),
          onclick: () => guarded(async () => {
            const name = String(tplName.value || '').trim();
            if (!name) { toast(t('weekly.templates.needName'), { kind: 'warn', timeout: 2600 }); return; }
            await tplPost({ page: 'weekly', action: 'save', name }, 'weekly.templates.saved');
          }) })], t('weekly.templates.saveHint'))),
    wSub('weekly.templates.listTitle',
      tplRows.length ? el('div', null, ...tplRows) : el('div', { class: 'empty', text: t('weekly.templates.none') }))));

  return nodes;
}

// ─────────────────────────────────────────────── 屏 · 碉堡（PVP 运营）

// 字段表在服务端（`_BUNKER_FIELDS`，标签中英双语写在表里）：加一个可配参数只要在服务端
// 表里写一行，这一屏不用跟着改。管的是 season / matchmaking / chips 三段，保存即生效
// （配置按 mtime 热加载，不重启服务）。
// ★ 玩家档案（段位/星章/金票）在现状卡里**只读**：直接编辑 pvp_state.json 会被服务器
//   下次写盘覆盖，要改就走这一页的参数或「竞技场」卡。

function bText(f) { return (LANG === 'cn' ? f.cn : f.en) || f.key; }
function bHint(f) { return (LANG === 'cn' ? f.hint_cn : f.hint_en) || ''; }

// 一个值 → 人能读的一行。现状卡、改动记录、模板卡三处共用。
function bunkerVal(f, v) {
  const kind = (f && f.kind) || '';
  if (kind === 'bool') return v ? t('bunker.on') : t('bunker.off');
  if (kind === 'text' || kind === 'banner') return v ? String(v) : '—';
  if (kind === 'stars') return t('bunker.stars.sum',
    { n: fmtNum((v || []).reduce((a, b) => a + (Number(b) || 0), 0)) });
  if (kind === 'ids') return t('bunker.track.count', { n: fmtNum((v || []).length) });
  if (kind === 'rewards') return t('bunker.rewards.count', { n: fmtNum((v || []).length) });
  if (kind === 'products') return t('bunker.products.count', { n: fmtNum((v || []).length) });
  if (v === null || v === undefined || v === '') return '—';
  return fmtNum(v);
}

// 秒 → 人话。用户 m08968：线上 match_duration_seconds 被手写成 300（测试值），
// 打进对局 5 分钟就被客户端按 start_time+total_time 收了局，光看数字不易发现。
function durText(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  if (s < 60) return t('app.span.s', { s: fmtNum(s) });
  if (s < 3600) {
    return s % 60 === 0 ? t('app.span.m', { m: fmtNum(s / 60) }) : t('app.span.s', { s: fmtNum(s) });
  }
  if (s % 3600 === 0) return t('app.span.h', { h: fmtNum(s / 3600) });
  return t('app.span.hm', { h: fmtNum(Math.floor(s / 3600)),
                            m: fmtNum(Math.round((s % 3600) / 60)) });
}
const DUR_KEYS = ['matchmaking.match_duration_seconds', 'matchmaking.friendly_match_duration'];
function isDurKey(k) { return DUR_KEYS.indexOf(k) >= 0; }

// 赛季奖励表：名次 0..25 一行，金币/钻石各一个数量框，特殊奖励一个「下拉 + 可手填」的
// 输入框（原表 RewardID → 名字，见 item-ids.md §8c）。
// ★ 数量是**每档增量**：客户端会把名次 R 及以上的档位累加起来发。
function rewardsEditor(rows, cat, onChange) {
  const by = {};
  for (let r = 0; r <= 25; r++) by[r] = { 1: 0, 2: 0, 145: 0 };
  (rows || []).forEach(x => {
    const r = Number(x.rank), it = Number(x.item_id);
    if (!(r in by) || (it !== 1 && it !== 2 && it !== 145)) return;
    by[r][it] = Number(x.amount) || 0;
  });
  const emit = () => {
    const out = [];
    for (let r = 0; r <= 25; r++) {
      if (by[r][1]) out.push({ rank: r, item_id: 1, amount: by[r][1] });
      if (by[r][2]) out.push({ rank: r, item_id: 2, amount: by[r][2] });
      if (by[r][145]) out.push({ rank: r, item_id: 145, amount: by[r][145] });
    }
    onChange(out);
  };
  const nm = c => (LANG === 'cn' ? c.name_cn : c.name) || c.name || '';
  const names = {}, official = {};
  cat.forEach(c => { names[String(c.id)] = nm(c); official[String(c.id)] = !!c.official; });
  // ★ 下拉里是物品表里**全部**奖励编号（按类别分组），带 ★ 的是官方赛季特殊奖表里的 43 个。
  //   表外编号照样能填 —— 显示什么由「玩家有没有这件物品」决定（见 pvp-reward-contract §5d），
  //   所以这里只提示、不拦，最下面那行会写清楚规则。
  const groups = [];
  cat.forEach(c => {
    const label = (LANG === 'cn' ? c.cat_cn : c.cat) || c.cat || '';
    let g = groups[groups.length - 1];
    if (!g || g.label !== label) groups.push(g = { label: label, rows: [] });
    g.rows.push(c);
  });
  const dl = el('datalist', { id: 'tfRewardIds' }, groups.map(g =>
    el('optgroup', { label: g.label }, g.rows.map(c => el('option', {
      value: String(c.id), text: (c.official ? '★ ' : '') + '#' + c.id + ' ' + nm(c) })))));
  const head = el('div', { class: 'rwrow rwhead' },
    el('div', { class: 'rwrank', text: t('bunker.rewards.rank') }),
    el('div', { text: t('bunker.rewards.coin') }),
    el('div', { text: t('bunker.rewards.gem') }),
    el('div', { text: t('bunker.rewards.special') }));
  const body = el('div', { class: 'rwbody' });
  for (let r = 0; r <= 25; r++) {
    const row = el('div', { class: 'rwrow' + (by[r][1] || by[r][2] || by[r][145] ? ' on' : '') });
    const dirty = () => row.classList.toggle('on', !!(by[r][1] || by[r][2] || by[r][145]));
    const num = item => {
      const inp = el('input', { type: 'number', min: '0', step: '1', class: 'rwnum',
                                value: by[r][item] ? String(by[r][item]) : '' });
      inp.addEventListener('input', () => {
        by[r][item] = Number(inp.value) || 0;
        dirty();
        emit();
      });
      return inp;
    };
    const sp = el('input', { type: 'text', class: 'rwsp', list: 'tfRewardIds', inputmode: 'numeric',
                             placeholder: t('bunker.rewards.manual') });
    const spName = el('span', { class: 'hint' });
    const mark = v => {
      const seen = !!v && !!names[String(v)];
      const off = seen && !official[String(v)];
      spName.textContent = !v ? ''
        : (seen ? names[String(v)] + (off ? ' · ' + t('bunker.rewards.nonofficial') : '')
                : t('bunker.rewards.unknown'));
      spName.classList.toggle('bad', !!v && !seen);
      spName.classList.toggle('p-warn', off);
      sp.classList.toggle('bad', !!v && !seen);
    };
    if (by[r][145]) sp.value = String(by[r][145]);
    mark(by[r][145]);
    sp.addEventListener('input', () => {
      const v = parseInt(sp.value.replace(/[^0-9]/g, ''), 10) || 0;
      by[r][145] = v;
      mark(v);
      dirty();
      emit();
    });
    row.append(el('div', { class: 'rwrank',
      text: r === 0 ? t('bunker.rank.legend') : t('bunker.rank.n', { n: r }) }),
      num(1), num(2), el('div', { class: 'rwspwrap' }, sp, spName));
    body.append(row);
  }
  return el('div', { class: 'rwtable' },
    dl,
    el('p', { class: 'hint', text: t('bunker.rewards.subtitle') }),
    head, body);
}

// 礼包表（`season.product_list`）：product_id 是商城商品 id，客户端认不出就静默忽略。
function productsEditor(rows, onChange) {
  const items = (rows || []).map(x => ({ product_id: String(x.product_id || ''),
                                        amount: Number(x.amount) || 0 }));
  const list = el('div', { class: 'plist' });
  const emit = () => onChange(items.filter(x => x.product_id)
    .map(x => ({ product_id: x.product_id, amount: x.amount })));
  const dl = el('datalist', { id: 'tfProductIds' },
    el('option', { value: 'chip_shop.goldentickets' }));
  function row(it) {
    const idIn = el('input', { type: 'text', list: 'tfProductIds', value: it.product_id,
                               placeholder: t('bunker.products.item') });
    const amtIn = el('input', { type: 'number', min: '0', step: '1', class: 'rwnum',
                                value: String(it.amount || 0) });
    idIn.addEventListener('input', () => { it.product_id = idIn.value.trim(); emit(); });
    amtIn.addEventListener('input', () => { it.amount = Number(amtIn.value) || 0; emit(); });
    const node = el('div', { class: 'prow pitem' }, idIn, amtIn,
      el('button', { class: 'btn tiny danger', type: 'button', text: t('bunker.products.remove'),
        onclick: () => {
          const i = items.indexOf(it);
          if (i >= 0) items.splice(i, 1);
          node.remove();
          emit();
        } }));
    return node;
  }
  items.forEach(it => list.append(row(it)));
  return el('div', { class: 'pwrap' }, dl, list,
    el('button', { class: 'btn tiny', type: 'button', text: t('bunker.products.add'),
      onclick: () => {
        const it = { product_id: '', amount: 1 };
        items.push(it);
        list.append(row(it));
        emit();
      } }));
}

async function screenBunker() {
  const data = await api('/__api/admin/bunker');
  const st = data.status || {}, fields = data.fields || [], values = data.values || {};
  const ctx = { tracks: data.tracks || [], rewards: data.rewards || [] };
  BIKES = data.bikes || [];    // 固定车辆下拉 / 车号翻译（两屏共用的一份车表）
  const byKey = {};
  fields.forEach(f => { byKey[f.key] = f; });
  const draft = Object.assign({}, values);
  const nodes = [el('p', { class: 'lead', text: t('bunker.lead') })];
  // ── ⓪ 引导：赛季怎么算、奖励怎么显示（★ 玩家已拥有 = 画兜底物）、什么只能在这一页改。
  nodes.push(guideCard('bunker.guide.title',
    t('bunker.guide.l1'), t('bunker.guide.l2'), t('bunker.guide.l3'),
    t('bunker.guide.l4'), t('bunker.guide.l5'), t('bunker.guide.l6')));
  const set = (k, v) => { draft[k] = v; };

  function diffFields(keys) {
    const out = {};
    for (const k of keys) {
      const a = draft[k] === undefined ? null : draft[k];
      const b = values[k] === undefined ? null : values[k];
      if (JSON.stringify(a) !== JSON.stringify(b)) out[k] = a;
    }
    return out;
  }

  async function saveFields(keys, okKey) {
    return guarded(async () => {
      const fs = diffFields(keys);
      if (!Object.keys(fs).length) { toast(t('weekly.noChange'), { kind: 'warn', timeout: 2600 }); return; }
      const r = await post('/__api/admin/bunker', { fields: fs });
      const applied = r.applied || [];
      const sum = applied.map(a => bText(byKey[a.key] || { key: a.key }) + ' ' +
                                    bunkerVal(byKey[a.key], a.after)).join('　');
      const ids = applied.map(a => a.audit).filter(Boolean);
      const opts = { kind: 'good' };
      if (ids.length) opts.action = { label: t('weekly.undo'), run: () => guarded(async () => {
        for (const id of ids) await post('/__api/admin/undo', { id });
        show('bunker');
      }) };
      toast(t(okKey) + (sum ? ' · ' + sum : ''), opts);
      show('bunker');
    });
  }
  const saveBtn = keys => el('button', { class: 'btn primary', type: 'button',
    text: t('weekly.save'), onclick: () => saveFields(keys, 'weekly.saved') });

  // 一个字段 → 控件。清空数字框 = 删掉这个键（回到代码默认值），服务端支持。
  function bControl(f) {
    const k = f.key, kind = f.kind;
    const cur = el('span', { class: 'hint', text: isDurKey(k)
      ? t('bunker.nowIsDur', { v: bunkerVal(f, f.now), d: durText(f.now) })
      : t('bunker.nowIs', { v: bunkerVal(f, f.now) }) });
    if (kind === 'int' || kind === 'float') {
      // 车号给一个下拉提示（19 台车，带级别），并实时显示选中的是哪台车。
      if (k === 'matchmaking.bike_id') {
        const dl = el('datalist', { id: 'tfBikesBunker' });
        BIKES.forEach(b => dl.appendChild(el('option', { value: String(b.id) })));
        const tip = el('span', { class: 'hint' });
        const syncTip = () => {
          tip.textContent = bikeLabel(draft[k]) + ' · ' + t('app.tier.lv') + ' ' +
            tierText(bikeTierOf(draft[k]));
        };
        syncTip();
        return [numBox(draft[k], v => { set(k, v); syncTip(); },
                       { min: f.min, max: f.max, list: 'tfBikesBunker' }), dl, tip, cur];
      }
      const box = numBox(draft[k], v => set(k, v), { min: f.min, max: f.max });
      // 时长（排位 6 小时 / 好友局 1 小时）：常用值一键填，数字框本身随便填（60..2592000）。
      if (isDurKey(k)) {
        const presets = [[300, t('app.span.m', { m: 5 })], [1800, t('app.span.m', { m: 30 })],
                         [3600, t('app.span.h', { h: 1 })], [21600, t('bunker.reset6h')]];
        return presets.map(p => el('button', { class: 'btn tiny', type: 'button', text: p[1],
          onclick: () => { draft[k] = p[0]; box.value = String(p[0]); } })).concat([box, cur]);
      }
      return [box, cur];
    }
    if (kind === 'bool') {
      const on = el('button', { class: 'chip', type: 'button', text: t('bunker.on') });
      const off = el('button', { class: 'chip', type: 'button', text: t('bunker.off') });
      const sync = v => {
        on.setAttribute('aria-pressed', String(v === true));
        off.setAttribute('aria-pressed', String(v === false));
      };
      on.onclick = () => { set(k, true); sync(true); };
      off.onclick = () => { set(k, false); sync(false); };
      sync(draft[k] === true);
      return [on, off, cur];
    }
    if (kind === 'text') {
      const inp = el('input', { type: 'text', maxlength: String(f.max || 60),
                                value: draft[k] == null ? '' : String(draft[k]) });
      const bad = el('span', { class: 'hint p-warn', hidden: true, text: t('bunker.pipeWarn') });
      const sync = () => { bad.hidden = inp.value.indexOf('|') < 0; };
      inp.addEventListener('input', () => { set(k, inp.value); sync(); });
      sync();
      return [inp, bad];
    }
    if (kind === 'banner') {
      const inp = el('input', { type: 'text', maxlength: String(f.max || 80),
                                value: draft[k] == null ? '' : String(draft[k]) });
      const img = el('img', { class: 'bannerprev', alt: '', src: draft[k] || '', hidden: !draft[k] });
      inp.addEventListener('input', () => { set(k, inp.value); img.hidden = !inp.value; img.src = inp.value; });
      return [inp, el('span', { class: 'hint', text: t('bunker.banner.preview') }), img];
    }
    if (kind === 'stars') {
      const arr = (draft[k] || []).map(Number);
      const grid = el('div', { class: 'stargrid' });
      for (let i = 0; i < 25; i++) {
        grid.append(el('label', { class: 'starcell', title: t('bunker.stars.cell', { n: i + 1 }) },
          el('span', { class: 'hint', text: String(i + 1) }),
          el('input', { type: 'number', min: '0', max: '100',
            value: String(arr[i] == null ? 0 : arr[i]),
            oninput: e => { arr[i] = Number(e.target.value) || 0; set(k, arr.slice()); } })));
      }
      return [grid, el('span', { class: 'hint', text: t('bunker.stars.hint') })];
    }
    if (kind === 'ids') {
      const list = (draft[k] || []).map(Number);
      if (!ctx.tracks.length) {
        const inp = el('input', { type: 'text', value: list.join(', '), placeholder: '1041, 1042' });
        inp.addEventListener('input', () => set(k,
          inp.value.split(/[^0-9]+/).filter(Boolean).map(Number)));
        return [inp, el('span', { class: 'hint', text: t('bunker.track.empty') })];
      }
      const limit = k === 'matchmaking.track_ids' ? 3 : 999;
      const count = el('span', { class: 'hint' });
      const search = el('input', { type: 'search', class: 'filter',
                                   placeholder: t('bunker.track.search') });
      const box = el('div', { class: 'picklist' });
      const rows = [];
      const sync = () => {
        const own = new Set(list);
        rows.forEach(r => { r.box.checked = own.has(r.id); r.row.classList.toggle('on', own.has(r.id)); });
        count.textContent = t('bunker.track.chosen', { n: fmtNum(list.length) });
      };
      const toggle = id => {
        const i = list.indexOf(id);
        if (i >= 0) list.splice(i, 1);
        else if (list.length >= limit) {
          toast(t('bunker.track.max', { n: limit }), { kind: 'warn', timeout: 2600 });
          return;
        } else list.push(id);
        set(k, list.slice());
        sync();
      };
      for (const tr of ctx.tracks) {
        const tick = el('input', { type: 'checkbox', class: 'tick' });
        const nm = (LANG === 'cn' ? tr.name_cn : tr.name) || tr.name || '';
        const row = el('label', { class: 'prow', dataset: { q: (nm + ' ' + tr.id).toLowerCase() } },
          tick, el('span', { class: 'grow', text: nm || ('#' + tr.id) }),
          el('span', { class: 'hint mono', text: '#' + tr.id }));
        tick.onchange = () => toggle(Number(tr.id));
        rows.push({ id: Number(tr.id), box: tick, row });
        box.append(row);
      }
      search.addEventListener('input', () => {
        const q = search.value.trim().toLowerCase();
        rows.forEach(r => { r.row.hidden = !!q && r.row.dataset.q.indexOf(q) < 0; });
      });
      sync();
      return [el('div', { class: 'pick' },
        el('div', { class: 'pickhead' }, search, count), box)];
    }
    return [];   // rewards / products 由卡片自己画
  }

  // ── ① 现状：全只读。数字都由服务端实时算，界面不自己推。
  const nowCard = card => {
    const kv = el('div', { class: 'kv' },
      kvItem(t('bunker.now.season'), '#' + st.season),
      kvItem(t('bunker.now.display'), '#' + st.display_id),
      kvItem(t('bunker.now.duration'), t('app.days', { n: fmtNum(st.duration_days) })),
      kvItem(t('bunker.now.window'), fmtTime(st.start) + ' → ' + fmtTime(st.end)),
      kvItem(t('bunker.now.left'), spanText(st.end - st.now)),
      kvItem(t('bunker.now.players'), fmtNum((st.players || []).length)),
      kvItem(t('bunker.now.matches'), fmtNum(st.matches_total)),
      kvItem(t('bunker.now.queue'), fmtNum((st.queue || []).length)),
      kvItem(t('bunker.now.active'), fmtNum((st.active || []).length)),
      kvItem(t('bunker.now.tickets'), fmtNum(st.tickets_pool)),
      kvItem(t('bunker.now.chips'), fmtNum(st.chips_pool)));
    const pcols = [
      { label: t('weekly.col.profile'), render: r => idCell(r.profile) },
      { label: t('grant.pvpRank'), cls: 'r num', k: 'rank' },
      { label: t('grant.pvpStar'), cls: 'r num', k: 'star' },
      { label: t('grant.pvpSeason'), cls: 'r num', k: 'season' },
      { label: t('weekly.col.week'), render: r => el('span',
          { class: 'badge' + (r.this_season ? ' ok' : ''),
            text: r.this_season ? t('weekly.col.thisWeek') : t('weekly.col.oldWeek') }) },
      { label: t('grant.pvpGolden'), cls: 'r num', render: r => fmtNum(r.golden_ticket) },
      { label: t('grant.pvpStreak'), cls: 'r num', k: 'win_streak' },
      { label: t('grant.pvpChips'), cls: 'r num', render: r => fmtNum(r.chips) },
    ];
    const mcols = [
      { label: t('bunker.col.match'), render: r => el('span', { class: 'mono', text: String(r.id) }) },
      { label: t('bunker.col.players'), render: r => (r.players || []).join(', ') || '—' },
      { label: t('bunker.col.track'), cls: 'r num', render: r => '#' + r.track },
      { label: t('bunker.col.bot'), render: r => (r.bot ? t('app.yes') : t('app.no')) },
      { label: t('bunker.col.age'), cls: 'r', render: r => spanText(r.age) },
    ];
    const qrows = st.queue || [];
    const arows = st.active || [];
    const acols = [
      { label: t('weekly.col.profile'), render: r => idCell(r.profile) },
      { label: t('bunker.col.waited'), cls: 'r', render: r => spanText(r.waited) },
    ];
    const bcols = [
      { label: t('weekly.col.profile'), render: r => idCell(r.profile) },
      { label: t('bunker.col.seen'), cls: 'r', render: r => spanText(r.seen_ago) },
    ];
    const audit = data.audit || [];
    const acols2 = [
      { label: t('weekly.col.time'), k: 'at', render: r => fmtTime(r.at) },
      { label: t('weekly.col.param'), render: r => {
          const k = (r.path || []).slice(-1)[0];
          return (byKey[k] ? bText(byKey[k]) : String(k)) +
                 (r.kind === 'undo' ? ' · ' + t('weekly.kindUndo') : '');
        } },
      { label: t('weekly.col.change'), render: r => {
          const k = (r.path || []).slice(-1)[0];
          return (r.existed === false ? '—' : bunkerVal(byKey[k], r.before)) + ' → ' +
                 bunkerVal(byKey[k], r.after);
        } },
      { label: '', cls: 'act', render: r => el('button', { class: 'btn tiny', type: 'button',
          text: t('weekly.undoBtn'), onclick: () => guarded(async () => {
            await post('/__api/admin/undo', { id: r.id });
            toast(t('weekly.undone'), { kind: 'good', timeout: 2600 });
            show('bunker');
          }) }) },
    ];
    return wCardRaw(bText(card), null,
      el('div', { class: 'card-body' },
        kv,
        ...(st.warnings || []).map(w => el('p', { class: 'lead p-warn',
          text: (LANG === 'cn' ? w.cn : w.en) || w.cn || '' })),
        wSub('bunker.now.playersTitle',
          (st.players || []).length ? table(pcols, st.players)
            : el('div', { class: 'empty', text: t('bunker.now.noPlayers') })),
        wSub('bunker.now.matchesTitle',
          (st.matches || []).length ? table(mcols, st.matches)
            : el('div', { class: 'empty', text: t('bunker.now.noMatches') })),
        wSub('bunker.now.queueTitle',
          qrows.length ? table(acols, qrows) : el('div', { class: 'empty', text: t('bunker.now.noQueue') }),
          arows.length ? table(bcols, arows) : null),
        wSub('weekly.now.auditTitle',
          audit.length ? table(acols2, audit)
            : el('div', { class: 'empty', text: t('weekly.now.noAudit') }))));
  };

  // ── ⑦ 赛季奖励：名次表 + 礼包表（两张表分开保存，改动记录按张计）。
  const rewardsCard = card => {
    const rf = byKey['season.rewards'] || { key: 'season.rewards' };
    const pf = byKey['season.product_list'] || { key: 'season.product_list' };
    return wCardRaw(bText(card), null,
      el('p', { class: 'hint', text: bHint(rf) }),
      rewardsEditor(draft['season.rewards'], ctx.rewards, list => set('season.rewards', list)),
      cardFoot(saveBtn(['season.rewards'])),
      wSub('bunker.products.title',
        el('p', { class: 'hint', text: bHint(pf) }),
        productsEditor(draft['season.product_list'], list => set('season.product_list', list))),
      cardFoot(saveBtn(['season.product_list'])));
  };

  // ── ⑧ 模板：整页参数快照，跟午夜杯共用同一套端点（page=bunker）。
  const templatesCard = card => {
    const curKv = el('div', { class: 'kv' },
      fields.map(f => kvItem(bText(f), bunkerVal(f, values[f.key]))));
    const tplName = el('input', { type: 'text', maxlength: '40', value: '',
                                  placeholder: t('weekly.templates.nameHint') });
    async function tplPost(body, okKey) {
      return guarded(async () => {
        await post('/__api/admin/templates', body);
        toast(t(okKey), { kind: 'good', timeout: 2600 });
        show('bunker');
      });
    }
    const rows = (data.templates || []).map(tp => el('div', { class: 'tplrow' },
      el('div', { class: 'grow' },
        el('div', { class: 'tname', text: tp.name }),
        el('div', { class: 'hint', text: fmtTime(tp.saved_at) })),
      el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.applyAll'),
        onclick: () => guarded(async () => {
          const r = await post('/__api/admin/templates',
            { page: 'bunker', action: 'apply', name: tp.name, parts: 'all' });
          const applied = r.applied || [];
          const sum = applied.map(a => bText(byKey[a.key] || { key: a.key }) + ' → ' +
                                          bunkerVal(byKey[a.key], a.after)).join('　');
          const ids = applied.map(a => a.audit).filter(Boolean);
          const opts = { kind: 'good' };
          if (ids.length) opts.action = { label: t('weekly.undo'), run: () => guarded(async () => {
            for (const id of ids) await post('/__api/admin/undo', { id });
            show('bunker');
          }) };
          toast(t('weekly.templates.applied', { name: tp.name }) + (sum ? ' · ' + sum : ''), opts);
          show('bunker');
        }) }),
      el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.applyRewards'),
        onclick: () => guarded(async () => {
          const r = await post('/__api/admin/templates',
            { page: 'bunker', action: 'apply', name: tp.name, parts: 'rewards' });
          const v = (r.config || r.values || {});
          toast(t('weekly.templates.applied', { name: tp.name }) + ' · ' +
                bunkerVal(byKey['season.rewards'], v['season.rewards']),
                { kind: 'good', timeout: 4000 });
          show('bunker');
        }) }),
      el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.rename'),
        onclick: () => guarded(async () => {
          const to = await confirmDialog({ title: t('weekly.templates.rename'),
            okLabel: t('weekly.templates.rename'),
            input: { label: t('weekly.templates.name'), value: tp.name } });
          if (!to || String(to).trim() === tp.name) return;
          await tplPost({ page: 'bunker', action: 'rename', name: tp.name, new_name: String(to).trim() },
                        'weekly.templates.renamed');
        }) }),
      el('button', { class: 'btn tiny', type: 'button', text: t('weekly.templates.copy'),
        onclick: () => guarded(async () => {
          const to = await confirmDialog({ title: t('weekly.templates.copy'),
            okLabel: t('weekly.templates.copy'),
            input: { label: t('weekly.templates.name'),
                     value: tp.name + t('weekly.templates.copySuffix') } });
          if (!to || !String(to).trim()) return;
          await tplPost({ page: 'bunker', action: 'copy', name: tp.name, new_name: String(to).trim() },
                        'weekly.templates.copied');
        }) }),
      el('button', { class: 'btn tiny danger', type: 'button', text: t('weekly.templates.delete'),
        onclick: () => guarded(async () => {
          const yes = await confirmDialog({ title: t('weekly.templates.delete'),
            okLabel: t('weekly.templates.delete'),
            body: t('weekly.templates.deleteBody', { name: tp.name }) });
          if (!yes) return;
          await tplPost({ page: 'bunker', action: 'delete', name: tp.name }, 'weekly.templates.deleted');
        }) })));
    return wCardRaw(bText(card), null,
      wSub('weekly.templates.currentTitle',
        curKv,
        el('p', { class: 'hint', text: t('weekly.templates.currentHint') })),
      wSub('weekly.templates.saveTitle',
        fRow('weekly.templates.name', [tplName,
          el('button', { class: 'btn primary', type: 'button', text: t('weekly.templates.save'),
            onclick: () => guarded(async () => {
              const name = String(tplName.value || '').trim();
              if (!name) { toast(t('weekly.templates.needName'), { kind: 'warn', timeout: 2600 }); return; }
              await tplPost({ page: 'bunker', action: 'save', name }, 'weekly.templates.saved');
            }) })], t('weekly.templates.saveHint'))),
      wSub('weekly.templates.listTitle',
        rows.length ? el('div', null, ...rows)
                    : el('div', { class: 'empty', text: t('weekly.templates.none') })));
  };

  // 推进到下一赛季：advance +1 = 本届窗口整体往前挪一轮（不是多届历史，见服务端注释）。
  const advanceBtn = el('button', { class: 'btn danger', type: 'button', text: t('bunker.advance'),
    onclick: () => guarded(async () => {
      const yes = await confirmDialog({ title: t('bunker.advance'), body: t('bunker.advanceBody'),
                                        okLabel: t('bunker.advance') });
      if (!yes) return;
      const next = (Number(values['season.advance']) || 0) + 1;
      const r = await post('/__api/admin/bunker', { fields: { 'season.advance': next } });
      const id = ((r.applied || [])[0] || {}).audit;
      const opts = { kind: 'good' };
      if (id) opts.action = { label: t('weekly.undo'), run: () => guarded(async () => {
        await post('/__api/admin/undo', { id });
        show('bunker');
      }) };
      toast(t('bunker.advanceDone', { n: fmtNum((r.values || {})['season.advance'] || next) }), opts);
      show('bunker');
    }) });

  // ── 其余卡片：按服务端字段表生成（加参数只改服务端）。
  for (const card of (data.cards || [])) {
    if (card.id === 'now') { nodes.push(nowCard(card)); continue; }
    if (card.id === 'rewards') { nodes.push(rewardsCard(card)); continue; }
    if (card.id === 'templates') { nodes.push(templatesCard(card)); continue; }
    const fs = fields.filter(f => f.card === card.id);
    if (!fs.length) continue;
    const body = fs.map(f => fRowRaw(bText(f), bControl(f), bHint(f),
                                     f.kind === 'ids' || f.kind === 'stars'));
    if (card.id === 'season') body.push(fRowRaw(t('bunker.advance'), [advanceBtn], t('bunker.advanceHint')));
    body.push(cardFoot(saveBtn(fs.map(f => f.key))));
    nodes.push(wCardRaw(bText(card), null, ...body));
  }

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
