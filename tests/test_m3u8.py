# -*- coding: utf-8 -*-
"""本地（file://）HLS 测试：不联网也能跑，CI 用。"""
import hashlib
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import m3u8_download as md  # noqa: E402


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _make(plain: bool, workdir: str):
    seg_dir = os.path.join(workdir, "ts")
    os.makedirs(seg_dir, exist_ok=True)
    key = bytes(range(16))
    with open(os.path.join(workdir, "key.bin"), "wb") as f:
        f.write(key)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:4", "#EXT-X-MEDIA-SEQUENCE:3"]
    if not plain:
        lines.append('#EXT-X-KEY:METHOD=AES-128,URI="key.bin"')
    want = b""
    for i in range(3):
        data = bytes(random.getrandbits(8) for _ in range(4096 + i * 111))
        want += data
        body = data if plain else md.aes128_cbc_encrypt(
            key, (3 + i).to_bytes(16, "big"), md.pkcs7_pad(data))
        with open(os.path.join(seg_dir, f"s{i}.ts"), "wb") as f:
            f.write(body)
        lines += ["#EXTINF:4.000,", f"ts/s{i}.ts"]
    lines.append("#EXT-X-ENDLIST")
    m3u8 = os.path.join(workdir, "index.m3u8")
    with open(m3u8, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return m3u8, want


def test_aes_selftest():
    md._selftest_aes()


def test_local_plain(tmp_path=None):
    work = tmp_path or tempfile.mkdtemp(prefix="m3u8_plain_")
    m3u8, want = _make(True, str(work))
    out = os.path.join(str(work), "out.mp4")
    assert md.main([m3u8, "-o", out, "--keep-temp"]) == 0
    assert open(out, "rb").read() == want


def test_local_aes(tmp_path=None):
    work = tmp_path or tempfile.mkdtemp(prefix="m3u8_aes_")
    m3u8, want = _make(False, str(work))
    out = os.path.join(str(work), "out.mp4")
    assert md.main([m3u8, "-o", out, "--keep-temp"]) == 0
    assert open(out, "rb").read() == want


if __name__ == "__main__":
    import shutil
    d = tempfile.mkdtemp(prefix="m3u8_selftest_")
    try:
        test_aes_selftest()
        test_local_plain(d + "_p")
        test_local_aes(d + "_a")
        print("全部通过")
    finally:
        for p in (d + "_p", d + "_a"):
            shutil.rmtree(p, ignore_errors=True)
