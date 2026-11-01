#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m3u8 下载器 · Qt 图形界面（PyQt5）

- 地址可以填网页（自动用无头浏览器找 m3u8），也可以填 m3u8 直链、本地文件
- 保存目录 / 缓存目录 / 浏览器 / 等待时间 都在「设置」里选，记在注册表里（QSettings）
- 文件名默认用网页标题（获取到什么就用什么），也可以在「保存名」里自己改
- 真正干活的是 m3u8_download.py（QProcess 子进程），所以 GUI 和命令行行为一致
"""
from __future__ import annotations

import os
import re
import sys

from PyQt5.QtCore import QProcess, QProcessEnvironment, QSettings, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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


def default_save_dir() -> str:
    for cand in (os.path.join(os.path.expanduser("~"), "Downloads"),
                 os.path.join(os.path.expanduser("~"), "下载")):
        if os.path.isdir(cand):
            return cand
    return HERE


class Settings:
    """简单封装 QSettings：保存目录、缓存目录、浏览器等。"""

    def __init__(self):
        self.s = QSettings("fushiyimeng", "m3u8-downloader")

    def get(self, key: str, default):
        v = self.s.value(key, default)
        if isinstance(default, bool):
            if isinstance(v, bool):
                return v
            return str(v).lower() in ("true", "1", "yes")
        if isinstance(default, int):
            try:
                return int(v)
            except (TypeError, ValueError):
                return default
        if isinstance(default, float):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
        return str(v) if v is not None else default

    def set(self, key: str, value):
        self.s.setValue(key, value)

    @property
    def save_dir(self) -> str:
        d = self.get("save_dir", "")
        return d if d and os.path.isdir(d) else default_save_dir()

    @save_dir.setter
    def save_dir(self, v: str):
        self.set("save_dir", v)

    @property
    def cache_dir(self) -> str:
        return self.get("cache_dir", "")

    @cache_dir.setter
    def cache_dir(self, v: str):
        self.set("cache_dir", v)


class SettingsDialog(QDialog):
    def __init__(self, st: Settings, parent=None):
        super().__init__(parent)
        self.st = st
        self.setWindowTitle("设置")
        self.setMinimumWidth(580)
        form = QFormLayout(self)

        row = QHBoxLayout()
        self.save_dir = QLineEdit(st.save_dir)
        row.addWidget(self.save_dir, 1)
        b = QPushButton("浏览…")
        b.clicked.connect(lambda: self.pick_dir(self.save_dir))
        row.addWidget(b)
        form.addRow("保存目录", self._wrap(row))

        row = QHBoxLayout()
        self.cache_dir = QLineEdit(st.cache_dir)
        self.cache_dir.setPlaceholderText("留空 = 放在保存目录下的「视频名.parts」")
        row.addWidget(self.cache_dir, 1)
        b = QPushButton("浏览…")
        b.clicked.connect(lambda: self.pick_dir(self.cache_dir))
        row.addWidget(b)
        form.addRow("缓存目录", self._wrap(row))

        self.browser = QLineEdit(st.get("browser", "msedge"))
        self.browser.setPlaceholderText("msedge / chrome / chromium（用系统自带的，不用下内核）")
        form.addRow("浏览器", self.browser)

        self.show_browser = QCheckBox("显示浏览器窗口（默认无头；勾上会弹出来，排查页面卡住处用）")
        self.show_browser.setChecked(st.get("show_browser", False))
        form.addRow("", self.show_browser)

        self.wait = QSpinBox()
        self.wait.setRange(5, 180)
        self.wait.setSuffix(" 秒")
        self.wait.setValue(st.get("wait", 25))
        form.addRow("等页面出 m3u8", self.wait)

        row = QHBoxLayout()
        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        self.workers.setValue(st.get("workers", 8))
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(st.get("retries", 3))
        row.addWidget(QLabel("并发"))
        row.addWidget(self.workers)
        row.addSpacing(14)
        row.addWidget(QLabel("重试"))
        row.addWidget(self.retries)
        row.addStretch(1)
        form.addRow("下载", self._wrap(row))

        row2 = QHBoxLayout()
        self.ffmpeg = QLineEdit(st.get("ffmpeg", ""))
        self.ffmpeg.setPlaceholderText("留空自动找 PATH / 同目录")
        row2.addWidget(self.ffmpeg, 1)
        bb = QPushButton("浏览…")
        bb.clicked.connect(self.pick_ffmpeg)
        row2.addWidget(bb)
        form.addRow("ffmpeg", self._wrap(row2))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return w

    def pick_dir(self, target: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "选择目录", target.text() or os.path.expanduser("~"))
        if d:
            target.setText(d)

    def pick_ffmpeg(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 ffmpeg", "", "ffmpeg (ffmpeg.exe);;所有文件 (*.*)")
        if p:
            self.ffmpeg.setText(p)

    def save(self):
        self.st.save_dir = self.save_dir.text().strip()
        self.st.cache_dir = self.cache_dir.text().strip()
        self.st.set("browser", self.browser.text().strip() or "msedge")
        self.st.set("show_browser", self.show_browser.isChecked())
        self.st.set("wait", self.wait.value())
        self.st.set("workers", self.workers.value())
        self.st.set("retries", self.retries.value())
        self.st.set("ffmpeg", self.ffmpeg.text().strip())


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.st = Settings()
        self.proc: QProcess | None = None
        self.buf = ""
        self.setWindowTitle("m3u8 下载器 · Qt")
        self.setFixedSize(800, 600)      # 和原来 pygame 版一致
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

        row = QHBoxLayout()
        row.addWidget(self._field_label("地址："))
        self.url = QLineEdit()
        self.url.setPlaceholderText("网页地址或 m3u8 直链都行 —— 网页会自动用浏览器找 m3u8")
        row.addWidget(self.url, 1)
        btn_local = QPushButton("本地文件…")
        btn_local.clicked.connect(self.pick_local)
        row.addWidget(btn_local)
        root.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._field_label("保存名："))
        self.name = QLineEdit()
        self.name.setPlaceholderText("留空 = 自动用网页标题")
        row.addWidget(self.name, 1)
        btn_set = QPushButton("设置…")
        btn_set.clicked.connect(self.open_settings)
        row.addWidget(btn_set)
        root.addLayout(row)

        self.hint = QLabel()
        self.hint.setStyleSheet("color:#666;font-size:12px")
        root.addWidget(self.hint)
        self.refresh_hint()

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

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        root.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumBlockCount(5000)
        root.addWidget(self.log, 1)

    def refresh_hint(self):
        cache = self.st.cache_dir or "（同上目录下的 .parts）"
        self.hint.setText(f"保存到：{self.st.save_dir}    缓存：{cache}")

    def open_settings(self):
        dlg = SettingsDialog(self.st, self)
        if dlg.exec_() == QDialog.Accepted:
            dlg.save()
            self.refresh_hint()
            self.write("设置已保存")

    # ── 交互 ──────────────────────────────────────────────
    def pick_local(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择本地 m3u8", "",
                                              "m3u8 播放列表 (*.m3u8);;所有文件 (*.*)")
        if path:
            self.url.setText(path)
            if not self.name.text().strip():
                self.name.setText(os.path.splitext(os.path.basename(path))[0])

    def reveal(self):
        d = self.st.save_dir
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
        cmd = [sys.executable, CORE, self.url.text().strip()]
        cmd += ["--save-dir", self.st.save_dir]
        if self.st.cache_dir:
            cmd += ["--cache-dir", self.st.cache_dir]
        cmd += ["--browser", self.st.get("browser", "msedge")]
        if self.st.get("show_browser", False):
            cmd += ["--no-headless"]
        cmd += ["--wait", str(self.st.get("wait", 25))]
        cmd += ["--workers", str(self.st.get("workers", 8))]
        cmd += ["--retries", str(self.st.get("retries", 3))]
        ff = self.st.get("ffmpeg", "")
        if ff:
            cmd += ["--ffmpeg", ff]
        name = self.name.text().strip()
        if name:
            if not name.lower().endswith(".mp4"):
                name += ".mp4"
            cmd += ["-o", name]
        return cmd

    def start(self):
        if not self.url.text().strip():
            QMessageBox.warning(self, "缺少地址", "先填一个网页地址或 m3u8 地址，或点「本地文件…」")
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
            self.reset()

    def on_finished(self, code: int, _status):
        if self.buf.strip():
            self.write(self.buf.strip())
            self.buf = ""
        self.reset()
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

    def reset(self):
        self.btn_go.setEnabled(True)
        self.btn_stop.setEnabled(False)


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
