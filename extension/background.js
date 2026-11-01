// 本地 m3u8 下载器助手 · background
// 只做两件事：观察媒体请求、把选中的地址 POST 给本地下载服务。
// 不注入网页脚本、不读 cookie、没有任何远程脚本。

const DEFAULTS = { server: 'http://127.0.0.1:18888' };

const MEDIA_RE = /\.(m3u8|mp4|m3u|m4v|mov|flv|webm|f4v|mp3|m4a|aac|ogg|wav|flac)(\?|#|$)/i;
const CT_RE = /(video\/|audio\/|mpegurl|vnd\.apple)/i;
const SKIP_RE = /^(blob:|data:|ws:|wss:)/i;
const SEGMENT_RE = /\.(ts|m4s)(\?|#|$)/i;   // 分片不记，交给 m3u8 去解析
const MAX_PER_TAB = 120;

let captures = null;   // { tabId: [ {url, kind, size, ct, ts} ] }

async function load() {
  if (captures) return captures;
  const d = await chrome.storage.session.get({ captures: {} });
  captures = d.captures || {};
  return captures;
}

async function save() {
  try { await chrome.storage.session.set({ captures }); } catch (e) { /* ignore */ }
}

function kindOf(url, ct) {
  const u = String(url || '').toLowerCase();
  if (u.indexOf('.m3u8') >= 0 || /mpegurl/i.test(ct)) return 'hls';
  if (/\.(mp4|m4v|mov|flv|webm|f4v)(\?|#|$)/.test(u) || /^video\//i.test(ct)) return 'video';
  if (/\.(mp3|m4a|aac|ogg|wav|flac)(\?|#|$)/.test(u) || /^audio\//i.test(ct)) return 'audio';
  return 'other';
}

function headerValue(headers, name) {
  if (!Array.isArray(headers)) return '';
  for (const h of headers) {
    if (String(h.name || '').toLowerCase() === name) return String(h.value || '');
  }
  return '';
}

async function touchBadge(tabId) {
  try {
    const list = (await load())[tabId] || [];
    const n = list.length;
    await chrome.action.setBadgeBackgroundColor({ tabId, color: '#2f6fed' });
    await chrome.action.setBadgeText({ tabId, text: n ? String(n) : '' });
  } catch (e) { /* ignore */ }
}

async function addCapture(tabId, url, ct, size) {
  if (tabId < 0 || !url || SKIP_RE.test(url)) return;
  if (SEGMENT_RE.test(url)) return;                       // ts/m4s 分片跳过
  const kind = kindOf(url, ct);
  if (kind === 'other' && !CT_RE.test(ct)) return;
  if (kind === 'other') return;

  const caps = await load();
  const list = caps[tabId] || (caps[tabId] = []);
  const i = list.findIndex(function (x) { return x.url === url; });
  const item = { url: url, kind: kind, size: size || 0, ct: ct || '', ts: Date.now() };
  if (i >= 0) {
    list[i] = item;
  } else {
    list.push(item);
    if (list.length > MAX_PER_TAB) list.shift();
  }
  await save();
  await touchBadge(tabId);
}

chrome.webRequest.onResponseStarted.addListener(
  function (d) {
    const ct = headerValue(d.responseHeaders, 'content-type');
    addCapture(d.tabId, d.url, ct, 0);
  },
  { urls: ['<all_urls>'] },
  ['responseHeaders']
);

chrome.webRequest.onHeadersReceived.addListener(
  function (d) {
    const ct = headerValue(d.responseHeaders, 'content-type');
    if (CT_RE.test(ct) || MEDIA_RE.test(d.url)) {
      const len = Number(headerValue(d.responseHeaders, 'content-length') || 0);
      addCapture(d.tabId, d.url, ct, len);
    }
  },
  { urls: ['<all_urls>'] },
  ['responseHeaders']
);

chrome.tabs.onRemoved.addListener(async function (tabId) {
  const caps = await load();
  if (caps[tabId]) { delete caps[tabId]; await save(); }
});

chrome.tabs.onUpdated.addListener(async function (tabId, info) {
  if (info.url) {
    const caps = await load();
    if (caps[tabId]) { delete caps[tabId]; await save(); await touchBadge(tabId); }
  }
});

async function getServer() {
  const d = await chrome.storage.sync.get({ server: DEFAULTS.server });
  return String(d.server || DEFAULTS.server).replace(/\/+$/, '');
}

async function sendAll(items, tab) {
  const server = await getServer();
  const results = [];
  for (const it of items) {
    try {
      const resp = await fetch(server + '/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: it.url,
          title: (tab && tab.title) || '',
          referer: (tab && tab.url) || ''
        })
      });
      results.push(await resp.json());
    } catch (e) {
      results.push({ ok: false, error: String(e) });
    }
  }
  return { ok: results.some(function (r) { return r.ok; }), results: results };
}

async function getTasks() {
  const server = await getServer();
  try {
    const resp = await fetch(server + '/api/tasks');
    return await resp.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

chrome.runtime.onInstalled.addListener(function () {
  chrome.contextMenus.create({
    id: 'send-tab',
    title: '把本页媒体全部交给本地下载器',
    contexts: ['page', 'video', 'audio']
  });
});

chrome.contextMenus.onClicked.addListener(async function (info, tab) {
  if (info.menuItemId !== 'send-tab') return;
  const caps = await load();
  const items = (caps[tab.id] || []).slice();
  if (!items.length) {
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon128.png',
      title: '本地 m3u8 下载器',
      message: '这个页面还没抓到媒体，先播放一下视频再试'
    });
    return;
  }
  const r = await sendAll(items, tab);
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icons/icon128.png',
    title: '已发送到本地下载器',
    message: r.ok ? ('共 ' + items.length + ' 个媒体，去看下载目录') : '本地服务没响应，先启动 启动扩展后端.bat'
  });
});

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  (async function () {
    if (msg.type === 'get') {
      const caps = await load();
      sendResponse({ ok: true, items: caps[msg.tabId] || [] });
    } else if (msg.type === 'clear') {
      const caps = await load();
      caps[msg.tabId] = [];
      await save();
      await touchBadge(msg.tabId);
      sendResponse({ ok: true });
    } else if (msg.type === 'download') {
      sendResponse(await sendAll(msg.items || [], msg.tab || null));
    } else if (msg.type === 'tasks') {
      sendResponse(await getTasks());
    } else if (msg.type === 'ping') {
      const server = await getServer();
      try {
        const resp = await fetch(server + '/api/ping');
        sendResponse(await resp.json());
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    }
  })();
  return true;
});