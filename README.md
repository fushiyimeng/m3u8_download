# m3u8 下载器

把网页上的 HLS（m3u8）视频下载到本地并合并成一个文件。

> 2021 年那版是 pygame 手搓的 GUI，靠「第 7 行、奇数行」猜格式，硬编码 Z:/mp4，
> 只能处理本地 m3u8 + 本地 key，遇到网络地址就抓瞎。2026 年按 HLS 规范重写了核心，
> 界面换成 Qt（窗口仍是原来的 800x600），旧脚本收进 legacy/ 留作存档。

## 两个入口

| 文件 | 用途 |
|---|---|
| m3u8_download.py | 命令行版，适合脚本 / 批量 |
| m3u8_gui.py | Qt 图形界面（PyQt5），双击或 pythonw 启动 |

## 装依赖

    pip install requests

图形界面还需要 Qt 绑定（只装一次）：

    pip install -r requirements-gui.txt

合并建议装 ffmpeg（可选，不装也能拼，但装了解密/封装更稳）：

- 把 ffmpeg.exe 放到脚本同目录，或加进 PATH
- 也可以用 --ffmpeg "D:\\tools\\ffmpeg.exe" 指定

> AES-128 解密是内置的纯 Python 实现，不需要装 cryptography / pycryptodome。

## 命令行用法

    # 最简单：给个地址，自动挑最高码率、自动合并
    python m3u8_download.py "https://example.com/video/index.m3u8"

    # 指定输出文件
    python m3u8_download.py "https://example.com/video/index.m3u8" -o "D:\\视频\\第01集.mp4"

    # 防盗链站点：带上 Referer / Cookie / UA
    python m3u8_download.py "https://..." --referer "https://example.com/" --cookie "token=abc; uid=123"

    # 加速 / 多试几次
    python m3u8_download.py "https://..." --workers 16 --retries 5

    # 只看解析结果，不下载
    python m3u8_download.py "https://..." --dry-run

    # 看 master playlist 有哪些清晰度
    python m3u8_download.py "https://..." --list-formats

    # 下载第 2 个变体（0 = 最高码率）
    python m3u8_download.py "https://..." --bandwidth-index 1

    # 跑一下内置自检（验证 AES 实现没坏）
    python m3u8_download.py --selftest

### 全部参数

    -o, --output            输出文件（默认按 m3u8 名字生成 .mp4）
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

窗口大小保持原版 pygame 界面的 800x600。用法：

1. 粘贴 m3u8 地址（或点「本地文件…」选一个）
2. 选保存位置（不填就自动放在当前目录）
3. 需要防盗链的站点，填 Referer / Cookie
4. 点「开始下载」，进度条和日志会实时更新

界面只负责收集参数，真正干活的是命令行版（QProcess 子进程），所以两边行为完全一致；
按「停止」会保留已下载的分片，下次重跑接着下。

## 支持的 HLS 特性

- 普通媒体清单 + master playlist（自动选最高码率）
- 相对路径 / 绝对路径 / 本地 file://
- AES-128 加密（EXT-X-KEY，自动下载密钥；没给 IV 时按媒体序列号推导）
- fMP4（EXT-X-MAP 初始化段）
- EXT-X-BYTERANGE 分片
- 断点续传（已有分片跳过，.part 临时文件原子替换）
- 失败重试（指数退避）+ 403 提示补 Referer/Cookie
- 有 ffmpeg 用无损 copy 合并，没有就二进制拼接
- 不支持 SAMPLE-AES（DRM），会明确报错

## 常见问题

**下载 403 / 401**

站点做了防盗链。抓包看浏览器带了什么 Referer / Cookie，用 --referer / --cookie 补上。

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
