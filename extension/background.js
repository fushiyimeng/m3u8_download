// 本地 m3u8 下载器助手 · background
// 只做两件事：观察媒体请求、把选中的地址 POST 给本地下载服务。
// 不注入网页脚本、不读 cookie、没有任何远程脚本。

const DEFAULTS = { server: 'http://127.0.0.1:18888' };

const MEDIA_RE = /\.(m3u8|mp4|m3u|m4v|mov|flv|webm|f4v|mp3|m4a|aac|ogg|wav|flac)(\?|#|$)/i;
const CT_RE = /(video\/|audio\/|mpegurl|vnd\.apple)/i;
const SKIP_RE = /^(blob:|data:|ws:|wss:)/i;
const SEGMENT_RE = /\.(ts|m4s)(\?|#|$)/i;   // 分片不记，交给 m3u8 去解析
const MAX_PER_TAB = 120;

let captures = null;   // { tabId: [ {url, kind, size, ct, ts, headers} ] }
let reqHeaders = {};   // url -> { Cookie, Referer, Origin, 'User-Agent' }（防盗链站点必需）

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
  if (reqHeaders[url]) item.headers = reqHeaders[url];
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

// 观察请求头：把浏览器真正发出去的 Cookie/Referer/Origin/UA 记下来，
// 发任务时一起交给本地下载器（否则防盗链站点会把 Python 的请求直接 RST）
chrome.webRequest.onBeforeSendHeaders.addListener(
  function (d) {
    if (d.tabId < 0 || !d.url) return;
    const h = {};
    for (const x of (d.requestHeaders || [])) {
      const k = String(x.name || '').toLowerCase();
      if (k === 'cookie') h.Cookie = String(x.value || '');
      else if (k === 'referer') h.Referer = String(x.value || '');
      else if (k === 'origin') h.Origin = String(x.value || '');
      else if (k === 'user-agent') h['User-Agent'] = String(x.value || '');
    }
    if (Object.keys(h).length) {
      reqHeaders[d.url] = h;
      const keys = Object.keys(reqHeaders);
      if (keys.length > 500) { for (const old of keys.slice(0, 100)) delete reqHeaders[old]; }
    }
  },
  { urls: ['<all_urls>'] },
  ['requestHeaders']
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
          referer: (tab && tab.url) || '',
          headers: it.headers || reqHeaders[it.url] || {}
        })
      });
      results.push(await resp.json());
    } catch (e) {
      results.push({ ok: false, error: String(e) });
    }
  }
  return { ok: results.some(function (r) { return r.ok; }), results: results };
}

// 单文件（mp4/mp3…）：直接交给浏览器下载，走它自己的 cookie 和缓存，不经过本地服务
async function browserDownload(items, tab) {
  const results = [];
  for (const it of items) {
    try {
      let name = '';
      try {
        name = decodeURIComponent(new URL(it.url).pathname.split('/').pop() || '');
      } catch (e) { name = ''; }
      const t = (tab && tab.title) ? tab.title.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80) : '';
      const ext = name.indexOf('.') >= 0 ? name.slice(name.lastIndexOf('.')) : '';
      const id = await chrome.downloads.download({
        url: it.url,
        filename: (t || 'download') + ext,
        conflictAction: 'uniquify',
        saveAs: false
      });
      results.push({ ok: true, id: id });
    } catch (e) {
      results.push({ ok: false, error: String(e) });
    }
  }
  return { ok: results.some(function (r) { return r.ok; }), results: results };
}

// ── 浏览器自己下分片（带 cookie/Referer，过防盗链；本地只负责合并）──
let grabJobs = {};

function absUrl(u, base) {
  try { return new URL(u, base).href; } catch (e) { return u; }
}

async function fetchPlaylistText(url) {
  const r = await fetch(url, { credentials: 'include', cache: 'no-store' });
  if (!r.ok) throw new Error('m3u8 HTTP ' + r.status);
  return await r.text();
}

async function resolveSegments(url, depth) {
  depth = depth || 0;
  const text = await fetchPlaylistText(url);
  const lines = text.split(/\r?\n/);

  // master playlist：挑带宽最大的子清单
  let bw = 0;
  const variants = [];
  for (const ln of lines) {
    const s = ln.trim();
    if (s.startsWith('#EXT-X-STREAM-INF:')) {
      const m = /BANDWIDTH=(\d+)/i.exec(s);
      bw = m ? Number(m[1]) : 1;
    } else if (s && s.charAt(0) !== '#' && bw > 0) {
      variants.push({ url: absUrl(s, url), bw: bw });
      bw = 0;
    }
  }
  if (variants.length && depth < 3) {
    variants.sort(function (a, b) { return b.bw - a.bw; });
    return await resolveSegments(variants[0].url, depth + 1);
  }

  if (text.indexOf('#EXT-X-KEY') >= 0 && text.indexOf('METHOD=NONE') < 0) {
    throw new Error('这条流是加密的（AES-128），浏览器抓取模式暂不支持，请用本地下载模式');
  }
  const segs = [];
  for (const ln of lines) {
    const s = ln.trim();
    if (!s || s.charAt(0) === '#') continue;
    segs.push(absUrl(s, url));
  }
  if (!segs.length) throw new Error('m3u8 里没找到分片');
  return segs;
}

function downloadOne(url, filename) {
  return new Promise(function (resolve, reject) {
    chrome.downloads.download({
      url: url, filename: filename, conflictAction: 'overwrite', saveAs: false
    }, function (id) {
      if (chrome.runtime.lastError || !id) {
        return reject(new Error((chrome.runtime.lastError && chrome.runtime.lastError.message) || 'download 调用失败'));
      }
      // 用轮询而不是只靠 onChanged：本地文件下载极快，事件可能在监听前就结束了
      let settled = false;
      const finish = function (ok, val) {
        if (settled) return;
        settled = true;
        if (ok) resolve(val); else reject(val);
      };
      const check = function () {
        chrome.downloads.search({ id: id }, function (items) {
          const it = items && items[0];
          if (!it) {
            return finish(false, new Error('下载记录消失了'));
          }
          if (it.state === 'complete') return finish(true, it);
          if (it.state === 'interrupted') return finish(false, new Error('下载中断：' + (it.error || '')));
          if (!settled) setTimeout(check, 120);
        });
      };
      setTimeout(check, 80);
    });
  });
}

function startGrab(m3u8Url, title, tabId) {
  const gid = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  grabJobs[gid] = { gid: gid, title: title || '', status: 'preparing', done: 0, total: 0,
                    dir: '', out: '', error: '' };
  runGrab(gid, m3u8Url, title).catch(function (e) {
    const j = grabJobs[gid] || {};
    j.status = 'failed';
    j.error = String(e && e.message ? e.message : e);
  });
  return gid;
}

async function finishGrab(gid, title) {
  const job = grabJobs[gid];
  job.status = 'merging';
  const server = await getServer();
  const resp = await fetch(server + '/api/grab/' + gid + '/finish', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
  });
  const j = await resp.json();
  if (j.ok) {
    job.status = 'done';
    job.out = j.out || '';
    job.error = j.note || '';
  } else {
    job.status = 'failed';
    job.error = j.error || '合并失败';
  }
}

async function runGrab(gid, m3u8Url, title) {
  const job = grabJobs[gid];
  try {
    const segs = await resolveSegments(m3u8Url, 0);
    job.total = segs.length;
    job.status = 'downloading';
    const server = await getServer();

    // 路线 1：在页面/扩展里 fetch 分片，流式 POST 给本地（同源或 CDN 允许跨域时最快）
    try {
      const created = await fetch(server + '/api/grab/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: gid, title: title || '', total: segs.length })
      });
      const cj = await created.json();
      if (!cj.ok) throw new Error('建任务失败：' + (cj.error || ''));
      for (let i = 0; i < segs.length; i++) {
        const r = await fetch(segs[i], { credentials: 'include' });
        if (!r.ok) throw new Error('分片 HTTP ' + r.status);
        const buf = await r.arrayBuffer();
        const up = await fetch(server + '/api/grab/' + gid + '/chunk?seq=' + i, {
          method: 'POST', body: buf
        });
        if (!up.ok) throw new Error('上传失败 ' + up.status);
        job.done = i + 1;
      }
      await finishGrab(gid, title);
      return;
    } catch (e) {
      job.lastError = 'fetch 方式不可用（' + String(e && e.message ? e.message : e) + '），改用浏览器下载';
      job.done = 0;
    }

    // 路线 2：让浏览器自己下载分片（chrome.downloads，带 cookie、不受 CORS 限制）
    const prefix = 'm3u8grab/' + gid + '/';
    let next = 0, running = 0, firstFile = '';
    await new Promise(function (resolve) {
      function pump() {
        while (running < 8 && next < segs.length) {
          const idx = next++;
          running++;
          const filename = prefix + String(idx).padStart(6, '0') + '.ts';
          downloadOne(segs[idx], filename).then(function (item) {
            if (item && item.filename) firstFile = item.filename;
            job.done++;
            running--;
            if (next >= segs.length && running === 0) resolve();
            else pump();
          }).catch(function (err) {
            job.done++;
            job.lastError = String(err && err.message ? err.message : err);
            running--;
            if (next >= segs.length && running === 0) resolve();
            else pump();
          });
        }
        if (next >= segs.length && running === 0) resolve();
      }
      pump();
    });

    if (!firstFile) throw new Error('浏览器下载也没拿到分片：' + (job.lastError || ''));
    job.dir = firstFile.replace(/[\\/][^\\/]+$/, '');
    job.status = 'merging';
    const resp = await fetch(server + '/api/grab/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dir: job.dir, title: title || '' })
    });
    const j = await resp.json();
    if (j.ok) {
      job.status = 'done';
      job.out = j.out || '';
    } else {
      job.status = 'failed';
      job.error = j.error || '合并失败';
    }
  } catch (e) {
    job.status = 'failed';
    job.error = String(e && e.message ? e.message : e);
  }
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
    } else if (msg.type === 'browserdownload') {
      sendResponse(await browserDownload(msg.items || [], msg.tab || null));
    } else if (msg.type === 'grab') {
      sendResponse({ ok: true, gid: startGrab(msg.url, msg.title, msg.tabId) });
    } else if (msg.type === 'grabstatus') {
      const j = grabJobs[msg.gid] || {};
      sendResponse({ ok: true, job: j });
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