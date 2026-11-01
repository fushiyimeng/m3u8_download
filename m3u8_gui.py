#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m3u8 下载器 · Qt 图形界面（PyQt5）

界面只收集参数，真正下载由 m3u8_download.py 完成（QProcess 子进程），
所以 GUI 和命令行行为完全一致，下载器崩了也不会带崩界面。

启动：
    python m3u8_gui.py          # 带控制台
    pythonw m3u8_gui.py         # 不带控制台（双击 .py 关联也行）
"""
from __future__ import annotations

import os
import re
import sys

from PyQt5.QtCore import QProcess, Qt, QProcessEnvironment
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "m3u8_download.py")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def default_out(url: str) -> str:
    """根据地址猜一个输出文件名（和命令行版规则一致）。"""
    name = url.rstrip("/").split("/")[-1] or "video.m3u8"
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    stem, _ = os.path.splitext(name)
    return os.path.splitext(os.path.abspath(CORE))[0] and os.path.join(os.getcwd(), (stem or "video") + ".mp4")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.proc: QProcess | None = None
        self.buf = ""
        self.setWindowTitle("m3u8 下载器 · Qt")
        # 和 2021 年那版 pygame 窗口保持一致：800x600
        self.setFixedSize(800, 600)
        self.build_ui()

    # ── 界面 ──────────────────────────────────────────────
    @staticmethod
    def _field_label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setMinimumWidth(78)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lab

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # 地址
        row = QHBoxLayout()
        row.addWidget(self._field_label("m3u8 地址："))
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://example.com/video/index.m3u8  （也可以选本地文件）")
        row.addWidget(self.url, 1)
        btn_local = QPushButton("本地文件…")
        btn_local.clicked.connect(self.pick_local)
        row.addWidget(btn_local)
        root.addLayout(row)

        # 保存位置
        row = QHBoxLayout()
        row.addWidget(self._field_label("保存为："))
        self.out = QLineEdit()
        self.out.setPlaceholderText("留空 = 自动放在当前目录")
        row.addWidget(self.out, 1)
        btn_out = QPushButton("浏览…")
        btn_out.clicked.connect(self.pick_out)
        row.addWidget(btn_out)
        root.addLayout(row)

        # 高级参数
        box = QGroupBox("可选（防盗链站点才需要）")
        form = QFormLayout(box)
        self.referer = QLineEdit()
        self.referer.setPlaceholderText("https://example.com/")
        form.addRow("Referer", self.referer)
        self.cookie = QLineEdit()
        self.cookie.setPlaceholderText("token=abc; uid=123")
        form.addRow("Cookie", self.cookie)
        self.ua = QLineEdit()
        self.ua.setPlaceholderText("留空用默认浏览器 UA")
        form.addRow("User-Agent", self.ua)

        row = QHBoxLayout()
        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        self.workers.setValue(8)
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(3)
        self.ffmpeg = QLineEdit()
        self.ffmpeg.setPlaceholderText("留空自动找 PATH / 同目录")
        row.addWidget(QLabel("并发"))
        row.addWidget(self.workers)
        row.addSpacing(12)
        row.addWidget(QLabel("重试"))
        row.addWidget(self.retries)
        row.addSpacing(12)
        row.addWidget(QLabel("ffmpeg"))
        row.addWidget(self.ffmpeg, 1)
        form.addRow(row)
        root.addWidget(box)

        # 按钮
        row = QHBoxLayout()
        self.btn_go = QPushButton("开始下载")
        self.btn_go.setDefault(True)
        self.btn_go.clicked.connect(self.start)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        btn_open = QPushButton("打开保存目录")
        btn_open.clicked.connect(self.reveal)
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color:#555")
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_stop)
        row.addWidget(btn_open)
        row.addSpacing(12)
        row.addWidget(self.status, 1)
        root.addLayout(row)

        # 进度
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        root.addWidget(self.bar)

        # 日志
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumBlockCount(5000)
        root.addWidget(self.log, 1)

    # ── 交互 ──────────────────────────────────────────────
    def pick_local(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择本地 m3u8", "",
                                              "m3u8 播放列表 (*.m3u8);;所有文件 (*.*)")
        if path:
            self.url.setText(path)
            if not self.out.text().strip():
                self.out.setText(os.path.splitext(path)[0] + ".mp4")

    def pick_out(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存为", self.out.text() or "",
                                              "MP4 视频 (*.mp4);;所有文件 (*.*)")
        if path:
            self.out.setText(path)

    def reveal(self):
        target = self.out.text().strip()
        d = os.path.dirname(os.path.abspath(target)) if target else os.getcwd()
        if os.path.isdir(d):
            if hasattr(os, "startfile"):
                os.startfile(d)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", d])

    def write(self, text: str):
        self.log.appendPlainText(text)
        m = PCT_RE.search(text)
        if m and "/" in text:
            try:
                self.bar.setValue(int(float(m.group(1))))
                self.status.setText(f"下载中… {float(m.group(1)):.1f}%")
            except ValueError:
                pass

    # ── 运行 ──────────────────────────────────────────────
    def build_command(self) -> list[str]:
        url = self.url.text().strip()
        cmd = [sys.executable, CORE, url]
        if self.out.text().strip():
            cmd += ["-o", self.out.text().strip()]
        if self.referer.text().strip():
            cmd += ["--referer", self.referer.text().strip()]
        if self.cookie.text().strip():
            cmd += ["--cookie", self.cookie.text().strip()]
        if self.ua.text().strip():
            cmd += ["--user-agent", self.ua.text().strip()]
        cmd += ["--workers", str(self.workers.value()), "--retries", str(self.retries.value())]
        if self.ffmpeg.text().strip():
            cmd += ["--ffmpeg", self.ffmpeg.text().strip()]
        return cmd

    def start(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.warning(self, "缺少地址", "先填一个 m3u8 地址，或点「本地文件…」选一个")
            return
        cmd = self.build_command()
        self.log.clear()
        self.write("$ " + " ".join(cmd))
        self.bar.setValue(0)
        self.status.setText("启动中…")
        self.btn_go.setEnabled(False)
        self.btn_stop.setEnabled(True)

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self.on_output)
        self.proc.finished.connect(self.on_finished)
        self.proc.errorOccurred.connect(self.on_error)
        self.buf = ""
        self.proc.start(cmd[0], cmd[1:])

    def on_output(self):
        if not self.proc:
            return
        raw = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self.buf += raw
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self.write(line)

    def on_error(self, err):
        if err == QProcess.FailedToStart:
            self.write("启动失败：找不到 Python？")
            self.reset(False)

    def on_finished(self, code: int, _status):
        if self.buf.strip():
            self.write(self.buf.strip())
            self.buf = ""
        self.reset(code == 0)
        if code == 0:
            self.bar.setValue(100)
            self.status.setText("完成")
            self.write("\n✔ 完成")
        else:
            self.status.setText(f"失败（退出码 {code}）")
            self.write(f"\n✘ 退出码 {code}，看上面的报错")

    def stop(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.terminate()
            self.write("\n已请求停止（已下载的分片会保留，下次接着下）")

    def reset(self, ok: bool):
        self.btn_go.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if ok:
            self.proc = None


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("m3u8 下载器")
    w = MainWindow()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
