/* 本地 m3u8 下载器助手 · options */

const DEFAULTS = { server: 'http://127.0.0.1:18888' };

function msg(text, cls) {
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = cls || '';
}

async function getServer() {
  const d = await chrome.storage.sync.get({ server: DEFAULTS.server });
  return String(d.server || DEFAULTS.server).replace(/\/+$/, '');
}

async function loadConfig() {
  try {
    const r = await fetch((await getServer()) + '/api/config');
    const j = await r.json();
    if (j.ok) {
      document.getElementById('saveDir').value = j.save_dir || '';
      document.getElementById('cacheDir').value = j.cache_dir || '';
      if (j.ffmpeg && !document.getElementById('ffmpeg').value) {
        document.getElementById('ffmpeg').value = j.ffmpeg;
      }
    }
  } catch (e) {
    msg('连不上本地服务（先启动 启动扩展后端.bat）', 'err');
  }
}

document.addEventListener('DOMContentLoaded', async function () {
  document.getElementById('server').value = await getServer();
  await loadConfig();

  document.getElementById('save').addEventListener('click', async function () {
    const server = document.getElementById('server').value.trim().replace(/\/+$/, '') || DEFAULTS.server;
    await chrome.storage.sync.set({ server: server });
    try {
      const r = await fetch(server + '/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          save_dir: document.getElementById('saveDir').value.trim(),
          cache_dir: document.getElementById('cacheDir').value.trim(),
          ffmpeg: document.getElementById('ffmpeg').value.trim()
        })
      });
      const j = await r.json();
      if (j.ok) msg('已保存（服务端目录也更新了）', 'ok');
      else msg('服务端拒绝：' + (j.error || ''), 'err');
    } catch (e) {
      msg('设置存到扩展里了，但本地服务没连上：' + e, 'err');
    }
  });

  document.getElementById('test').addEventListener('click', async function () {
    const server = document.getElementById('server').value.trim().replace(/\/+$/, '') || DEFAULTS.server;
    try {
      const r = await fetch(server + '/api/ping');
      const j = await r.json();
      msg(j.ok ? ('连接成功：' + server + '  保存目录 ' + (j.save_dir || '(默认)')) : '服务返回异常', j.ok ? 'ok' : 'err');
    } catch (e) {
      msg('连不上：' + e, 'err');
    }
  });
});