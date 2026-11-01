#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m3u8 下载器（2026 重写版）

把一个 HLS（m3u8）视频下载到本地并合并成一个文件。

相对 2021 年那版（m3u8.pyw / phncdn / uu / x.py）改掉了这些问题：
  * 不再靠"第 7 行、奇数行"这种行号猜格式 —— 按 HLS 规范解析
  * 支持网络地址、master playlist（自动挑最高码率）、相对路径
  * 支持 AES-128 加密分片（内置纯 Python AES，不用装 cryptography）
  * 支持 fMP4 的 EXT-X-MAP、EXT-X-BYTERANGE
  * 线程池并发下载 + 失败重试 + 断点续传（已下好的分片不重复下）
  * 不再硬编码 Z:/mp4、不再依赖 pygame / gevent
  * 有 ffmpeg 就用它无损合并，没有就二进制拼接（TS 通常能播）

用法：
    python m3u8_download.py "https://example.com/xxx/index.m3u8"
    python m3u8_download.py play.m3u8 -o D:\视频\第01集.mp4
    python m3u8_download.py "https://..." --referer "https://example.com/" --cookie "a=1"
    python m3u8_download.py "https://..." --workers 16 --retries 5
    python m3u8_download.py "https://..." --dry-run     # 只看解析结果，不下载
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 requests：pip install requests\n")
    raise SystemExit(2)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
CHUNK = 64 * 1024


# ────────────────────────────── AES-128 ──────────────────────────────
# HLS 的 AES-128 是 CBC 模式。这里自带一份实现，免得用户额外装包。

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76"
    "ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d83115"
    "04c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f84"
    "53d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa8"
    "51a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d1973"
    "60814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479"
    "e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a"
    "703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df"
    "8ca1890dbfe6426841992d0fb054bb16"
)
_INV_SBOX = bytes(256)
_INV_SBOX = bytearray(256)
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_INV_SBOX = bytes(_INV_SBOX)
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r & 0xFF


def _expand_key(key: bytes) -> list[bytes]:
    if len(key) != 16:
        raise ValueError("AES-128 需要 16 字节密钥")
    w = [list(key[i * 4:(i + 1) * 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [bytes(sum(w[4 * r:4 * r + 4], [])) for r in range(11)]


def _add_round_key(s: list[int], k: bytes) -> None:
    for i in range(16):
        s[i] ^= k[i]


def _encrypt_block(block: bytes, rk: list[bytes]) -> bytes:
    s = list(block)
    _add_round_key(s, rk[0])
    for rnd in range(1, 11):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # ShiftRows
        if rnd != 10:
            t = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t += [
                    _mul(a0, 2) ^ _mul(a1, 3) ^ a2 ^ a3,
                    a0 ^ _mul(a1, 2) ^ _mul(a2, 3) ^ a3,
                    a0 ^ a1 ^ _mul(a2, 2) ^ _mul(a3, 3),
                    _mul(a0, 3) ^ a1 ^ a2 ^ _mul(a3, 2),
                ]
            s = t
        _add_round_key(s, rk[rnd])
    return bytes(s)


def _decrypt_block(block: bytes, rk: list[bytes]) -> bytes:
    s = list(block)
    _add_round_key(s, rk[10])
    for rnd in range(9, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]  # InvShiftRows
        s = [_INV_SBOX[b] for b in s]
        _add_round_key(s, rk[rnd])
        if rnd != 0:
            t = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t += [
                    _mul(a0, 14) ^ _mul(a1, 11) ^ _mul(a2, 13) ^ _mul(a3, 9),
                    _mul(a0, 9) ^ _mul(a1, 14) ^ _mul(a2, 11) ^ _mul(a3, 13),
                    _mul(a0, 13) ^ _mul(a1, 9) ^ _mul(a2, 14) ^ _mul(a3, 11),
                    _mul(a0, 11) ^ _mul(a1, 13) ^ _mul(a2, 9) ^ _mul(a3, 14),
                ]
            s = t
    return bytes(s)


def aes128_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    rk = _expand_key(key)
    iv = iv or b"\x00" * 16
    out = bytearray()
    prev = iv
    for off in range(0, len(data) - len(data) % 16, 16):
        blk = data[off:off + 16]
        dec = _decrypt_block(blk, rk)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    return bytes(out)


def aes128_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    rk = _expand_key(key)
    iv = iv or b"\x00" * 16
    out = bytearray()
    prev = iv
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        prev = _encrypt_block(bytes(a ^ b for a, b in zip(blk, prev)), rk)
        out += prev
    return bytes(out)


def pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    n = block - len(data) % block
    return data + bytes([n]) * n


def pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data


def _selftest_aes() -> None:
    """FIPS-197 标准向量，确保自带 AES 没写错。"""
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plain = bytes.fromhex("00112233445566778899aabbccddeeff")
    want = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    got = _encrypt_block(plain, _expand_key(key))
    assert got == want, "AES 自检失败"
    assert _decrypt_block(want, _expand_key(key)) == plain
    iv = bytes(range(16))
    data = b"hello m3u8 aes-128 CBC!" * 3
    enc = aes128_cbc_encrypt(key, iv, pkcs7_pad(data))
    assert pkcs7_unpad(aes128_cbc_decrypt(key, iv, enc)) == data


# ────────────────────────────── 解析 ──────────────────────────────
@dataclass
class Key:
    method: str = "NONE"
    uri: str = ""
    iv: Optional[bytes] = None
    data: bytes = b""      # 下载后的密钥内容
    keyformat: str = ""


@dataclass
class MediaPart:
    """一个要落盘的分片（普通 ts 或 fMP4 的 init 段）。"""
    url: str
    seq: int = 0
    key: Optional[Key] = None
    byterange: Optional[tuple[int, int]] = None   # (start, length)
    is_init: bool = False


@dataclass
class Playlist:
    segments: list[MediaPart] = field(default_factory=list)
    variants: list[tuple[str, int]] = field(default_factory=list)  # (url, bandwidth)
    is_master: bool = False
    media_sequence: int = 0
    endlist: bool = False


_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _attrs(line: str) -> dict[str, str]:
    body = line.split(":", 1)[1] if ":" in line else ""
    out = {}
    for k, v in _ATTR_RE.findall(body):
        out[k] = v.strip('"')
    return out


def _iv_from_attr(v: str) -> Optional[bytes]:
    v = (v or "").strip()
    if not v:
        return None
    if v.lower().startswith("0x"):
        v = v[2:]
    v = v.zfill(32)
    try:
        return bytes.fromhex(v)
    except ValueError:
        return None


def parse_playlist(text: str, base_url: str) -> Playlist:
    pl = Playlist()
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    cur_key: Optional[Key] = None
    pending_range: Optional[tuple[int, int]] = None
    seq = 0
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            pl.media_sequence = int(ln.split(":", 1)[1].strip() or 0)
            seq = pl.media_sequence     # 不给 IV 时，IV 由媒体序列号推导
        elif ln.startswith("#EXT-X-STREAM-INF:"):
            pl.is_master = True
            bw = int(_attrs(ln).get("BANDWIDTH") or 0)
            pl.variants.append(("", bw))
        elif ln.startswith("#EXT-X-KEY:"):
            a = _attrs(ln)
            method = (a.get("METHOD") or "NONE").upper()
            if method == "NONE":
                cur_key = None
            else:
                cur_key = Key(method=method,
                              uri=urllib.parse.urljoin(base_url, a.get("URI", "")),
                              iv=_iv_from_attr(a.get("IV", "")),
                              keyformat=a.get("KEYFORMAT", ""))
        elif ln.startswith("#EXT-X-MAP:"):
            a = _attrs(ln)
            uri = urllib.parse.urljoin(base_url, a.get("URI", ""))
            pl.segments.append(MediaPart(url=uri, seq=-1, key=cur_key, is_init=True))
        elif ln.startswith("#EXT-X-BYTERANGE:"):
            val = ln.split(":", 1)[1]
            length, _, start = val.partition("@")
            start = int(start) if start else None
            pending_range = (start if start is not None else -1, int(length))
        elif ln.startswith("#EXT-X-ENDLIST"):
            pl.endlist = True
        elif ln.startswith("#"):
            continue
        else:
            uri = urllib.parse.urljoin(base_url, ln)
            if pl.is_master and pl.variants and not pl.variants[-1][0]:
                pl.variants[-1] = (uri, pl.variants[-1][1])
            else:
                pl.segments.append(MediaPart(url=uri, seq=seq, key=cur_key,
                                             byterange=pending_range))
                seq += 1
            pending_range = None
    return pl


# ────────────────────────────── 下载 ──────────────────────────────
class _LocalResp:
    """file:// 地址的假响应对象，让本地 m3u8 / 本地 ts 也能走同一套流程。"""

    def __init__(self, data: bytes, url: str):
        self.content = data
        self.url = url
        self.status_code = 200

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


def _local_path(url: str) -> str:
    from urllib.request import url2pathname
    p = url2pathname(urllib.parse.urlparse(url).path)
    return p.lstrip("/") if os.name == "nt" else p


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def _fmt_secs(s: float) -> str:
    s = int(s)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class Downloader:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": args.user_agent})
        if args.referer:
            self.session.headers["Referer"] = args.referer
        if args.cookie:
            self.session.headers["Cookie"] = args.cookie
        for h in args.header or []:
            if ":" in h:
                k, v = h.split(":", 1)
                self.session.headers[k.strip()] = v.strip()
        self.session.trust_env = not args.no_proxy
        self.lock = threading.Lock()
        self.done = 0
        self.total = 0
        self.done_bytes = 0
        self.t0 = time.time()

    # ---------- 基础请求 ----------
    def _get(self, url: str, stream: bool = False, headers: Optional[dict] = None):
        if url.lower().startswith("file://"):
            path = _local_path(url)
            with open(path, "rb") as f:
                return _LocalResp(f.read(), url)
        last = None
        for i in range(self.args.retries):
            try:
                r = self.session.get(url, timeout=self.args.timeout, stream=stream,
                                     headers=headers, allow_redirects=True)
                if r.status_code == 200:
                    return r
                last = f"HTTP {r.status_code}"
                if r.status_code in (403, 401):
                    hint = "（可能需要 --referer / --cookie / --user-agent）"
                    last += hint
                elif r.status_code == 404:
                    last += "（地址不存在，可能已过期）"
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {str(e)[:120]}"
            if i < self.args.retries - 1:
                time.sleep(min(8, 0.8 * (2 ** i)) + random.random() * 0.3)
        raise RuntimeError(f"下载失败：{url}\n  原因：{last}")

    # ---------- m3u8 ----------
    def load_playlist(self, target: str) -> tuple[Playlist, str]:
        if re.match(r"^https?://", target, re.I):
            r = self._get(target)
            return parse_playlist(r.text, r.url), r.url
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        base = "file:///" + os.path.abspath(target).replace("\\", "/")
        return parse_playlist(text, base), base

    def choose_variant(self, url: str, pl: Playlist) -> tuple[Playlist, str]:
        if not pl.is_master:
            return pl, url
        variants = [(u, b) for u, b in pl.variants if u]
        if not variants:
            raise RuntimeError("master playlist 里没有可用的子清单")
        variants.sort(key=lambda x: x[1], reverse=True)
        idx = self.args.bandwidth_index or 0
        idx = max(0, min(idx, len(variants) - 1)) if idx >= 0 else 0
        if self.args.verbose:
            for i, (u, b) in enumerate(variants):
                print(f"  [变体 {i}] {b // 1000} kbps  {u}")
        chosen, bw = variants[idx]
        print(f"→ 选择码率最高/指定变体：{bw // 1000} kbps")
        r = self._get(chosen)
        return parse_playlist(r.text, r.url), r.url

    # ---------- 密钥 ----------
    def fetch_keys(self, segs: list[MediaPart]) -> None:
        cache: dict[str, bytes] = {}
        for s in segs:
            k = s.key
            if not k or k.method == "NONE":
                continue
            if k.uri in cache:
                k.data = cache[k.uri]
                continue
            if k.method != "AES-128":
                raise RuntimeError(f"不支持的加密方式：{k.method}（目前只支持 AES-128）")
            r = self._get(k.uri)
            data = r.content
            if len(data) != 16:
                raise RuntimeError(f"密钥长度异常：{len(data)} 字节（应为 16）")
            cache[k.uri] = data
            k.data = data
        print(f"→ 密钥就绪（{len(cache)} 个）")

    # ---------- 分片 ----------
    def _seg_path(self, parts_dir: str, s: MediaPart, index: int) -> str:
        if s.is_init:
            return os.path.join(parts_dir, "init.mp4")
        return os.path.join(parts_dir, f"{index:06d}.ts")

    def download_segment(self, s: MediaPart, path: str) -> int:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return os.path.getsize(path)
        tmp = path + ".part"
        headers = {}
        if s.byterange:
            start, length = s.byterange
            if start >= 0:
                headers["Range"] = f"bytes={start}-{start + length - 1}"
            else:
                headers["Range"] = f"bytes={length}"
        r = self._get(s.url, stream=True, headers=headers)
        raw = r.content if not s.byterange else r.content
        if s.key and s.key.method == "AES-128":
            if len(s.key.data) != 16:
                raise RuntimeError("密钥没有取到，无法解密")
            iv = s.key.iv
            if iv is None:
                iv = (s.seq & 0xFFFFFFFFFFFFFFFF).to_bytes(16, "big")
            raw = pkcs7_unpad(aes128_cbc_decrypt(s.key.data, iv, raw))
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)
        return len(raw)

    # ---------- 主流程 ----------
    def run(self, target: str, out: str) -> int:
        pl, base = self.load_playlist(target)
        pl, base = self.choose_variant(base, pl)
        segs = [s for s in pl.segments]
        if not segs:
            raise RuntimeError("清单里没有找到任何分片（是不是空文件或格式不对？）")
        print(f"→ 共 {len(segs)} 个分片"
              + ("（含 init 段）" if any(s.is_init for s in segs) else ""))

        parts_dir = out + ".parts"
        os.makedirs(parts_dir, exist_ok=True)
        self.fetch_keys(segs)
        self.total = len(segs)

        tasks = []
        for i, s in enumerate(segs):
            tasks.append((s, self._seg_path(parts_dir, s, i)))

        try:
            with ThreadPoolExecutor(max_workers=self.args.workers) as pool:
                futures = {}
                for s, p in tasks:
                    futures[pool.submit(self._download_one, s, p)] = s
                for fut in futures:
                    fut.result()
        except KeyboardInterrupt:
            print("\n中断：已下载的分片保留，下次再跑会接着下")
            return 130
        finally:
            self._progress(force=True)

        names = [p for _, p in tasks]
        print()
        print(f"→ 下载完成：{self._fmt_done()}，用时 {_fmt_secs(time.time() - self.t0)}")

        ok = self.merge(parts_dir, names, out)
        if ok and not self.args.keep_temp:
            shutil.rmtree(parts_dir, ignore_errors=True)
            print("→ 缓存已清理")
        elif not ok:
            print(f"→ 分片保留在 {parts_dir}，可手动用 ffmpeg 合并")
        return 0 if ok else 1

    def _download_one(self, s: MediaPart, path: str) -> None:
        size = self.download_segment(s, path)
        with self.lock:
            self.done += 1
            self.done_bytes += size
            self._progress()

    def _fmt_done(self) -> str:
        return f"{self.done}/{self.total} 片，{_fmt_size(self.done_bytes)}"

    def _progress(self, force: bool = False) -> None:
        now = time.time()
        if not force and hasattr(self, "_last") and now - self._last < 0.3:
            return
        self._last = now
        pct = (self.done / self.total * 100) if self.total else 0
        speed = self.done_bytes / max(0.1, now - self.t0)
        bar_len = 24
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(f"\r  [{bar}] {pct:5.1f}%  {self.done}/{self.total}  "
                         f"{_fmt_size(self.done_bytes)}  {_fmt_size(speed)}/s   ")
        sys.stdout.flush()

    # ---------- 合并 ----------
    def _find_ffmpeg(self) -> Optional[str]:
        if self.args.ffmpeg:
            return self.args.ffmpeg if os.path.exists(self.args.ffmpeg) else None
        for name in ("ffmpeg", "ffmpeg.exe"):
            p = shutil.which(name)
            if p:
                return p
        here = os.path.dirname(os.path.abspath(sys.argv[0]))
        for cand in (os.path.join(here, "ffmpeg.exe"), os.path.join(here, "bin", "ffmpeg.exe")):
            if os.path.exists(cand):
                return cand
        return None

    def merge(self, parts_dir: str, names: list[str], out: str) -> bool:
        names = [n for n in names if os.path.exists(n)]
        if not names:
            print("→ 没有可合并的分片")
            return False
        ffmpeg = self._find_ffmpeg()
        if ffmpeg:
            list_file = os.path.join(parts_dir, "concat.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for n in names:
                    p = os.path.abspath(n).replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{p}'\n")
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy"]
            # 只有 TS 分片才需要把 ADTS 音频转成 ASC；fMP4 加了反而可能报错
            if all(n.lower().endswith(".ts") for n in names):
                cmd += ["-bsf:a", "aac_adtstoasc"]
            cmd.append(out)
            print("→ 用 ffmpeg 合并（无损 copy）…")
            import subprocess
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                print(f"→ 合并完成：{out}（{_fmt_size(os.path.getsize(out))}）")
                return True
            print(f"→ ffmpeg 合并失败：{r.stderr.strip()[:300]}")
            print("  换二进制拼接再试一次…")
        # 无 ffmpeg：二进制拼接（MPEG-TS 通常能播；fMP4 也能拼）
        with open(out, "wb") as w:
            for n in names:
                with open(n, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        w.write(b)
        print(f"→ 已拼接成 {out}（{_fmt_size(os.path.getsize(out))}）"
              "  · 没有 ffmpeg，建议装一个再合并，更稳")
        return True


# ────────────────────────────── 命令行 ──────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="m3u8_download",
        description="下载 m3u8（HLS）视频并合并成 mp4（支持 AES-128 加密 / master playlist）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例子：\n"
               "  python m3u8_download.py \"https://x.com/a/index.m3u8\"\n"
               "  python m3u8_download.py local.m3u8 -o out.mp4 --referer \"https://x.com/\"\n")
    p.add_argument("target", nargs="?", help="m3u8 地址（http/https），或本地 .m3u8 文件路径")
    p.add_argument("-o", "--output", help="输出文件（默认按 m3u8 名字生成 .mp4）")
    p.add_argument("--referer", default="", help="Referer（防盗链站点常用）")
    p.add_argument("--cookie", default="", help="Cookie")
    p.add_argument("--user-agent", default=DEFAULT_UA, help="User-Agent")
    p.add_argument("--header", action="append", default=[], help="额外请求头，格式 \"K: V\"，可重复")
    p.add_argument("--workers", type=int, default=8, help="并发下载数（默认 8）")
    p.add_argument("--retries", type=int, default=3, help="每个分片重试次数（默认 3）")
    p.add_argument("--timeout", type=float, default=20.0, help="请求超时秒数（默认 20）")
    p.add_argument("--bandwidth-index", type=int, default=0,
                   help="master playlist 里选第几个变体，0=最高码率（默认 0）")
    p.add_argument("--ffmpeg", default="", help="ffmpeg 路径（默认自动找 PATH / 同目录）")
    p.add_argument("--keep-temp", action="store_true", help="保留分片缓存，便于排查/重跑")
    p.add_argument("--no-proxy", action="store_true", help="忽略系统代理")
    p.add_argument("--dry-run", action="store_true", help="只解析、不下载")
    p.add_argument("--list-formats", action="store_true", help="列出 master playlist 的变体")
    p.add_argument("--verbose", "-v", action="store_true", help="打印更多过程")
    p.add_argument("--selftest", action="store_true", help="跑一遍内置 AES 自检后退出")
    return p


def default_output(target: str, base: str) -> str:
    if re.match(r"^https?://", target, re.I):
        name = os.path.basename(urllib.parse.urlparse(target).path) or "video.m3u8"
    else:
        name = os.path.basename(target)
    stem, _ = os.path.splitext(name)
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem) or "video"
    out = stem + ".mp4"
    if os.path.exists(out):
        i = 2
        while os.path.exists(f"{stem}_{i}.mp4"):
            i += 1
        out = f"{stem}_{i}.mp4"
    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.selftest:
        _selftest_aes()
        print("AES 自检通过")
        return 0
    if not args.target:
        build_parser().error("缺少 m3u8 地址（或用 --selftest 只跑自检）")
    _selftest_aes()

    dl = Downloader(args)
    try:
        pl, base = dl.load_playlist(args.target)
        if args.list_formats:
            if pl.is_master:
                variants = sorted([(u, b) for u, b in pl.variants if u], key=lambda x: -x[1])
                for i, (u, b) in enumerate(variants):
                    print(f"[{i}] {b // 1000:>6} kbps  {u}")
            else:
                print("这不是 master playlist（只有一条媒体流）")
            return 0
        if args.dry_run:
            pl, base = dl.choose_variant(base, pl)
            print(f"分片数：{len(pl.segments)}")
            print(f"加密：{'是' if any(s.key and s.key.method != 'NONE' for s in pl.segments) else '否'}")
            for s in pl.segments[:5]:
                print("  " + s.url)
            if len(pl.segments) > 5:
                print(f"  …（还有 {len(pl.segments) - 5} 个）")
            return 0
        out = args.output or default_output(args.target, base)
        print(f"→ 输出：{os.path.abspath(out)}")
        return dl.run(args.target, out)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"\n失败：{e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
