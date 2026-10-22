> **存档说明（2026-10-22 补）**
>
> 这是 2021 年的代码快照，由 VS Code 的「Publish to GitHub」自动上传，**不是最终版本**，
> 已知存在若干缺陷（并发写入、硬编码路径、缺少错误处理等），不一定能直接跑起来。
>
> 当年的用途：把网页上的 m3u8 视频拉到本地 —— 解析播放列表、改写成本地清单，
> 再交给 ffmpeg 解密合并。纯自用工具，现在已不再维护，仅作存档。
>
> 唯一保留的价值：它是我的第一个"自己发明算法"的地方 —— 用 pygame 手搓 GUI，
> 用 gevent 并发下载，用字符串拼装改写 m3u8。回头看很粗糙，但当时能跑通。

# m3u8_download

## 文件说明

| 文件 | 用途 |
| --- | --- |
| `m3u8.pyw` | 主程序。pygame 绘制的图形界面（选文件 → 解析 → 下载 → 调用 ffmpeg 合并） |
| `phncdn_m3u8_download.py` | 针对某个站点（phncdn）的专用版本 |
| `uu_m3u8_download.py` | 另一站点的专用版本 |
| `x.py` | 早期试验脚本 |

## 依赖

```
pip install requests gevent pygame
```

还需要本机有 `ffmpeg`（合并 ts 片段）。

## 已知问题

- 全局变量满天飞，GUI 线程与下载线程共享 `get_list`，没有加锁
- 硬编码 `./ico_ttf_img/`、`./ts/` 等路径，换目录运行会崩
- 没有 `with open`，没有重试，HTTP 非 200 直接跳过，合并可能缺帧
- `url_list.index(url)` 在重复 URL 时会定位错位
