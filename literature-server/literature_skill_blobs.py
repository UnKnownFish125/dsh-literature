#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_skill_blobs.py — skill bundle 的内容寻址存储（CAS）。

问题背景：`skill_files` 只存元数据（rel_path/size/sha256/mode），不存内容；
导入时若 `artifact_uri` 为空，部署器只能拿到 SKILL.md，**bundle 文件全部丢失**
（lieflat-charts 的 SKILL.md 大量引用 templates/、color-presets.js、catalog.md）。

解决：文件内容按 sha256 存进 CAS，天然去重、可校验、可离线重建完整 bundle。
  <root>/ab/abcdef0123…    （sha256 前 2 位作分目录，避免单目录百万文件）

写入原子：临时文件 + fsync + os.replace；已存在则直接复用（去重）。
"""
import hashlib
import os
import stat
import tempfile


class BlobError(ValueError):
    pass


class BlobStore:
    """内容寻址存储。root 默认与 literature.db 同级的 data/blobs。"""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    # ── 基础路径 ────────────────────────────────────────────────
    @staticmethod
    def sha256(data):
        return hashlib.sha256(data).hexdigest()

    def path(self, digest):
        digest = self._check(digest)
        return os.path.join(self.root, digest[:2], digest)

    @staticmethod
    def _check(digest):
        if not isinstance(digest, str) or len(digest) != 64 or \
                any(c not in "0123456789abcdef" for c in digest):
            raise BlobError("invalid sha256 digest")
        return digest

    def exists(self, digest):
        return os.path.isfile(self.path(digest))

    # ── 读写 ────────────────────────────────────────────────────
    def put(self, data):
        """写入内容，返回 sha256。已存在则跳过（去重）。"""
        if not isinstance(data, (bytes, bytearray)):
            raise BlobError("blob data must be bytes")
        data = bytes(data)
        digest = self.sha256(data)
        target = self.path(digest)
        if os.path.isfile(target) and os.path.getsize(target) == len(data):
            return digest
        folder = os.path.dirname(target)
        os.makedirs(folder, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return digest

    def get(self, digest):
        """读取内容并校验哈希；缺失或损坏抛 BlobError。"""
        path = self.path(digest)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            raise BlobError("blob not found: " + digest) from None
        actual = self.sha256(data)
        if actual != digest:
            raise BlobError("blob corrupted: %s (actual %s)" % (digest, actual))
        return data

    def verify(self, digest):
        try:
            self.get(digest)
            return True
        except BlobError:
            return False

    # ── 批量与统计 ──────────────────────────────────────────────
    def put_files(self, files):
        """files: {rel_path: bytes} → {rel_path: sha256}。"""
        return {rel: self.put(data) for rel, data in files.items()}

    def stats(self):
        count = 0
        total = 0
        for folder in (os.path.join(self.root, d) for d in os.listdir(self.root)) \
                if os.path.isdir(self.root) else ():
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    count += 1
                    total += os.path.getsize(path)
        return {"blobs": count, "bytes": total, "root": self.root}

    def prune(self, keep_digests):
        """删除不在 keep_digests 里的 blob（危险操作，需显式调用）。"""
        keep = set(self._check(d) for d in keep_digests)
        removed, freed = [], 0
        if not os.path.isdir(self.root):
            return {"removed": 0, "bytes": 0}
        for entry in os.listdir(self.root):
            folder = os.path.join(self.root, entry)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if name in keep:
                    continue
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    freed += os.path.getsize(path)
                    os.unlink(path)
                    removed.append(name)
            if not os.listdir(folder):
                os.rmdir(folder)
        return {"removed": len(removed), "bytes": freed}


def _self_test():
    import tempfile as _tf
    with _tf.TemporaryDirectory(prefix="blob-test-") as tmp:
        store = BlobStore(os.path.join(tmp, "blobs"))
        a = b"hello world"
        b = b"\x89PNG\r\n\x1a\n" + b"x" * 1000
        da, db = store.put(a), store.put(b)
        assert da == hashlib.sha256(a).hexdigest()
        assert store.get(da) == a and store.get(db) == b
        print("PASS put/get: 文本与二进制往返一致")

        # 去重：同内容再写不新增文件
        before = store.stats()["blobs"]
        assert store.put(a) == da
        assert store.stats()["blobs"] == before
        print("PASS dedupe: 同内容不重复落盘")

        # 分目录
        assert os.path.basename(os.path.dirname(store.path(da))) == da[:2]
        print("PASS sharding: 按 sha256 前 2 位分目录")

        # 损坏检测
        with open(store.path(db), "wb") as fh:
            fh.write(b"corrupted")
        assert store.verify(db) is False
        try:
            store.get(db)
            raise AssertionError("should raise")
        except BlobError as exc:
            assert "corrupted" in str(exc)
        print("PASS integrity: 内容被篡改后 verify=False 且 get 抛错")

        # 非法 digest
        for bad in ("", "xyz", "A" * 64, "a" * 63):
            try:
                store.path(bad)
                raise AssertionError("should reject: " + repr(bad))
            except BlobError:
                pass
        print("PASS validation: 非法 digest 被拒绝")

        # prune
        store.put(b"third")
        res = store.prune([da])
        assert res["removed"] >= 1
        assert store.verify(da) and not store.exists(db)
        print(f"PASS prune: 保留指定 blob，删除其余（{res['removed']} 个）")
        print("ALL BLOB SELF-TESTS PASSED")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--stats", metavar="ROOT")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
    elif args.stats:
        import json
        print(json.dumps(BlobStore(args.stats).stats(), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
