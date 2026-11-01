# m3u8 下载器

把网页上的 HLS（m3u8）视频下载到本地并合并成一个文件。

> 2021 年那版是 pygame 手搓的 GUI，靠「第 7 行、奇数行」猜格式，硬编码 Z:/mp4，
> 只能处理本地 m3u8 + 本地 key，遇到网络地址就抓瞎。2026 年按 HLS 规范重写了核心，
> 界面换成 Qt（窗口仍是原来的 800x600），旧脚本收进 legacy/ 留作存档。

## 三个入口

| 文件 | 用途 |
|---|---|
| m3u8_download.py | 命令行版，适合脚本 / 批量 |
| m3u8_gui.py | Qt 图形界面（PyQt5），双击或 pythonw 启动 |
| extension/ | **浏览器扩展**（Edge/Chrome 开发者模式加载）：播放页面时自动抓 m3u8，一键交给本地下载 |

## 浏览器扩展怎么用

1. 双击 `启动扩展后端.bat`（本地接收服务 127.0.0.1:18888，窗口保持开着）
2. Edge 打开 `edge://extensions/` → 打开「开发人员模式」→「加载解压缩的扩展」→ 选 extension 文件夹
3. 打开要下载的页面，**播放一下视频**；扩展图标上出现数字 = 抓到媒体
4. 点扩展图标 → 选一条点「下载」，或「全部交给下载器」；也可以网页右键菜单

扩展只做两件事：观察媒体请求、把地址 POST 给本地服务。**不注入网页、不读 cookie、没有远程脚本**，
下载/解密/合并全在本地 Python 里（AES-128、ffmpeg、断点续传）。

## 两种给法

1. **直接给 m3u8 地址**（或者本地 .m3u8 文件）—— 老办法，直接下。
2. **只给网页地址** —— 程序会用无头浏览器打开页面、自动等播放、抓出 m3u8 再下。
   文件名默认用**网页标题**（获取到什么就叫什么），也可以自己指定。

## 装依赖

    pip install requests

图形界面 + 网页自动解析：

    pip install -r requirements-gui.txt

> 自动解析用 **系统自带的 Edge**（playwright channel=msedge），**不用下载浏览器内核**。
> 没有 Edge 的话会自动回退到 playwright 自带内核（那时才需要 playwright install chromium）。

合并建议装 ffmpeg（可选，不装也能拼，但装了解密/封装更稳）：

- 把 ffmpeg.exe 放到脚本同目录，或加进 PATH
- 也可以用 --ffmpeg "D:\\tools\\ffmpeg.exe" 指定

> AES-128 解密是内置的纯 Python 实现，不需要装 cryptography / pycryptodome。

## 命令行用法

    # 网页地址：自动找 m3u8，名字用网页标题
    python m3u8_download.py "https://example.com/video/12345.html"

    # m3u8 直链：直接下
    python m3u8_download.py "https://example.com/video/index.m3u8"

    # 指定保存目录 / 缓存目录
    python m3u8_download.py "https://..." --save-dir "D:\\视频" --cache-dir "D:\\缓存"

    # 防盗链站点：带上 Referer / Cookie / UA
    python m3u8_download.py "https://..." --referer "https://example.com/" --cookie "token=abc; uid=123"

    # 页面要手动点播放：加一个点击选择器 + 多等一会
    python m3u8_download.py "https://..." --click ".my-play-btn" --wait 40

    # 页面卡住排查：把浏览器显示出来看
    python m3u8_download.py "https://..." --no-headless --wait 60

    # 加速 / 多试几次
    python m3u8_download.py "https://..." --workers 16 --retries 5

    # 只看解析结果，不下载
    python m3u8_download.py "https://..." --dry-run

    # 看 master playlist 有哪些清晰度
    python m3u8_download.py "https://..." --list-formats

    # 跑一下内置自检（验证 AES 实现没坏）
    python m3u8_download.py --selftest

### 全部参数

    -o, --output            输出文件名（默认自动：网页标题 / m3u8 名）
    --save-dir              保存目录（默认当前目录）
    --cache-dir             分片缓存目录（默认放保存目录下）
    --no-browser            网页地址不自动解析，只当 m3u8 用
    --browser               自动解析用哪个浏览器：msedge / chrome / chromium
    --no-headless           显示浏览器窗口（排查用）
    --wait                  最多等多少秒让页面出 m3u8（默认 25）
    --click                 额外要点击的 CSS 选择器，可重复
    --referer               Referer
    --cookie                Cookie
    --user-agent            User-Agent
    --header "K: V"         额外请求头，可重复
    --workers               并发数（默认 8）
    --retries               每个分片重试次数（默认 3）
    --timeout               请求超时秒数（默认 20）
    --bandwidth-index       master playlist 里选第几个变体（0=最高）
    --ffmpeg                ffmpeg 路径
    --keep-temp             保留下载的分片（便于排查 / 续传）
    --no-proxy              忽略系统代理
    --dry-run               只解析不下载
    --list-formats          列出清晰度
    --verbose               打印更多过程
    --selftest              跑 AES 自检

## 图形界面（Qt）

    python m3u8_gui.py          # 带控制台
    pythonw m3u8_gui.py         # 不带控制台（双击也行）

窗口 800x600（和原版一致）。主界面只有三行：

1. **地址**：网页地址或 m3u8 直链都行（网页会自动找 m3u8）
2. **保存名**：留空 = 自动用网页标题
3. **设置…**：保存目录 / 缓存目录 / 浏览器 / 等待时间 / 并发 / 重试 / ffmpeg

设置保存在系统里（QSettings），下次打开还记得。
「打开保存目录」直接跳到下载好的地方。

## 支持的 HLS 特性

- 网页自动解析：无头浏览器抓 m3u8（自动点播放按钮、滚动、等加载）
- 普通媒体清单 + master playlist（自动选最高码率）
- 相对路径 / 绝对路径 / 本地 file://
- AES-128 加密（EXT-X-KEY，自动下载密钥；没给 IV 时按媒体序列号推导）
- fMP4（EXT-X-MAP 初始化段）
- EXT-X-BYTERANGE 分片
- 断点续传（已有分片跳过，.part 临时文件原子替换）
- 失败重试（指数退避）+ 403 提示补 Referer/Cookie
- 有 ffmpeg 用无损 copy 合并，没有就二进制拼接
- 不支持 SAMPLE-AES（DRM），会明确报错

## 本地服务（--serve）

扩展需要它：

    python m3u8_download.py --serve 127.0.0.1:18888

接口：

    GET  /api/ping             健康检查 + 当前保存目录
    GET  /api/tasks            任务列表（状态 / 进度 / 输出路径）
    GET  /api/tasks/<id>       单个任务
    POST /api/download         {url, title?, referer?, cookie?} → {id}
    GET/POST /api/config       保存目录、缓存目录

只监听 127.0.0.1，只接受 `Origin: chrome-extension://…` 的请求，网页脚本扫到端口也塞不进任务。

## 常见问题

**网页打开了但没抓到 m3u8**

页面可能要登录 / 要手动点播放 / 懒加载很慢。依次试：

    --wait 60 --no-headless          # 看着浏览器，找它卡在哪
    --click ".play-button"           # 自己指播放按钮
    --cookie "你的登录 cookie"        # 需要登录的站

**下载 403 / 401**

站点做了防盗链。抓包看浏览器带了什么 Referer / Cookie，用 --referer / --cookie 补上。
（用网页自动解析时，浏览器里的 cookie 会自动带给下载器，一般不用手动补。）

**m3u8 是 master playlist，下成了低清晰度**

先 --list-formats 看变体顺序，再用 --bandwidth-index N 指定。

**只拿到 m3u8 文本、没有分片地址**

说明是直播流（没有 EXT-X-ENDLIST）—— 本工具面向点播，直播请用 ffmpeg 录制：
ffmpeg -i "https://.../index.m3u8" -c copy out.ts

**合并出来音画异常 / 无法播放**

装 ffmpeg 再跑一次；或加 --keep-temp 保留分片，手动：
ffmpeg -f concat -safe 0 -i out.mp4.parts/concat.txt -c copy out.mp4

**Qt 界面起不来**

先装 PyQt5：pip install -r requirements-gui.txt。没有图形界面也能用命令行版。

## 开发 / 测试

    python tests/test_m3u8.py      # 本地 file:// 清单 + AES 往返，不联网
    python m3u8_download.py --selftest
    python -m flake8 .             # 配置见 .flake8（legacy/ 不参与）

## 说明

仅用于下载你自己有权保存的内容（自己的作品、已授权的素材、公开课等）。
请遵守目标站点的服务条款和当地法律。

## legacy/

2021 年的四个脚本，原样保留、不保证能跑：

| 文件 | 当年用途 |
|---|---|
| legacy/m3u8.pyw | pygame 手搓 GUI（本项目的前身） |
| legacy/phncdn_m3u8_download.py | 某站的分片命名规则硬编码 |
| legacy/uu_m3u8_download.py | 本地 m3u8 + 本地 key |
| legacy/x.py | 从第一个 ts 地址反推分片地址 |
