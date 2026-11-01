#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m3u8 下载器 · 图形界面（tkinter，标准库自带）

和命令行版共用同一套核心逻辑：界面只负责收集参数，真正干活的是
m3u8_download.py（用子进程跑，出问题不影响界面）。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "m3u8_download.py")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.last_out = None
        root.title("m3u8 下载器")
        root.geometry("820x560")
        root.minsize(720, 480)

        pad = {"padx": 10, "pady": 5}
        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True, **pad)

        # 地址
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="m3u8 地址：", width=11).pack(side="left")
        self.url = ttk.Entry(row)
        self.url.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="本地文件…", width=10,
                   command=self.pick_local).pack(side="left", padx=(6, 0))

        # 输出
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="保存为：", width=11).pack(side="left")
        self.out = ttk.Entry(row)
        self.out.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", width=8,
                   command=self.pick_out).pack(side="left", padx=(6, 0))

        # 高级参数
        opt = ttk.LabelFrame(frm, text="可选（防盗链站点才需要）")
        opt.pack(fill="x", pady=(0, 6))
        r1 = ttk.Frame(opt)
        r1.pack(fill="x", padx=6, pady=4)
        ttk.Label(r1, text="Referer", width=8).pack(side="left")
        self.referer = ttk.Entry(r1)
        self.referer.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(r1, text="Cookie", width=7).pack(side="left")
        self.cookie = ttk.Entry(r1)
        self.cookie.pack(side="left", fill="x", expand=True)

        r2 = ttk.Frame(opt)
        r2.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(r2, text="并发", width=4).pack(side="left")
        self.workers = ttk.Spinbox(r2, from_=1, to=32, width=5)
        self.workers.set("8")
        self.workers.pack(side="left", padx=(0, 12))
        ttk.Label(r2, text="重试", width=4).pack(side="left")
        self.retries = ttk.Spinbox(r2, from_=0, to=10, width=5)
        self.retries.set("3")
        self.retries.pack(side="left", padx=(0, 12))
        ttk.Label(r2, text="ffmpeg（留空自动找）", width=20).pack(side="left")
        self.ffmpeg = ttk.Entry(r2)
        self.ffmpeg.pack(side="left", fill="x", expand=True)

        # 按钮
        btn = ttk.Frame(frm)
        btn.pack(fill="x", pady=(0, 6))
        self.go = ttk.Button(btn, text="开始下载", command=self.start)
        self.go.pack(side="left")
        self.stop = ttk.Button(btn, text="停止", command=self.stop, state="disabled")
        self.stop.pack(side="left", padx=(8, 0))
        self.open_dir = ttk.Button(btn, text="打开保存目录", command=self.reveal)
        self.open_dir.pack(side="left", padx=(8, 0))
        self.status = ttk.Label(btn, text="就绪")
        self.status.pack(side="left", padx=12)

        # 进度
        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.bar.pack(fill="x", pady=(0, 6))

        # 日志
        self.log = tk.Text(frm, height=16, wrap="none", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(self.log, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set, state="disabled")

        self.root.after(100, self.drain)

    # ---------- 选择文件 ----------
    def pick_local(self):
        p = filedialog.askopenfilename(
            title="选择本地 m3u8",
            filetypes=[("m3u8 播放列表", "*.m3u8"), ("所有文件", "*.*")])
        if p:
            self.url.delete(0, "end")
            self.url.insert(0, p)
            if not self.out.get().strip():
                self.out.insert(0, os.path.splitext(p)[0] + ".mp4")

    def pick_out(self):
        p = filedialog.asksaveasfilename(
            title="保存为", defaultextension=".mp4",
            filetypes=[("MP4 视频", "*.mp4"), ("所有文件", "*.*")])
        if p:
            self.out.delete(0, "end")
            self.out.insert(0, p)

    def reveal(self):
        out = self.last_out or self.out.get().strip()
        d = os.path.dirname(os.path.abspath(out)) if out else HERE
        if os.path.isdir(d):
            os.startfile(d)  # type: ignore[attr-defined]

    # ---------- 日志 ----------
    def write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    self.write(payload)
                    self.parse_progress(payload)
                elif kind == "done":
                    self.finish(payload)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def parse_progress(self, line: str):
        # 形如 "[██░░] 42.0%  21/50  1.2MB  2.3MB/s"
        if "%" in line and "/" in line:
            try:
                pct = line.split("%")[0].split()[-1]
                self.bar["value"] = float(pct)
                self.status.config(text=f"下载中… {float(pct):.1f}%")
            except Exception:
                pass

    # ---------- 运行 ----------
    def start(self):
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("缺少地址", "先填一个 m3u8 地址，或选本地文件")
            return
        out = self.out.get().strip()
        cmd = [sys.executable, CORE, url]
        if out:
            cmd += ["-o", out]
        if self.referer.get().strip():
            cmd += ["--referer", self.referer.get().strip()]
        if self.cookie.get().strip():
            cmd += ["--cookie", self.cookie.get().strip()]
        if self.workers.get().strip():
            cmd += ["--workers", self.workers.get().strip()]
        if self.retries.get().strip():
            cmd += ["--retries", self.retries.get().strip()]
        if self.ffmpeg.get().strip():
            cmd += ["--ffmpeg", self.ffmpeg.get().strip()]

        self.last_out = out or None
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.write("$ " + " ".join(cmd) + "\n")
        self.go.configure(state="disabled")
        self.stop.configure(state="normal")
        self.bar["value"] = 0
        self.status.config(text="启动中…")

        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("启动失败", str(e))
            self.reset()
            return
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self.q.put(("line", line.rstrip("\n")))
        code = proc.wait()
        self.q.put(("done", code))

    def finish(self, code: int):
        self.reset()
        if code == 0:
            self.bar["value"] = 100
            self.status.config(text="完成")
            self.write("\n✔ 完成")
        else:
            self.status.config(text=f"失败（退出码 {code}）")
            self.write(f"\n✘ 退出码 {code}，看上面的报错")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.write("\n已请求停止（已下载的分片会保留，下次接着下）")

    def reset(self):
        self.go.configure(state="normal")
        self.stop.configure(state="disabled")


def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
