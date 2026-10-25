"""实时观战页：一个 HTML 字符串，由服务端直接吐出来。

为什么不用前端框架？
    这个页面的全部工作是"连 WebSocket、追加几行字"，用 React/Vite 要引入构建链，
    对 demo 来说是负收益。等页面复杂到需要状态管理时再换，现在用原生 JS 最快。
    （这也是判断"什么时候该上框架"的一个标准：等你觉得手写 DOM 痛苦的时候。）
"""

from __future__ import annotations

LIVE_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Liar's Table · 实时观战</title>
<style>
:root { --bg:#0f1115; --card:#171a21; --line:#262b36; --text:#d7dae0;
        --muted:#8b93a1; --good:#4ea1ff; --wolf:#ff6b6b; --accent:#ffc857; }
* { box-sizing: border-box; }
body { margin:0; padding:28px 20px 80px; background:var(--bg); color:var(--text);
       font:14px/1.7 "Segoe UI","Microsoft YaHei",system-ui,sans-serif; }
.wrap { max-width: 860px; margin: 0 auto; }
h1 { font-size:20px; margin:0 0 2px; }
.sub { color:var(--muted); font-size:13px; }
.bar { display:flex; align-items:center; gap:12px; margin:18px 0; }
.dot { width:8px; height:8px; border-radius:50%; background:var(--accent);
       box-shadow:0 0 0 4px rgba(255,200,87,.15); }
.dot.done { background:#3ba55d; box-shadow:0 0 0 4px rgba(59,165,93,.15); }
.btn { background:#222835; color:var(--text); border:1px solid var(--line);
       padding:7px 14px; border-radius:8px; cursor:pointer; font-size:13px; }
.btn:hover { background:#2b3242; }
.timeline { background:var(--card); border:1px solid var(--line);
            border-radius:10px; padding:6px 0; min-height:120px; }
.line { display:flex; gap:12px; padding:6px 16px; animation:fade .18s ease-out; }
@keyframes fade { from { opacity:0; transform:translateY(3px); } to { opacity:1; } }
.line .seq { color:#4a5160; min-width:32px; font-variant-numeric:tabular-nums; }
.night { color:var(--wolf); font-weight:600; }
.dawn { color:var(--accent); font-weight:600; }
.speech { color:#dbe4f5; }
.ended { color:#3ba55d; font-weight:600; }
.empty { color:var(--muted); padding:14px 16px; }
.result { margin-top:18px; background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:16px; display:none; }
.result.show { display:block; }
.result h2 { margin:0 0 6px; font-size:16px; }
table { width:100%; border-collapse:collapse; margin-top:10px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); font-size:13px; }
th { color:var(--muted); font-weight:600; font-size:12px; }
.wolf { color:var(--wolf); }
.good { color:var(--good); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Liar's Table · 实时观战</h1>
  <div class="sub">seed <span id="seed">-</span> · 事件 <span id="count">0</span></div>

  <div class="bar">
    <span class="dot" id="dot"></span>
    <span id="status">准备中</span>
    <button class="btn" id="new">新开一局</button>
  </div>

  <div class="timeline" id="timeline">
    <div class="empty" id="empty">正在开局…</div>
  </div>

  <div class="result" id="result">
    <h2 id="result-title"></h2>
    <div id="result-reason" class="sub"></div>
    <table id="result-table"></table>
  </div>
</div>

<script>window.__BOOT__ = __BOOT_DATA__;</script>
<script>
const el = (id) => document.getElementById(id);
let lastSeq = -1;
let socket = null;

function setStatus(text, done) {
  el('status').textContent = text;
  el('dot').classList.toggle('done', !!done);
}

function reset() {
  el('timeline').innerHTML = '';
  el('result').classList.remove('show');
  el('count').textContent = '0';
  lastSeq = -1;
}

function append(seq, kind, text) {
  if (lastSeq < 0) el('timeline').innerHTML = '';
  const row = document.createElement('div');
  row.className = 'line ' + kind;
  row.innerHTML = '<span class="seq"></span><span class="body"></span>';
  row.querySelector('.seq').textContent = seq;
  row.querySelector('.body').textContent = text;
  el('timeline').appendChild(row);
  el('count').textContent = String(seq + 1);
  row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function showResult(msg) {
  const winner = msg.winner === 'wolf' ? '狼人阵营获胜' : '好人阵营获胜';
  el('result-title').textContent = winner;
  el('result-reason').textContent = msg.reason || '';
  const head = '<tr><th>座位</th><th>身份</th><th>结局</th></tr>';
  const rows = (msg.players || []).map(p => {
    const camp = p.role === '狼人' ? 'wolf' : 'good';
    return `<tr><td>${p.seat}</td><td class="${camp}">${p.role}</td>` +
           `<td>${p.survived ? '存活' : '出局'}</td></tr>`;
  }).join('');
  el('result-table').innerHTML = head + rows;
  el('result').classList.add('show');
  setStatus('已结束', true);
}

function connect(id) {
  if (socket) socket.close();
  socket = new WebSocket(`ws://${location.host}/ws/${id}`);

  socket.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.kind === 'result') { showResult(msg); return; }
    if (msg.seq <= lastSeq) return;      // 断线重连去重
    lastSeq = msg.seq;
    if (!msg.text) return;               // 私有事件不在公开频道展示
    append(msg.seq, msg.kind, msg.text);
  };

  socket.onopen = () => setStatus('对局进行中');
  socket.onclose = () => {
    if (el('status').textContent !== '已结束') setStatus('连接断开', true);
  };
}

async function newGame() {
  reset();
  setStatus('开局中…');
  const response = await fetch('/api/games', { method: 'POST' });
  const data = await response.json();
  el('seed').textContent = data.seed;
  connect(data.id);
}

el('new').addEventListener('click', newGame);

async function attach(id) {
  const response = await fetch(`/api/games/${id}`);
  if (!response.ok) { setStatus('对局不存在', true); return; }
  const data = await response.json();
  el('seed').textContent = data.seed;
  connect(id);
}

// 首屏优先用服务端注入的数据：即使 WebSocket 还没连上，也能立刻看到已有事件。
const presetId = new URLSearchParams(location.search).get('id');
const boot = window.__BOOT__ || {};

if (boot.seed !== null && boot.seed !== undefined) {
  el('seed').textContent = boot.seed;
  el('timeline').innerHTML = '';          // 清掉"正在开局…"占位
  (boot.payloads || []).forEach((p) => {
    if (!p.text) return;
    lastSeq = p.seq;
    append(p.seq, p.kind, p.text);
  });
  if (boot.result) {
    showResult(boot.result);
  } else if (presetId) {
    connect(presetId);
  }
} else if (presetId) {
  attach(presetId);
} else {
  newGame();
}
</script>
</body>
</html>
"""
