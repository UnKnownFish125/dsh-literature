#!/usr/bin/env python3
"""Managed skill deployment; only this module is new.

SkillDeployer(db_path, config).deploy(skill_id, version_id, target_id)
Config: {"targets": {"managed": {"root_dir": "/trusted/skills",
         "scope": "workspace", "workspace_id": "<UUID>"}},
         "projectDir": "/project", "customSkillDirs": ["/trusted/skills"],
         "agentsHome": "/configured/agents"}
Targets may use root_kind=agents|dsh instead of root_dir. No target is
implicitly global. Versions must be approved and skills active.

Linux renameat2(RENAME_EXCHANGE) is required for upgrading a nonempty
bundle: POSIX os.replace cannot replace a nonempty directory. First
publication and retirement use os.replace. No non-atomic fallback exists.
Staging, retired bundles, journals and locks are outside discovery roots.
PyYAML is required for actual YAML parsing. An optional native_verify
callback(path, target, version) can additionally perform DSH list/get;
without it, verified means filesystem/frontmatter/hash verification only.
"""
import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote, urlparse


class DeploymentError(ValueError):
    pass


class DriftError(DeploymentError):
    def __init__(self, message, observed_hash=""):
        super().__init__(message)
        self.observed_hash = observed_hash


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def bundle_sha256(skill_md, files):
    """Frozen convention: sort ALL paths, including SKILL.md, as UTF-8."""
    if "SKILL.md" in files:
        raise DeploymentError("files must not contain SKILL.md")
    entries = dict(files, **{"SKILL.md": skill_md})
    rows = {p: {"sha256": sha256_hex(b), "size_bytes": len(b)}
            for p, b in entries.items()}
    return _metadata_hash(rows)


def _metadata_hash(rows):
    h = hashlib.sha256()
    for p in sorted(rows, key=lambda s: s.encode("utf-8")):
        r = rows[p]
        h.update((p + "\0" + r["sha256"] + "\0" +
                  str(r["size_bytes"]) + "\n").encode("utf-8"))
    return h.hexdigest()


def _rel(value):
    if (not isinstance(value, str) or not value or ".." in value or
            value.startswith("/") or "\\" in value or ":" in value or
            any(ord(c) < 32 for c in value) or
            any(p in ("", ".") for p in value.split("/"))):
        raise DeploymentError("unsafe relative path: %r" % (value,))
    value.encode("utf-8", "strict")
    return value


def _slug(value):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value or ""):
        raise DeploymentError("invalid skill slug")
    return value


def _absolute(value):
    raw = os.path.expanduser(os.fspath(value))
    p = Path(raw)
    if (not p.is_absolute() or ".." in p.parts or "\\" in raw or
            any(ord(c) < 32 for c in raw)):
        raise DeploymentError("configuration requires safe absolute paths")
    for node in reversed((p,) + tuple(p.parents)):
        try:
            if stat.S_ISLNK(node.lstat().st_mode):
                raise DeploymentError("symlink path rejected: %s" % node)
        except FileNotFoundError:
            pass
    return p


def _read_bytes(path, maximum):
    """Open every ancestor with O_NOFOLLOW, not only the final filename."""
    path = _absolute(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=fd)
        with os.fdopen(leaf, "rb") as f:
            before = os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise DeploymentError("not a bounded regular file: %s" % path)
            data = f.read(maximum + 1)
            after = os.fstat(f.fileno())
            if (len(data) > maximum or before.st_size != len(data) or
                    (before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_mtime_ns, after.st_ctime_ns)):
                raise DeploymentError("file changed while reading: %s" % path)
            return data, stat.S_IMODE(before.st_mode)
    finally:
        os.close(fd)


def _frontmatter(data, slug=None):
    try:
        import yaml
    except ImportError as exc:
        raise DeploymentError("PyYAML is required for frontmatter parsing") from exc
    text = data.decode("utf-8", "strict")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise DeploymentError("SKILL.md must start with YAML frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise DeploymentError("frontmatter terminator missing")
    try:
        meta = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise DeploymentError("invalid YAML frontmatter") from exc
    if not isinstance(meta, dict) or any(
            not isinstance(meta.get(k), str) or not meta[k].strip()
            for k in ("name", "description")):
        raise DeploymentError("frontmatter name and description must be nonempty strings")
    if slug is not None and meta["name"] != slug:
        raise DeploymentError("frontmatter name differs from registered slug")
    if not "\n".join(lines[end + 1:]).strip():
        raise DeploymentError("skill body must not be empty")
    return meta


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _rename(source, dest):
    os.replace(source, dest)
    _fsync_dir(Path(source).parent)
    _fsync_dir(Path(dest).parent)


def _exchange(left, right):
    """Atomically replace a live nonempty directory without an absence gap."""
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise DeploymentError("atomic directory exchange needs Linux renameat2")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                   ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        code = ctypes.get_errno()
        raise OSError(code, "atomic directory exchange unavailable: " + os.strerror(code))
    _fsync_dir(Path(left).parent)
    _fsync_dir(Path(right).parent)


def _inode(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise DeploymentError("expected directory, found link or file: %s" % path)
    return [info.st_dev, info.st_ino]


def _atomic_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    _rename(temporary, path)


class SkillDeployer:
    """Single-host writer. Methods return deployment dicts; bad IDs raise.

    Publication errors return state=failed and preserve applied_version_id.
    A recovery error raises rather than discarding the only surviving copy.
    Caller-supplied SQLite connections must have no open transaction.
    """
    def __init__(self, db_path, config, ensure_schema=True, native_verify=None):
        if not isinstance(config, dict):
            raw, _ = _read_bytes(config, 1024 * 1024)
            config = json.loads(raw)
        self.config = dict(config)
        self.db_path = db_path
        self.native_verify = native_verify
        self._mutex = threading.RLock()
        self.max_files = int(config.get("max_files", 4096))
        self.max_bytes = int(config.get("max_bytes", 64 * 1024 * 1024))
        if min(self.max_files, self.max_bytes) <= 0:
            raise DeploymentError("positive package limits required")
        self.agents_home = _absolute(config.get("agentsHome") or
            os.environ.get("DSH_AGENTS_HOME") or Path.home() / ".agents")
        self.dsh_home = _absolute(config.get("dshHome") or
            os.environ.get("DSH_HOME") or Path.home() / ".dsh")
        if not isinstance(config.get("targets"), dict) or not config["targets"]:
            raise DeploymentError("trusted config.targets is required")
        if ensure_schema:
            from literature_skill_schema import install_skill_schema
            with self._connection() as conn:
                install_skill_schema(conn, note="literature_skill_deploy")

    def _target(self, target):
        tid = target.get("target_id", target.get("id")) if isinstance(target, dict) else target
        if tid not in self.config["targets"]:
            raise DeploymentError("target is not in trusted configuration")
        cfg = dict(self.config["targets"][tid])
        root = cfg.get("root_dir")
        if root is None:
            homes = {"agents": self.agents_home, "dsh": self.dsh_home}
            if cfg.get("root_kind") not in homes:
                raise DeploymentError("target requires root_dir or root_kind=agents|dsh")
            root = homes[cfg["root_kind"]] / "skills"
        cfg["root_dir"] = _absolute(root)
        cfg["target_id"] = tid
        scope = cfg.get("scope", cfg.get("target_scope"))
        if scope not in ("workspace", "global"):
            raise DeploymentError("target scope must be explicit")
        cfg["scope"] = scope
        ws = cfg.get("workspace_id")
        if scope == "workspace":
            try:
                if str(uuid.UUID(ws)) != ws:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise DeploymentError("workspace target requires canonical workspace UUID")
        elif ws is not None:
            raise DeploymentError("global target workspace_id must be null")
        if isinstance(target, dict):
            for key in ("root_dir", "scope", "workspace_id"):
                if key in target and str(target[key]) != str(cfg.get(key)):
                    raise DeploymentError("target payload cannot override configuration")
        return cfg

    def _roots(self):
        roots = []
        project = self.config.get("projectDir")
        if project:
            p = _absolute(project)
            for ancestor in (p,) + tuple(p.parents):
                roots.extend([(ancestor / ".dsh/skills", 100),
                              (ancestor / ".agents/skills", 200)])
        roots.extend((_absolute(p), 300) for p in self.config.get("customSkillDirs", []))
        roots.extend([(self.dsh_home / "skills", 400), (self.agents_home / "skills", 500)])
        for tid in self.config["targets"]:
            cfg = self._target(tid)
            root = cfg["root_dir"]
            if not any(p == root for p, _ in roots):
                roots.append((root, int(cfg.get("rank", 300))))
        unique = {}
        for p, rank in roots:
            unique[p] = min(rank, unique.get(p, rank))
        return sorted(unique.items(), key=lambda pair: pair[1])

    @contextlib.contextmanager
    def _connection(self):
        borrowed = isinstance(self.db_path, sqlite3.Connection)
        conn = self.db_path if borrowed else sqlite3.connect(self.db_path, timeout=30)
        try:
            if conn.in_transaction:
                raise DeploymentError("caller must commit before deployment")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            if not borrowed:
                conn.close()

    @staticmethod
    def _one(conn, sql, params=()):
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    @contextlib.contextmanager
    def _locked(self, target):
        cfg = self._target(target)
        root = cfg["root_dir"]
        if root == Path("/"):
            raise DeploymentError("filesystem root cannot be a discovery root")
        parent = root.parent
        roots = [p for p, _ in self._roots()]
        while any(parent == p or parent.is_relative_to(p) for p in roots):
            if parent == parent.parent:
                raise DeploymentError("no safe staging location outside discovery")
            parent = parent.parent
        state = _absolute(cfg.get("state_dir") or
            parent / (".literature-deploy-" + sha256_hex(str(root).encode())[:16]))
        if any(state == p or state.is_relative_to(p) for p in roots):
            raise DeploymentError("state directory must be outside every discovery root")
        root.mkdir(parents=True, exist_ok=True)
        state.mkdir(parents=True, mode=0o700, exist_ok=True)
        _absolute(root)
        _absolute(state)
        if root.stat().st_dev != state.stat().st_dev:
            raise DeploymentError("staging and target must share a filesystem")
        with self._mutex:
            fd = os.open(state / "writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                with self._connection() as conn:
                    self._prune_staging(state)
                    yield conn, cfg, state
            finally:
                os.close(fd)

    def _prune_staging(self, state):
        referenced = set()
        for journal in state.glob("journal-*.json"):
            raw, _ = _read_bytes(journal, 1024 * 1024)
            item = json.loads(raw)
            name = item.get("tx", "")
            if not re.fullmatch(r"tx-[A-Za-z0-9_-]+", name):
                raise DeploymentError("invalid recovery journal; refusing staging cleanup")
            referenced.add(name)
        changed = False
        for path in state.glob("tx-*"):
            if path.name not in referenced:
                _absolute(path)
                shutil.rmtree(path)
                changed = True
        for path in state.glob("journal-*.json.tmp"):
            _absolute(path)
            path.unlink()
            changed = True
        if changed:
            _fsync_dir(state)

    def detect_shadowing(self, slug, root_dir):
        _slug(slug)
        root = _absolute(root_dir)
        roots = self._roots()
        matches = [rank for p, rank in roots if p == root]
        if not matches:
            raise DeploymentError("root is not configured")
        target_rank = min(matches)
        warnings = []
        for candidate, rank in roots:
            if rank >= target_rank or not candidate.exists():
                continue
            _absolute(candidate)
            for directory, dirs, names in os.walk(candidate, followlinks=False):
                for name in list(dirs):
                    if Path(directory, name).is_symlink():
                        dirs.remove(name)
                        warnings.append({"code": "uninspected_symlink", "path": str(Path(directory, name)),
                                         "rank": rank, "message": "higher-priority symlink candidate"})
                if "SKILL.md" not in names:
                    continue
                path = Path(directory, "SKILL.md")
                try:
                    data, _ = _read_bytes(path, self.max_bytes)
                    meta = _frontmatter(data)
                except (DeploymentError, OSError, UnicodeError):
                    continue
                if meta["name"] == slug:
                    warnings.append({"code": "shadowed", "path": str(path), "rank": rank,
                                     "target_rank": target_rank,
                                     "message": "%s is shadowed by %s (rank %s < %s)" %
                                                (slug, path, rank, target_rank)})
        return warnings

    def _scan(self, root):
        _absolute(root)
        if not root.is_dir():
            raise DeploymentError("bundle directory missing")
        files, modes, total = {}, {}, 0
        def fail(error):
            raise error
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail):
            for name in dirs:
                node = Path(directory, name)
                _rel(node.relative_to(root).as_posix())
                if node.is_symlink():
                    raise DeploymentError("bundle contains symlink directory")
            for name in names:
                node = Path(directory, name)
                rel = _rel(node.relative_to(root).as_posix())
                data, mode = _read_bytes(node, self.max_bytes)
                files[rel], modes[rel] = data, mode
                total += len(data)
                if len(files) > self.max_files or total > self.max_bytes:
                    raise DeploymentError("bundle exceeds configured limits")
        return files, modes

    def _spec(self, conn, version_id, skill):
        version = self._one(conn, "SELECT * FROM skill_versions WHERE id=? AND skill_id=?",
                            (version_id, skill["id"]))
        if version is None:
            raise DeploymentError("version does not belong to this skill")
        data = version["skill_md"].encode("utf-8")
        _frontmatter(data, skill["slug"])
        if sha256_hex(data) != version["content_sha256"]:
            raise DeploymentError("content_sha256 mismatch in immutable version")
        manifest = json.loads(version["manifest_json"])
        if (not isinstance(manifest, dict) or manifest.get("schema") != 1 or
                manifest.get("entry") != "SKILL.md" or
                manifest.get("slug") != skill["slug"] or
                manifest.get("version") != version["version"] or
                not isinstance(manifest.get("files"), list)):
            raise DeploymentError("invalid manifest identity/schema")
        expected = {}
        for item in manifest["files"]:
            rel = _rel(item["rel_path"])
            if rel in expected or item.get("is_symlink", 0):
                raise DeploymentError("duplicate path or symlink in manifest")
            mode = item.get("mode", 0o644)
            size = item.get("size_bytes")
            digest = item.get("sha256", "")
            if (not isinstance(size, int) or size < 0 or
                    not isinstance(mode, int) or mode < 0 or mode & ~0o777 or
                    not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise DeploymentError("invalid manifest file metadata")
            expected[rel] = dict(item, mode=mode, is_symlink=0)
        entry = {"rel_path": "SKILL.md", "size_bytes": len(data),
                 "sha256": sha256_hex(data), "mode": 0o644, "is_symlink": 0}
        if "SKILL.md" in expected and any(expected["SKILL.md"][k] != entry[k]
                for k in ("size_bytes", "sha256")):
            raise DeploymentError("manifest SKILL.md differs from stored content")
        expected.setdefault("SKILL.md", entry)
        cur = conn.execute("SELECT rel_path,size_bytes,sha256,mode,is_symlink FROM skill_files WHERE skill_version_id=?",
                           (version_id,))
        keys = [d[0] for d in cur.description]
        stored = {r[0]: dict(zip(keys, r)) for r in cur.fetchall()}
        if set(stored) - {"SKILL.md"} != set(expected) - {"SKILL.md"}:
            raise DeploymentError("skill_files and manifest file sets differ")
        for rel, item in stored.items():
            _rel(rel)
            if rel not in expected or any(item[k] != expected[rel][k]
                    for k in ("size_bytes", "sha256", "mode", "is_symlink")):
                raise DeploymentError("skill_files differs from manifest")
        artifact = _metadata_hash(expected)
        if (artifact != version["artifact_sha256"] or
                artifact != manifest.get("bundle_sha256")):
            raise DeploymentError("artifact_sha256 mismatch in immutable version")
        if len(expected) > self.max_files or sum(r["size_bytes"] for r in expected.values()) > self.max_bytes:
            raise DeploymentError("bundle exceeds configured limits")
        return {"version": version, "expected": expected, "entry": data,
                "artifact": artifact, "slug": skill["slug"]}

    def _source(self, spec):
        uri = spec["version"]["artifact_uri"]
        if uri:
            parsed = urlparse(uri)
            if parsed.scheme and (parsed.scheme != "file" or parsed.netloc not in ("", "localhost")):
                raise DeploymentError("artifact_uri must be a local directory")
            path = _absolute(unquote(parsed.path) if parsed.scheme else uri)
            files, modes = self._scan(path)
        else:
            files = {"SKILL.md": spec["entry"]}
            modes = {"SKILL.md": spec["expected"]["SKILL.md"]["mode"]}
        self._compare(spec, files, modes, check_modes=False)
        return files

    def _compare(self, spec, files, modes, check_modes=True):
        rows = {p: {"sha256": sha256_hex(b), "size_bytes": len(b)} for p, b in files.items()}
        observed = _metadata_hash(rows)
        try:
            if set(files) != set(spec["expected"]):
                raise DeploymentError("bundle file set differs from manifest")
            _frontmatter(files["SKILL.md"], spec["slug"])
            for rel, item in spec["expected"].items():
                if rows[rel] != {k: item[k] for k in ("sha256", "size_bytes")}:
                    raise DeploymentError("file digest/size mismatch: " + rel)
                if check_modes and modes[rel] != item["mode"]:
                    raise DeploymentError("file mode mismatch: " + rel)
            if observed != spec["artifact"]:
                raise DeploymentError("artifact_sha256 mismatch")
        except (DeploymentError, UnicodeError) as exc:
            raise DriftError(str(exc), observed) from exc
        return observed

    def _check(self, spec, path):
        files, modes = self._scan(path)
        return self._compare(spec, files, modes)

    def _skill(self, conn, skill_id):
        skill = self._one(conn, "SELECT * FROM skills WHERE id=?", (skill_id,))
        if skill is None:
            raise DeploymentError("skill not found")
        _slug(skill["slug"])
        return skill

    def _row(self, conn, deployment_id):
        row = self._one(conn, "SELECT * FROM skill_deployments WHERE id=?", (deployment_id,))
        if row is None:
            raise DeploymentError("deployment not found")
        cfg = self._target(row["target_id"])
        skill = self._skill(conn, row["skill_id"])
        if (row["root_dir"] != str(cfg["root_dir"]) or
                row["deployed_path"] != str(cfg["root_dir"] / skill["slug"]) or
                row["target_scope"] != cfg["scope"] or
                row["workspace_id"] != cfg.get("workspace_id")):
            raise DeploymentError("deployment no longer matches trusted target configuration")
        return row

    def _update(self, conn, deployment_id, **values):
        values["updated_at"] = time.time()
        conn.execute("UPDATE skill_deployments SET " +
                     ",".join(k + "=?" for k in values) + " WHERE id=?",
                     tuple(values.values()) + (deployment_id,))

    def _audit(self, conn, row, action, previous, current):
        conn.execute("INSERT INTO skill_audit(action,target_type,target_id,details_json,created_at) VALUES (?,?,?,?,?)",
            (action, "skill_deployment", str(row["id"]), json.dumps({
                "previous_version_id": previous, "applied_version_id": current,
                "generation": row["generation"], "operation_key": row["operation_key"]}), time.time()))

    def _result(self, conn, deployment_id):
        row = self._row(conn, deployment_id)
        slug = self._skill(conn, row["skill_id"])["slug"]
        try:
            row["warnings"] = self.detect_shadowing(slug, row["root_dir"])
        except (DeploymentError, OSError, UnicodeError) as exc:
            row["warnings"] = [{"code": "shadow_scan_incomplete", "message": str(exc)}]
        row["verification_level"] = "filesystem+native" if self.native_verify else "filesystem"
        return row

    def _stage(self, state, spec, files):
        tx = Path(tempfile.mkdtemp(prefix="tx-", dir=state))
        try:
            bundle = tx / "bundle"
            bundle.mkdir()
            for rel, data in files.items():
                path = bundle / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as f:
                    f.write(data)
                    f.flush()
                    os.fchmod(f.fileno(), spec["expected"][rel]["mode"])
                    os.fsync(f.fileno())
            for directory, _, _ in os.walk(bundle, topdown=False):
                _fsync_dir(directory)
            _fsync_dir(tx)
            self._check(spec, bundle)
            return tx
        except BaseException:
            shutil.rmtree(tx)
            raise

    def _journal_path(self, state, row):
        return state / ("journal-%s.json" % row["id"])

    def _cleanup(self, state, row, tx, preserve=False):
        if tx.exists():
            if preserve and (tx / "bundle").exists():
                archive = state / ("archive-%s-%s" % (row["id"], row["generation"]))
                _rename(tx, archive)
            else:
                shutil.rmtree(tx)
        self._journal_path(state, row).unlink(missing_ok=True)
        _fsync_dir(state)

    def _recover(self, conn, state, row):
        journal = self._journal_path(state, row)
        if not journal.exists():
            if row["state"] in ("pending", "applying"):
                self._update(conn, row["id"], state="failed", last_error="interrupted before publication")
                conn.commit()
            return
        data, _ = _read_bytes(journal, 1024 * 1024)
        j = json.loads(data)
        if (j.get("operation_key") != row["operation_key"] or
                j.get("generation") != row["generation"] or
                not re.fullmatch(r"tx-[A-Za-z0-9_-]+", j.get("tx", ""))):
            raise DeploymentError("journal identity mismatch; manual recovery required")
        tx = _absolute(state / j["tx"])
        slot = tx / "bundle"
        dest = _absolute(row["deployed_path"])
        if row["state"] in ("verified", "removed"):
            self._cleanup(state, row, tx, preserve=True)
            return
        old, new = j["old_inode"], j.get("new_inode")
        observed = _inode(dest)
        if j["kind"] == "deploy":
            if observed == new and new is not None:
                if old is not None:
                    if _inode(slot) != old:
                        raise DeploymentError("old bundle identity lost; refusing destructive recovery")
                    _exchange(slot, dest)
                else:
                    if _inode(slot) is not None:
                        raise DeploymentError("unexpected recovery destination")
                    _rename(dest, slot)
            elif observed != old:
                raise DeploymentError("live directory changed during recovery")
        elif j["kind"] == "retire":
            if observed is None and _inode(slot) == old:
                _rename(slot, dest)
            elif observed != old:
                raise DeploymentError("retirement recovery conflict")
        else:
            raise DeploymentError("unknown recovery operation")
        self._update(conn, row["id"], state="failed", last_error="interrupted operation restored previous bundle")
        conn.commit()
        self._cleanup(state, row, tx)

    def _intent(self, state, row, tx, kind):
        dest = _absolute(row["deployed_path"])
        record = {"operation_key": row["operation_key"], "generation": row["generation"],
                  "kind": kind, "tx": tx.name, "old_inode": _inode(dest),
                  "new_inode": _inode(tx / "bundle") if kind == "deploy" else None}
        _atomic_json(self._journal_path(state, row), record)

    def _failed(self, conn, state, row, tx, exc):
        conn.rollback()
        current = self._row(conn, row["id"])
        self._recover(conn, state, current)
        current = self._row(conn, row["id"])
        if current["state"] not in ("verified", "removed"):
            self._update(conn, row["id"], state="failed", last_error=str(exc),
                         observed_hash=getattr(exc, "observed_hash", ""))
            conn.commit()
        if tx is not None and tx.exists():
            self._cleanup(state, row, tx)
        if not isinstance(exc, Exception):
            raise exc
        return self._result(conn, row["id"])

    def deploy(self, skill_id, version_id, target):
        with self._locked(target) as (conn, cfg, state):
            return self._deploy(conn, cfg, state, skill_id, version_id)

    def _deploy(self, conn, cfg, state, skill_id, version_id, restoring=False, source=None):
        skill = self._skill(conn, skill_id)
        if skill["scope"] == "workspace" and (
                cfg["scope"] != "workspace" or skill["workspace_id"] != cfg.get("workspace_id")):
            raise DeploymentError("private skill cannot escape its workspace")
        version = self._one(conn, "SELECT * FROM skill_versions WHERE id=? AND skill_id=?",
                            (version_id, skill_id))
        if version is None:
            raise DeploymentError("version does not belong to skill")
        old = self._one(conn, "SELECT * FROM skill_deployments WHERE skill_id=? AND target_id=?",
                        (skill_id, cfg["target_id"]))
        if old:
            self._row(conn, old["id"])
            self._recover(conn, state, old)
            old = self._row(conn, old["id"])
        dest = cfg["root_dir"] / skill["slug"]
        collision = self._one(conn, "SELECT id FROM skill_deployments WHERE deployed_path=? AND NOT (skill_id=? AND target_id=?)",
                              (str(dest), skill_id, cfg["target_id"]))
        if collision:
            raise DeploymentError("target path belongs to another deployment")
        now = time.time()
        conn.execute("BEGIN IMMEDIATE")
        if old is None:
            cur = conn.execute("""INSERT INTO skill_deployments
                (skill_id,skill_version_id,target_id,target_scope,workspace_id,root_dir,
                 deployed_path,desired_version_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (skill_id, version_id, cfg["target_id"],
                cfg["scope"], cfg.get("workspace_id"), str(cfg["root_dir"]),
                str(dest), version_id, now, now))
            old = self._row(conn, cur.lastrowid)
        previous = old["applied_version_id"]
        self._update(conn, old["id"], skill_version_id=version_id, desired_version_id=version_id,
            expected_current_hash=version["artifact_sha256"], state="pending",
            generation=old["generation"] + 1, operation_key=uuid.uuid4().hex,
            attempt_count=old["attempt_count"] + 1, next_retry_at=None, last_error="")
        conn.commit()
        row = self._row(conn, old["id"])
        self._update(conn, row["id"], state="applying")
        conn.commit()
        tx = None
        try:
            if skill["deleted_at"] is not None or skill["lifecycle"] != "active":
                raise DeploymentError("skill must be active before publishing")
            if version["review_status"] != "approved":
                raise DeploymentError("version must be explicitly approved")
            spec = self._spec(conn, version_id, skill)
            if _inode(dest) is not None:
                if previous is None:
                    raise DeploymentError("refusing to overwrite unmanaged skill directory")
                if not restoring:
                    self._check(self._spec(conn, previous, skill), dest)
            try:
                files = self._source(spec)
            except (DeploymentError, OSError):
                if source is None:
                    raise
                files, modes = self._scan(source)
                self._compare(spec, files, modes)
            tx = self._stage(state, spec, files)
            self._intent(state, row, tx, "deploy")
            slot = tx / "bundle"
            if _inode(dest) is None:
                _rename(slot, dest)
            else:
                _exchange(slot, dest)
            observed = self._check(spec, dest)
            if self.native_verify is not None:
                if self.native_verify(dest, cfg, version) is not True:
                    raise DeploymentError("native DSH list/get verification failed")
                observed = self._check(spec, dest)
            conn.execute("BEGIN IMMEDIATE")
            self._update(conn, row["id"], state="verified", applied_version_id=version_id,
                observed_hash=observed, last_verified_at=time.time(), last_error="")
            self._audit(conn, row, "skill.deploy.verified", previous, version_id)
            conn.commit()
            self._cleanup(state, row, tx, preserve=True)
            return self._result(conn, row["id"])
        except BaseException as exc:
            return self._failed(conn, state, row, tx, exc)

    def retire(self, skill_id, target):
        with self._locked(target) as (conn, cfg, state):
            row = self._one(conn, "SELECT * FROM skill_deployments WHERE skill_id=? AND target_id=?",
                            (skill_id, cfg["target_id"]))
            if row is None:
                raise DeploymentError("deployment not found")
            self._row(conn, row["id"])
            self._recover(conn, state, row)
            row = self._row(conn, row["id"])
            dest = _absolute(row["deployed_path"])
            if row["state"] == "removed" and _inode(dest) is None:
                return self._result(conn, row["id"])
            if row["applied_version_id"] is None:
                raise DeploymentError("cannot retire an unmanaged directory")
            if dest.exists():
                self._scan(dest)  # Reject links even when contents have drifted.
            self._update(conn, row["id"], state="applying", generation=row["generation"] + 1,
                         operation_key=uuid.uuid4().hex, attempt_count=row["attempt_count"] + 1)
            conn.commit()
            row = self._row(conn, row["id"])
            tx = None
            try:
                if _inode(dest) is not None:
                    tx = Path(tempfile.mkdtemp(prefix="tx-", dir=state))
                    self._intent(state, row, tx, "retire")
                    _rename(dest, tx / "bundle")
                if os.path.lexists(dest):
                    raise DeploymentError("retired directory is still discoverable")
                conn.execute("BEGIN IMMEDIATE")
                self._update(conn, row["id"], state="removed", observed_hash="", last_error="")
                self._audit(conn, row, "skill.retire", row["applied_version_id"], None)
                conn.commit()
                if tx is not None:
                    self._cleanup(state, row, tx, preserve=True)
                return self._result(conn, row["id"])
            except BaseException as exc:
                return self._failed(conn, state, row, tx, exc)

    def rollback(self, deployment_id):
        with self._connection() as conn:
            target = self._row(conn, deployment_id)["target_id"]
        with self._locked(target) as (conn, cfg, state):
            row = self._row(conn, deployment_id)
            self._recover(conn, state, row)
            row = self._row(conn, deployment_id)
            current = row["applied_version_id"]
            if current is None:
                raise DeploymentError("no successfully applied version to restore")
            version_id = current if row["state"] in ("removed", "failed") else None
            archive = None
            if version_id is None:
                records = conn.execute("SELECT details_json FROM skill_audit WHERE target_type='skill_deployment' AND target_id=? AND action='skill.deploy.verified' ORDER BY id DESC",
                                       (str(deployment_id),)).fetchall()
                for record in records:
                    detail = json.loads(record[0])
                    previous = detail.get("previous_version_id")
                    if detail.get("applied_version_id") == current and previous not in (None, current):
                        version_id = previous
                        archive = state / ("archive-%s-%s" % (deployment_id, detail["generation"])) / "bundle"
                        break
            else:
                archive = state / ("archive-%s-%s" % (deployment_id, row["generation"])) / "bundle"
            if version_id is None:
                raise DeploymentError("no previous successfully deployed version")
            return self._deploy(conn, cfg, state, row["skill_id"], version_id,
                                restoring=True, source=archive)

    def verify(self, deployment_id):
        with self._connection() as conn:
            target = self._row(conn, deployment_id)["target_id"]
        with self._locked(target) as (conn, cfg, state):
            row = self._row(conn, deployment_id)
            self._recover(conn, state, row)
            row = self._row(conn, deployment_id)
            dest = Path(row["deployed_path"])
            observed = ""
            try:
                _absolute(dest)
                if row["state"] == "removed":
                    if os.path.lexists(dest):
                        raise DriftError("retired directory reappeared in discovery root")
                    return self._result(conn, deployment_id)
                if row["applied_version_id"] is None:
                    raise DriftError("no applied version available for verification")
                skill = self._skill(conn, row["skill_id"])
                spec = self._spec(conn, row["applied_version_id"], skill)
                observed = self._check(spec, dest)
                if self.native_verify is not None:
                    if self.native_verify(dest, cfg, spec["version"]) is not True:
                        raise DriftError("native DSH list/get verification failed", observed)
                    observed = self._check(spec, dest)
                if row["desired_version_id"] == row["applied_version_id"]:
                    if row["expected_current_hash"] != observed:
                        raise DriftError("expected_current_hash differs from applied bundle", observed)
                    state_name, error = "verified", ""
                else:
                    state_name, error = "failed", "previous version intact; desired version is not applied"
                self._update(conn, deployment_id, state=state_name, observed_hash=observed,
                             last_verified_at=time.time(), last_error=error)
            except (DeploymentError, OSError, UnicodeError, KeyError, TypeError) as exc:
                self._update(conn, deployment_id, state="drift", observed_hash=getattr(exc, "observed_hash", observed), last_error=str(exc))
            conn.commit()
            return self._result(conn, deployment_id)


def _self_test():
    """All writes are confined to TemporaryDirectory, never production DB."""
    with tempfile.TemporaryDirectory(prefix="literature-deployer-test-") as temporary:
        base = Path(temporary)
        root = base / "skills"
        ws = str(uuid.uuid4())
        config = {"targets": {"local": {"root_dir": str(root), "scope": "workspace", "workspace_id": ws}},
                  "projectDir": str(base / "project"), "agentsHome": str(base / "agents"),
                  "dshHome": str(base / "dsh"), "customSkillDirs": [str(root)]}
        db = base / "test.sqlite"
        deployer = SkillDeployer(db, config)
        conn = sqlite3.connect(db)
        sid = str(uuid.uuid4())
        conn.execute("INSERT INTO skills(id,slug,scope,workspace_id,lifecycle,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                     (sid, "demo", "workspace", ws, "active", time.time(), time.time()))
        conn.commit()
        sequence = 0

        def version(body, extras=None):
            nonlocal sequence
            sequence += 1
            extras = extras or {}
            data = ("---\nname: demo\ndescription: Test deployment\n---\n" + body + "\n").encode()
            artifact = bundle_sha256(data, extras)
            rows = [{"rel_path": p, "size_bytes": len(b), "sha256": sha256_hex(b),
                     "mode": 0o755 if p.endswith(".sh") else 0o644, "is_symlink": 0}
                    for p, b in sorted(extras.items())]
            package = base / ("package-%s" % sequence)
            package.mkdir()
            (package / "SKILL.md").write_bytes(data)
            for item in rows:
                file = package / item["rel_path"]
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(extras[item["rel_path"]])
                file.chmod(item["mode"])
            manifest = {"schema": 1, "slug": "demo", "version": sequence, "entry": "SKILL.md",
                        "files": rows, "bundle_sha256": artifact}
            cur = conn.execute("""INSERT INTO skill_versions
                (skill_id,version,skill_md,content_sha256,artifact_sha256,artifact_uri,manifest_json,review_status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""", (sid, sequence, data.decode(), sha256_hex(data), artifact,
                str(package) if extras else "", json.dumps(manifest), "approved", time.time()))
            vid = cur.lastrowid
            for item in rows:
                conn.execute("INSERT INTO skill_files(skill_version_id,rel_path,size_bytes,sha256,mode,is_symlink) VALUES (?,?,?,?,?,?)",
                    (vid, item["rel_path"], item["size_bytes"], item["sha256"], item["mode"], 0))
            conn.commit()
            return vid, data, package

        v1, first, _ = version("Version one")
        row = deployer.deploy(sid, v1, "local")
        assert row["state"] == "verified", row
        did = row["id"]
        print("PASS deploy single-file: state=verified desired=1 applied=1")
        assert deployer.verify(did)["state"] == "verified"
        print("PASS verify: state=verified")
        live = root / "demo"
        (live / "SKILL.md").write_bytes(first + b"tampered\n")
        drift = deployer.verify(did)
        assert drift["state"] == "drift" and drift["applied_version_id"] == v1
        print("PASS tamper then verify: state=drift applied=1 unchanged")
        (live / "SKILL.md").chmod(0o444)
        retired = deployer.retire(sid, "local")
        assert retired["state"] == "removed" and not live.exists()
        print("PASS retire: state=removed directory_exists=False")
        restored = deployer.rollback(did)
        assert restored["state"] == "verified" and (live / "SKILL.md").read_bytes() == first
        print("PASS rollback after retire: state=verified original_bytes_restored=True")

        v2, second, _ = version("Version two", {"A.txt": b"sort before SKILL.md\n", "scripts/run.sh": b"echo test\n"})
        row = deployer.deploy(sid, v2, "local")
        assert row["state"] == "verified", row
        assert (live / "scripts/run.sh").stat().st_mode & 0o777 == 0o755
        assert row["expected_current_hash"] == row["observed_hash"]
        rolled = deployer.rollback(did)
        assert rolled["state"] == "verified" and rolled["applied_version_id"] == v1
        assert not (live / "A.txt").exists()
        assert deployer.deploy(sid, v2, "local")["state"] == "verified"
        print("PASS bundle upgrade and previous-deployment rollback: hashes and modes match")

        v3, _, _ = version("Rejected at post-publication verification")
        deployer.native_verify = lambda path, target, ver: False
        failed = deployer.deploy(sid, v3, "local")
        assert failed["state"] == "failed", failed
        assert failed["desired_version_id"] == v3 and failed["applied_version_id"] == v2
        assert (live / "SKILL.md").read_bytes() == second
        assert (live / "A.txt").is_file()
        deployer.native_verify = None
        assert deployer.verify(did)["state"] == "failed"
        print("PASS injected post-publication failure: previous bundle and applied_version_id preserved")

        v4, _, package = version("Unsafe symlink", {"asset.txt": b"content"})
        (package / "asset.txt").unlink()
        (package / "asset.txt").symlink_to(package / "SKILL.md")
        failed = deployer.deploy(sid, v4, "local")
        assert failed["state"] == "failed" and failed["applied_version_id"] == v2
        assert (live / "SKILL.md").read_bytes() == second
        print("PASS symlink bundle rejected: previous bundle unchanged")

        v5, _, _ = version("Bad manifest path")
        manifest = json.loads(conn.execute("SELECT manifest_json FROM skill_versions WHERE id=?", (v5,)).fetchone()[0])
        manifest["files"] = [{"rel_path": "../escape", "size_bytes": 1,
                              "sha256": sha256_hex(b"x"), "mode": 420, "is_symlink": 0}]
        conn.execute("UPDATE skill_versions SET manifest_json=? WHERE id=?", (json.dumps(manifest), v5))
        conn.commit()
        failed = deployer.deploy(sid, v5, "local")
        assert failed["state"] == "failed" and failed["applied_version_id"] == v2
        print("PASS traversal manifest rejected: previous bundle unchanged")
        shadow = base / "project/.dsh/skills/different-directory"
        shadow.mkdir(parents=True)
        (shadow / "SKILL.md").write_bytes(first)
        warnings = deployer.detect_shadowing("demo", root)
        assert any(w["code"] == "shadowed" and w["rank"] == 100 for w in warnings)
        print("PASS shadow detection: frontmatter name matched at rank 100 < 300")

        from unittest.mock import patch
        with patch.dict(os.environ, {"DSH_AGENTS_HOME": str(base / "env-agents")}):
            assert SkillDeployer(db, config, ensure_schema=False).agents_home == base / "agents"
            env_config = dict(config)
            del env_config["agentsHome"]
            assert SkillDeployer(db, env_config, ensure_schema=False).agents_home == base / "env-agents"
            del os.environ["DSH_AGENTS_HOME"]
            assert SkillDeployer(db, env_config, ensure_schema=False).agents_home == Path.home() / ".agents"
        print("PASS agentsHome precedence: config > environment > homedir/.agents")

        assert deployer.deploy(sid, v2, "local")["state"] == "verified"
        v6, _, _ = version("Crash after atomic exchange")
        import sys
        sys.stdout.flush()
        pid = os.fork()
        if pid == 0:
            try:
                child = SkillDeployer(db, config, native_verify=lambda *args: os._exit(73))
                child.deploy(sid, v6, "local")
            finally:
                os._exit(99)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 73
        recovered = deployer.verify(did)
        assert recovered["state"] == "failed" and recovered["applied_version_id"] == v2
        assert (live / "SKILL.md").read_bytes() == second
        assert (live / "A.txt").is_file()
        print("PASS process crash after exchange: journal restored previous complete bundle")

        sys.stdout.flush()
        pid = os.fork()
        if pid == 0:
            try:
                original_rename = globals()["_rename"]
                def crash_after_retire(source, dest):
                    original_rename(source, dest)
                    if Path(source) == live and Path(dest).name == "bundle":
                        os._exit(74)
                globals()["_rename"] = crash_after_retire
                SkillDeployer(db, config).retire(sid, "local")
            finally:
                os._exit(99)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 74
        recovered = deployer.verify(did)
        assert recovered["applied_version_id"] == v2 and live.is_dir()
        assert (live / "SKILL.md").read_bytes() == second
        print("PASS process crash during retirement: journal restored live directory")
        (live / "extra.txt").write_bytes(b"unexpected")
        assert deployer.verify(did)["state"] == "drift"
        (live / "extra.txt").unlink()
        print("PASS extra unmanifested file detected as drift")

        v7, _, _ = version("Broken immutable hash")
        conn.execute("UPDATE skill_versions SET content_sha256=? WHERE id=?", ("0" * 64, v7))
        conn.commit()
        failed = deployer.deploy(sid, v7, "local")
        assert failed["state"] == "failed" and failed["applied_version_id"] == v2
        assert (live / "SKILL.md").read_bytes() == second
        print("PASS content hash mismatch rejected before publication")

        v8, _, _ = version("Unreviewed draft")
        conn.execute("UPDATE skill_versions SET review_status='pending' WHERE id=?", (v8,))
        conn.commit()
        failed = deployer.deploy(sid, v8, "local")
        assert failed["state"] == "failed" and failed["applied_version_id"] == v2
        print("PASS unreviewed version rejected")
        assert [p.name for p in root.iterdir()] == ["demo"]
        assert not list(base.rglob("journal-*.json"))
        assert not list(base.rglob("tx-*"))
        conn.close()
        print("SELF-TEST OK (temporary database and discovery roots only)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="exercise only temporary roots and DB")
    arguments = parser.parse_args()
    if arguments.self_test:
        _self_test()
    else:
        parser.print_help()
