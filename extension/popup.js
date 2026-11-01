/* 本地 m3u8 下载器助手 · popup */

const KIND_LABEL = { hls: 'HLS', video: 'VID', audio: 'AUD', other: '???' };

function fmtSize(n) {
  n = Number(n) || 0;
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(n < 10 ? 1 : 0) + u[i];
}

function fileName(url) {
  try {
    const u = new URL(url);
    const base = decodeURIComponent(u.pathname.split('/').pop() || '');
    return base || u.hostname;
  } catch (e) {
    return url;
  }
}

async function currentTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0] ? tabs[0] : null;
}

function setStatus(text, cls) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.className = 'status' + (cls ? ' ' + cls : '');
}

async function ping() {
  const r = await chrome.runtime.sendMessage({ type: 'ping' });
  if (r && r.ok) {
    setStatus('本地服务已连接' + (r.save_dir ? ' · ' + r.save_dir : ''), 'ok');
    return true;
  }
  setStatus('本地服务没响应 —— 先双击「启动扩展后端.bat」', 'warn');
  return false;
}

function render(items) {
  const box = document.getElementById('list');
  box.textContent = '';
  document.getElementById('hint').textContent = items.length ? ('共 ' + items.length + ' 个') : '';
  if (!items.length) {
    const d = document.createElement('div');
    d.className = 'empty';
    d.textContent = '还没有抓到媒体 —— 先在页面上播放一下视频';
    box.appendChild(d);
    return;
  }
  const sorted = items.slice().sort(function (a, b) {
    const rank = { hls: 0, video: 1, audio: 2, other: 3 };
    return (rank[a.kind] || 9) - (rank[b.kind] || 9) || b.ts - a.ts;
  });
  for (const it of sorted) {
    const row = document.createElement('div');
    row.className = 'item';

    const badge = document.createElement('span');
    badge.className = 'badge ' + (it.kind || 'other');
    badge.textContent = KIND_LABEL[it.kind] || '???';
    row.appendChild(badge);

    const meta = document.createElement('div');
    meta.className = 'meta';
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = fileName(it.url);
    name.title = it.url;
    meta.appendChild(name);
    const sub = document.createElement('div');
    sub.className = 'sub';
    sub.textContent = [fmtSize(it.size), it.ct, it.url.slice(0, 60)].filter(Boolean).join(' · ');
    meta.appendChild(sub);
    row.appendChild(meta);

    const btn = document.createElement('button');
    btn.className = 'send';
    btn.textContent = '下载';
    btn.addEventListener('click', function () { sendItems([it], btn); });
    row.appendChild(btn);

    box.appendChild(row);
  }
}

let pollTimer = null;
let grabTimer = null;

async function fallbackLocal(hls, tabInfo) {
  const r2 = await chrome.runtime.sendMessage({ type: 'download', items: hls, tab: tabInfo });
  if (r2 && r2.ok) { setStatus('已改用本地下载器…'); startPolling(); }
  else { setStatus('本地下载也失败了', 'err'); }
}

function startGrabPolling(gid, hls, tabInfo) {
  if (grabTimer) clearInterval(grabTimer);
  grabTimer = setInterval(async function () {
    const r = await chrome.runtime.sendMessage({ type: 'grabstatus', gid: gid });
    const j = (r && r.job) || {};
    if (j.status === 'done') {
      clearInterval(grabTimer); grabTimer = null;
      setStatus('完成：' + (j.out || j.dir || ''), 'ok');
    } else if (j.status === 'failed') {
      clearInterval(grabTimer); grabTimer = null;
      setStatus('浏览器抓取失败（' + (j.error || '') + '），改用本地下载…', 'warn');
      fallbackLocal(hls, tabInfo);
    } else if (j.status === 'merging') {
      setStatus('分片抓完，正在合并…');
    } else {
      setStatus('浏览器抓取中 ' + (j.done || 0) + '/' + (j.total || '?'));
    }
  }, 700);
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async function () {
    const r = await chrome.runtime.sendMessage({ type: 'tasks' });
    if (!r || !r.ok || !r.tasks) return;
    const t = r.tasks[0];
    if (!t) return;
    if (t.status === 'done') {
      setStatus('完成：' + (t.out || ''), 'ok');
      clearInterval(pollTimer); pollTimer = null;
    } else if (t.status === 'failed') {
      setStatus('失败：' + (t.error || '') , 'err');
      clearInterval(pollTimer); pollTimer = null;
    } else {
      setStatus('下载中 ' + t.percent + '%  (' + t.done + '/' + t.total + ' 片)', '');
    }
  }, 800);
}

async function sendItems(items, btn) {
  const tab = await currentTab();
  const tabInfo = tab ? { title: tab.title, url: tab.url } : null;
  const hls = items.filter(function (it) { return it.kind === 'hls'; });
  const direct = items.filter(function (it) { return it.kind !== 'hls'; });

  if (btn) { btn.disabled = true; btn.textContent = '发送中…'; }

  let r = null;
  if (direct.length) {                       // mp4/mp3：浏览器自己下（带 cookie、能用缓存）
    r = await chrome.runtime.sendMessage({ type: 'browserdownload', items: direct, tab: tabInfo });
    if (r && r.ok) setStatus('已交给浏览器下载（可在下载列表看进度）', 'ok');
  }
  if (hls.length) {                          // m3u8：先让浏览器自己抓分片（带 cookie，过防盗链）
    const g = await chrome.runtime.sendMessage({
      type: 'grab', url: hls[0].url, title: tabInfo ? tabInfo.title : '', tabId: tab ? tab.id : -1
    });
    if (g && g.ok) {
      setStatus('浏览器开始抓取分片…');
      startGrabPolling(g.gid, hls, tabInfo);
      if (btn) { btn.disabled = false; btn.textContent = '下载'; }
      return;
    }
    const r2 = await chrome.runtime.sendMessage({ type: 'download', items: hls, tab: tabInfo });
    if (r2 && r2.ok) { r = r2; setStatus('已发送到本地下载器，开始下载…'); startPolling(); }
  }

  if (btn) { btn.disabled = false; btn.textContent = '下载'; }
  if (r && r.ok) {
    if (hls.length) startPolling();
  } else {
    const err = (r && r.results && r.results[0] && r.results[0].error) || (r && r.error) || '发送失败';
    setStatus('发送失败：' + err, 'err');
  }
}

async function refresh() {
  const tab = await currentTab();
  document.getElementById('pageTitle').textContent = tab ? (tab.title || tab.url || '') : '';
  if (!tab) { render([]); return; }
  const r = await chrome.runtime.sendMessage({ type: 'get', tabId: tab.id });
  render((r && r.items) || []);
  await ping();
}

document.addEventListener('DOMContentLoaded', function () {
  refresh();

  document.getElementById('btnAll').addEventListener('click', async function () {
    const tab = await currentTab();
    const r = await chrome.runtime.sendMessage({ type: 'get', tabId: tab.id });
    const items = (r && r.items) || [];
    if (!items.length) { setStatus('本页还没抓到东西', 'warn'); return; }
    await sendItems(items, null);
  });

  document.getElementById('btnClear').addEventListener('click', async function () {
    const tab = await currentTab();
    await chrome.runtime.sendMessage({ type: 'clear', tabId: tab.id });
    refresh();
  });

  document.getElementById('btnSettings').addEventListener('click', function () {
    chrome.runtime.openOptionsPage();
  });
});