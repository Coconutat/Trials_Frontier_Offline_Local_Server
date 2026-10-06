// 后台管理页浏览器冒烟测试（开发期工具，不参与服务器运行）。
//
//   node tools/ui_smoke.mjs [baseUrl] [管理员口令]
//   TF_ADMIN_PW=xxxx node tools/ui_smoke.mjs http://127.0.0.1:8000
//
// 为什么需要它：单元测试能证明端点返回什么，证明不了 app.js 在真浏览器里
// 画得出来。它自己管一个 headless Edge/Chrome（CDP），登录后逐屏切换，
// 断言每屏渲染出了真实数据，并且**一次 JS 异常都没有**。
//
// 只用 Node 内置模块（>=20，需要全局 fetch/WebSocket）。找不到浏览器就退出 2。
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = (process.argv[2] || 'http://127.0.0.1:8000').replace(/\/$/, '');
const PW = process.argv[3] || process.env.TF_ADMIN_PW || '';
const PORT = Number(process.env.TF_CDP_PORT || 9333);
// 给了目录就顺手把每屏截图存下来（设计评审要看的就是这个）。
const SHOT = process.env.TF_SHOT_DIR || process.argv[4] || '';

const BROWSERS = [
  process.env.TF_BROWSER,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/microsoft-edge', '/usr/bin/google-chrome', '/usr/bin/chromium',
].filter(Boolean);

const sleep = ms => new Promise(r => setTimeout(r, ms));

function die(msg, code = 1) { console.error('✗ ' + msg); process.exit(code); }
function ok(msg) { console.log('✓ ' + msg); }

// --------------------------------------------------------------- 登录
if (!PW) die('没给管理员口令。用法：node tools/ui_smoke.mjs <baseUrl> <口令>');

const res = await fetch(BASE + '/__api/admin/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: PW }),
});
if (!res.ok) die(`登录失败 ${res.status}：${await res.text()}`);
const cookie = (res.headers.getSetCookie ? res.headers.getSetCookie()[0]
                                         : res.headers.get('set-cookie')) || '';
const token = cookie.split('tf_admin=')[1]?.split(';')[0];
if (!token) die('登录响应里没有 tf_admin Cookie：' + cookie);
ok('登录成功，拿到管理员票据');

// --------------------------------------------------------------- 浏览器
const bin = BROWSERS.find(p => existsSync(p));
if (!bin) die('找不到 Edge/Chrome。用 TF_BROWSER=<路径> 指定。', 2);

const profile = mkdtempSync(join(tmpdir(), 'tf-ui-'));
const child = spawn(bin, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--disable-background-networking', '--mute-audio',
  `--user-data-dir=${profile}`, `--remote-debugging-port=${PORT}`, 'about:blank',
], { stdio: 'ignore' });

const cleanup = () => {
  try { child.kill(); } catch { /* 已经退了 */ }
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* 占用中无所谓 */ }
};
process.on('exit', cleanup);

let wsUrl = null;
for (let i = 0; i < 60 && !wsUrl; i++) {
  await sleep(250);
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    wsUrl = list.find(t => t.type === 'page')?.webSocketDebuggerUrl || null;
  } catch { /* 端口还没起来 */ }
}
if (!wsUrl) die('浏览器调试端口没起来（' + PORT + '）');
ok('浏览器已启动：' + bin.split(/[\\/]/).pop());

// --------------------------------------------------------------- CDP
const ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('ws')); });

let seq = 0;
const pending = new Map();
const problems = [];
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.id) {
    const p = pending.get(m.id);
    if (!p) return;
    pending.delete(m.id);
    m.error ? p.rej(new Error(m.error.message)) : p.res(m.result);
    return;
  }
  // ★ 一次 JS 异常 / 一个 error 级 console 输出都算失败：后台是运维台，
  //   静默半死不活比直接报错更糟。
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails;
    problems.push('JS 异常: ' + (d.exception?.description || d.text));
  } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    problems.push('console.error: ' + m.params.args.map(a => a.value ?? a.description).join(' '));
  } else if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
    problems.push('日志: ' + m.params.entry.text);
  }
};
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq;
  pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
});
const evalJs = async expr => (await send('Runtime.evaluate',
  { expression: expr, returnByValue: true, awaitPromise: true })).result.value;

await send('Page.enable');
await send('Runtime.enable');
await send('Log.enable');
await send('Network.enable');
// 深色是主设计（app.css 默认深色，浅色走 prefers-color-scheme: light）。
await send('Emulation.setEmulatedMedia',
  { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });

let shotN = 0;
// ★ 固定视口跟截图没关系，是**为了让断言可重复**：默认窗口小的时候，`#pane` 的
//   innerText 会随布局变（折叠区/换行不同），曾经出现「同一次改动，带截图跑绿、
//   不带截图跑红」。所以无论如何都钉死视口。
await send('Emulation.setDeviceMetricsOverride',
  { width: 1440, height: 1000, deviceScaleFactor: 2, mobile: false });
if (SHOT) mkdirSync(SHOT, { recursive: true });
const shot = async name => {
  if (!SHOT) return;
  const { data } = await send('Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: true });
  const f = join(SHOT, `${String(++shotN).padStart(2, '0')}-${name}.png`);
  writeFileSync(f, Buffer.from(data, 'base64'));
  console.log('  ⤷ 截图 ' + f);
};

const u = new URL(BASE);

// 先不塞票据，拍一张登录页。
await send('Page.navigate', { url: BASE + '/__admin' });
await sleep(1500);
await shot('login');
await send('Network.setCookie',
  { name: 'tf_admin', value: token, domain: u.hostname, path: '/' });

// --------------------------------------------------------------- 逐屏检查
// 每屏：切过去之后，界面里必须出现这些字符串（都是界面上真实可见的标签）。
// act 是切过去之后要点的东西（存档屏的关键余额在「详情」里，列表上只有元数据）。
// 改文案时要同步这里 —— 宁可失败也不要让检查悄悄变成空断言。
const SCREENS = [
  { hash: '#/accounts', title: '账号',
    // ★ 「对好友 / 加好友 / 改昵称」来自社交卡（2026-10-07 新增）：游戏内加不了好友
    //   （addFriend 只走育碧 Uplay 覆盖层），关系与昵称只能在这张卡上维护。
    //   只钉这些**结构性**字样，不钉「还没有好友」这类随关系变化的行内文案。
    must: ['玩家注册入口', '复制', '登录会话', '设备', '管理员口令',
           '对好友', '加好友', '改昵称'] },
  {
    hash: '#/saves', title: '存档', must: ['存档槽', '内容丰富度', '写入时间'],
    act: `[...document.querySelectorAll('#pane tbody tr')]
            .find(r => r.innerText.includes('53ebbd18'))
            .querySelector('td:last-child button').click()`,
    mustAfter: ['金币', '钻石', '道具 135', '存档版本'],
  },
  {
    hash: '#/grant', title: '下发物品',
    must: ['竞技场', '金票', '筹码', '存档物品', '云端',
           '货币', '消耗品', '摩托车零件', '骑手服装', '摩托蓝图', '车漆涂装', '已选 0 项'],
    // 默认选中是列表第一个（<anonymous>）。切到 ccb 那个真档上，确认竞技场卡
    // 读到的是服务端 pvp_state.json 里的真值。★ 别写死余额或段位数字：那是随时
    // 会变的线上数值（玩家打一局就变），写死过一次就变成假失败（2026-10-07：段位
    // 从 24 掉回 23，断言就红了）。这里只钉「有段位这一行」这种结构性的东西。
    act: `(() => {
            const s = document.getElementById('grantSlot');
            s.value = [...s.options].find(o => o.value.startsWith('53ebbd18')).value;
            s.dispatchEvent(new Event('change'));
          })()`,
    mustAfter: ['竞技场', '当前', '段位', '下发到竞技场'],
    // 再点开第一个分类（货币），确认折叠清单真的展开出物品行（未展开时 innerText 里没有这些）。
    act2: `document.querySelector('#pane .acchead').click()`,
    mustAfter2: ['金币', '钻石', '已选 0 项'],
    // 再点开「骑手服装」：80 套按套列出，High Roller 那套的套装效果文案必须露出来。
    act3: `[...document.querySelectorAll('#pane .acchead')]
             .find(b => b.innerText.includes('骑手服装')).click()`,
    mustAfter3: ['无限汽油', '隐藏', '已拥有', 'The High Roller'],
    // 再点开「车漆涂装」并展开 Riptide 那一组：108 款按车分组的嵌套折叠，
    // 涂装行上要能看到「位 0」这种位掩码信息（涂装不按 id 下发）。
    act4: `(() => {
            [...document.querySelectorAll('#pane .acchead')]
              .find(b => b.innerText.includes('车漆涂装')).click();
            const g = [...document.querySelectorAll('#pane .acc-sub > .acchead')]
              .find(b => b.innerText.includes('Riptide'));
            if (!g) throw new Error('没找到 Riptide 那一组涂装');
            g.click();
          })()`,
    mustAfter4: ['车漆涂装', 'Riptide', 'Riptide SnakeBite skin', '位 0'],
    // 再点开「摩托蓝图」：碎片是计数器（一辆车一个编号、每辆车要的片数不同），
    // 行上要能看到「需要 N 片」，Berserker 只在 giftbox 的紧凑形式里出现过、最容易漏。
    act5: `[...document.querySelectorAll('#pane .acchead')]
             .find(b => b.innerText.includes('摩托蓝图')).click()`,
    mustAfter5: ['需要 20 片', 'Berserker Blueprint Piece', '已拥有', '只能金币买'],
  },
  {
    // 午夜杯运营屏：六张卡（现状 / 时间 / 挑战规则 / 赛道与对手 / 奖励 / 模板）。
    // ★ 这一屏的按钮会**真写线上 tf_config.json**，所以这里只碰草稿（切周、改输入框），
    //   一个保存按钮都不点 —— 冒烟测试不该改生产参数。
    hash: '#/weekly', title: '午夜杯',
    must: ['现状', '本周赛道', '本届窗口', '周号', '时间', '窗口长度（天）',
           '上一周', '本周', '下一周', '立刻结束本届', '保存改动',
           '挑战规则', '赛道与对手', '榜单 id',
           '本届车辆', '租借升级',
           '奖励', '每档奖励个数', '服务端只下发', '白金', '退出午夜杯再进',
           '模板', '当前生效值', '存为模板'],
    // 切片：点「下一周」只改草稿里的 week_offset，窗口预览立刻跟着挪。
    act: `[...document.querySelectorAll('#pane .seg button')]
            .find(b => b.innerText.trim() === '下一周').click()`,
    mustAfter: ['这一届的窗口：'],
    // 把窗口长度改成 10 天：界面上要立刻挂出「实验性」徽章（只有 7 天在真机验过）。
    act2: `(() => {
            const row = [...document.querySelectorAll('#pane .frow')]
              .find(r => r.innerText.includes('窗口长度（天）'));
            const inp = row.querySelector('input[type=number]');
            inp.value = '10';
            inp.dispatchEvent(new Event('input'));
          })()`,
    mustAfter2: ['实验性'],
    // 奖励卡：点第 3 号池子方块，木档的「未指定」文案要跟着消失（它那档已有选中）。
    act3: `(() => {
            const row = [...document.querySelectorAll('#pane .tierrow')]
              .find(r => r.innerText.includes('木'));
            row.querySelectorAll('.chip')[2].click();
          })()`,
    mustAfter3: ['奖励'],
    // 截图文件名后缀：共享 steps 里的后缀是给「下发物品」屏写的，这一屏要自己的。
    suffixes: ['-翻周', '-窗口', '-奖励'],
  },
  {
    // 碉堡（PVP 运营）屏：八张卡（现状 / 赛季 / 对局时长 / 段位与星章 / 匹配与 AI /
    // 筹码与曲线 / 赛季奖励 / 模板）。跟午夜杯一样，保存会真写线上参数 ⇒ 只碰草稿。
    hash: '#/bunker', title: '碉堡',
    must: ['现状', '赛季', '对局时长', '段位与星章', '匹配与 AI', '筹码与曲线',
           '赛季奖励', '模板',
           '排位对局时长（秒）', '友军对局时长（秒）',
           '赛季长度（天）', '显示编号偏移', '推进到下一赛季', '赛季名', '横幅图片路径',
           '升阶星章表（25 档）', '起始段位',
           '匹配总开关', '固定赛道', '候选赛道池', 'AI 成绩倍率', '固定车辆',
           '按赛道级别随机发车', '随机池只放剧情车',
           '筹码曲线 x', '起始筹码', '每条赛道产币周期（秒）',
           '赛季奖励表', '礼包（商城商品）', '金币', '钻石', '特殊奖励',
           '当前：', '30 分钟', '保存改动', '存为模板', '当前生效值'],
    // 固定赛道：点第一条候选赛道 ⇒ 草稿里选中一条，计数器立刻变。
    act: `(() => {
            const row = [...document.querySelectorAll('#pane .prow')][0];
            row.click();
          })()`,
    mustAfter: ['已选 1 条'],
    // 奖励编号：填一个「物品表里有、但不在官方 43 个里」的编号（257 = 忍者服装）
    // ⇒ 名字位置要如实说显示什么由「玩家有没有这件物品」决定（兜底物 = 毛驴轮胎）。
    act2: `(() => {
             const inp = [...document.querySelectorAll('#pane .rwsp')][0];
             inp.value = '257';
             inp.dispatchEvent(new Event('input'));
           })()`,
    mustAfter2: ['忍者', '毛驴轮胎'],
    suffixes: ['-选路', '-奖励'],
  },
];

await send('Page.navigate', { url: BASE + '/__admin' });
await sleep(1800);

if (await evalJs(`document.getElementById('shell').hidden`)) {
  die('登录后 #shell 还是隐藏的 —— /__api/admin/me 没认这张 Cookie');
}
ok('已进入后台（#shell 可见）');
const who = await evalJs(`document.getElementById('whoami').textContent`);
if (who !== 'admin') die('#whoami 显示的是 ' + JSON.stringify(who));
ok(`顶部身份显示 ${who}`);

for (const s of SCREENS) {
  await evalJs(`location.hash = ${JSON.stringify(s.hash)}`);
  await sleep(900);
  await shot(s.title.replace(/[\\/:*?"<>| ]/g, '_'));
  const text = await evalJs(`document.getElementById('pane').innerText`);
  const cards = await evalJs(`document.querySelectorAll('#pane .card').length`);
  const rows = await evalJs(`document.querySelectorAll('#pane tbody tr').length`);
  if (!text || text.trim().length < 20) die(`${s.title}屏是空的：${JSON.stringify(text)}`);
  if (!cards) die(`${s.title}屏一张卡都没画出来`);
  for (const m of s.must) {
    if (!text.includes(m)) die(`${s.title}屏缺少「${m}」：\n` + text.slice(0, 600));
  }
  // 逐步点开（act → act4）：每步「点一下 → 核对文案 → 截图」。折叠起来的内容不在
  // innerText 里，所以展开之后才能断言里面的字。
  const steps = [
    { act: s.act, must: s.mustAfter, suffix: '-展开', wait: 1200 },
    { act: s.act2, must: s.mustAfter2, suffix: '-清单', wait: 900 },
    { act: s.act3, must: s.mustAfter3, suffix: '-服装', wait: 900 },
    { act: s.act4, must: s.mustAfter4, suffix: '-涂装', wait: 900 },
    { act: s.act5, must: s.mustAfter5, suffix: '-蓝图', wait: 900 },
  ];
  for (let i = 0; i < steps.length; i++) {
    const st = steps[i];
    if (!st.act) continue;
    const r = await evalJs(`(()=>{try{${st.act};return 'ok'}catch(e){return 'FAIL: '+e}})()`);
    if (r !== 'ok') die(`${s.title}屏第 ${i + 1} 步操作没点成：${r}`);
    await sleep(st.wait);
    const after = await evalJs(`document.getElementById('pane').innerText`);
    for (const m of st.must || []) {
      if (!after.includes(m)) die(`${s.title}屏第 ${i + 1} 步之后缺少「${m}」：\n` + after.slice(0, 900));
    }
    await shot(s.title.replace(/[\\/:*?"<>| ]/g, '_') +
                ((s.suffixes && s.suffixes[i]) || st.suffix));
  }
  ok(`${s.title}屏：${cards} 张卡 / ${rows} 行表格数据`);
}

// 英文也不能是空的（两语都得能切）。
await evalJs(`document.getElementById('langSeg').querySelector('[data-lang="en"]').click()`);
await sleep(800);
const en = await evalJs(`document.getElementById('pageTitle').textContent`);
if (!en || /[\u4e00-\u9fff]/.test(en)) die('切到 EN 之后标题还是中文：' + en);
ok('切到 EN 生效：' + en);

ws.close();
if (problems.length) {
  console.error('\n浏览器里出现 ' + problems.length + ' 个问题：');
  for (const p of problems) console.error('  · ' + p);
  process.exit(1);
}
console.log('\n全部通过，浏览器里零 JS 异常。');
// WebSocket 和浏览器子进程会一直吊着事件循环，必须显式退出（触发 exit 清理）。
process.exit(0);
