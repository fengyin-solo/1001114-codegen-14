"""单证材料归档业务规则：按单证编号存版本、挡缺失、按航次打包。

设计要点：
- 元数据用标准库 sqlite3 持久化，文件落在 backend/data/docarchive_files/，
  页面刷新、服务重启后已归档的材料都还在；
- 每份单证的提交「先暂存、再落库、整体就位」，任何一步中断都整体清理，
  不会留下半份材料；
- 同一单证编号每交一次版本号加一，旧版本只能查看（预览），不能再下载；
- 材料缺失、单证编号挂不上的提交会被挡下，回执里列明缺什么，补齐再交。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import re
import shutil
import sqlite3
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.store import store

MANIFEST_MODULE = "manifest"
DOC_NO_KEY = "单证编号"
VOYAGE_KEY = "关联航次"
DOC_TYPE_KEY = "单证类型"

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DOCARCHIVE_DATA_DIR", str(BACKEND_DIR / "data")))
DB_PATH = DATA_DIR / "docarchive.db"
FILE_ROOT = DATA_DIR / "docarchive_files"
STAGING_DIR = FILE_ROOT / "_staging"

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_DOC = 20
PREVIEW_BYTES = 8192


class ArchiveNotFound(Exception):
    """单证归档或材料文件不存在。"""


class OldVersionBlocked(Exception):
    """旧版本材料只能查看、不能下载时被拦下。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_file_name(name: str, fallback: str) -> str:
    """只保留文件名部分，剥掉路径，避免写到归档目录外。"""
    cleaned = Path(name.strip()).name
    return cleaned or fallback


def _dir_name(doc_no: str, version: int) -> str:
    """版本目录名：单证编号可能带斜杠等字符，做个清洗再加短哈希防撞名。"""
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", doc_no)[:40] or "doc"
    digest = hashlib.sha1(doc_no.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}-v{version}"


class DocArchiveService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        FILE_ROOT.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._sweep_orphans()

    # ---------- 持久化基础设施 ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_no TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    voyage TEXT NOT NULL DEFAULT '',
                    doc_type TEXT NOT NULL DEFAULT '',
                    remark TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(doc_no, version)
                );
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _sweep_orphans(self) -> None:
        """启动时清掉上次提交中断留下的暂存目录和没挂上版本的文件目录。"""
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            keep = {
                str(row[0]).split("/")[0]
                for row in conn.execute("SELECT DISTINCT stored_path FROM files")
            }
        for child in FILE_ROOT.iterdir():
            if child.is_dir() and child.name not in keep and child.name != STAGING_DIR.name:
                shutil.rmtree(child, ignore_errors=True)

    # ---------- 提交归档 ----------

    def submit_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """一次交多份：逐份处理、逐份回执，单份之间互不影响。"""
        return [self._submit_one(item) for item in items]

    def _submit_one(self, item: dict[str, Any]) -> dict[str, Any]:
        doc_no = str(item.get("doc_no") or "").strip()
        materials = item.get("materials") or []
        remark = str(item.get("remark") or "").strip()

        manifest_row, decoded, missing = self._validate(doc_no, materials)
        if missing:
            return {
                "doc_no": doc_no,
                "ok": False,
                "version": None,
                "message": f"{doc_no or '未填单证编号'} 已挡下，缺：{'；'.join(missing)}，补齐后重新交",
                "missing": missing,
            }

        assert manifest_row is not None  # 校验通过说明单证编号挂得上
        voyage = str(manifest_row.get(VOYAGE_KEY) or "")
        doc_type = str(manifest_row.get(DOC_TYPE_KEY) or "")

        with self._lock:
            version = self._next_version(doc_no)
            folder = _dir_name(doc_no, version)
            staging = STAGING_DIR / folder
            final_dir = FILE_ROOT / folder
            try:
                # 1) 全部材料先写进暂存目录（单文件也是先写 .part 再替换，不留半截文件）
                staging.mkdir(parents=True, exist_ok=False)
                for entry in decoded:
                    target = staging / entry["name"]
                    part = target.with_name(target.name + ".part")
                    part.write_bytes(entry["content"])
                    os.replace(part, target)
                # 2) 元数据事务落库，要么整份版本进去要么整体回滚
                self._insert_version(doc_no, version, voyage, doc_type, remark, folder, decoded)
                # 3) 材料整体就位；这步失败则连目录带库记录一起清掉
                os.rename(staging, final_dir)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                shutil.rmtree(final_dir, ignore_errors=True)
                self._delete_version_quietly(doc_no, version)
                return {
                    "doc_no": doc_no,
                    "ok": False,
                    "version": None,
                    "message": f"{doc_no} 归档中断，已整体清理，没有留下半份材料，请重新提交",
                    "missing": [],
                }

        return {
            "doc_no": doc_no,
            "ok": True,
            "version": version,
            "message": f"{doc_no} 已归档为 v{version}（材料 {len(decoded)} 份）",
            "missing": [],
        }

    def _validate(
        self, doc_no: str, materials: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
        """把要挡下的情况一次查全：单证编号挂不上、材料缺失、内容解析不了。"""
        missing: list[str] = []
        manifest_row: dict[str, Any] | None = None
        if not doc_no:
            missing.append("单证编号")
        else:
            manifest_row = next(
                (row for row in store.rows(MANIFEST_MODULE) if str(row.get(DOC_NO_KEY)) == doc_no),
                None,
            )
            if manifest_row is None:
                missing.append(f"单证编号 {doc_no} 在单证处理里查不到，材料挂不上")

        if not materials:
            missing.append("随附材料文件")
        elif len(materials) > MAX_FILES_PER_DOC:
            missing.append(f"材料份数超出单次上限 {MAX_FILES_PER_DOC} 份，请分批提交")

        decoded: list[dict[str, Any]] = []
        used_names: set[str] = set()
        for index, material in enumerate(materials, start=1):
            name = str(material.get("name") or "").strip()
            if not name:
                missing.append(f"第 {index} 份材料的文件名")
                continue
            raw = str(material.get("content_base64") or "")
            if "base64," in raw:  # 兼容 data URL 写法
                raw = raw.split("base64,", 1)[1]
            if not raw:
                missing.append(f"材料《{name}》的内容")
                continue
            try:
                content = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                missing.append(f"材料《{name}》的内容（base64 解析失败，需重新导出）")
                continue
            if not content:
                missing.append(f"材料《{name}》的内容（文件为空）")
                continue
            if len(content) > MAX_FILE_BYTES:
                missing.append(f"材料《{name}》（超过 10MB，需压缩后重传）")
                continue
            unique = self._dedupe_name(_safe_file_name(name, f"material_{index}"), used_names)
            decoded.append({
                "name": unique,
                "content": content,
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        return manifest_row, decoded, missing

    @staticmethod
    def _dedupe_name(name: str, used: set[str]) -> str:
        """同一次提交里重名的材料自动加序号，避免互相覆盖。"""
        candidate = name
        counter = 2
        while candidate in used:
            stem, dot, suffix = name.rpartition(".")
            candidate = f"{stem} ({counter}).{suffix}" if dot else f"{name} ({counter})"
            counter += 1
        used.add(candidate)
        return candidate

    def _insert_version(
        self,
        doc_no: str,
        version: int,
        voyage: str,
        doc_type: str,
        remark: str,
        folder: str,
        decoded: list[dict[str, Any]],
    ) -> None:
        now = _now()
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            cursor = conn.execute(
                "INSERT INTO versions(doc_no, version, voyage, doc_type, remark, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (doc_no, version, voyage, doc_type, remark, now),
            )
            version_id = cursor.lastrowid
            for entry in decoded:
                conn.execute(
                    "INSERT INTO files(version_id, name, size, sha256, stored_path, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        version_id,
                        entry["name"],
                        len(entry["content"]),
                        entry["sha256"],
                        f"{folder}/{entry['name']}",
                        now,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _delete_version_quietly(self, doc_no: str, version: int) -> None:
        """归档中断后的补偿清理：把已落库的半份版本记录删掉。"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM versions WHERE doc_no = ? AND version = ?",
                    (doc_no, version),
                ).fetchone()
                if row is not None:
                    conn.execute("DELETE FROM files WHERE version_id = ?", (row[0],))
                    conn.execute("DELETE FROM versions WHERE id = ?", (row[0],))
        except Exception:
            pass

    def _next_version(self, doc_no: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM versions WHERE doc_no = ?", (doc_no,)
            ).fetchone()
        return int(row[0] or 0) + 1

    def _latest_version(self, doc_no: str) -> int:
        return self._next_version(doc_no) - 1

    # ---------- 查询 ----------

    def summary(self) -> dict[str, int]:
        with self._connect() as conn:
            documents = conn.execute("SELECT COUNT(DISTINCT doc_no) FROM versions").fetchone()[0]
            versions = conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0]
            files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            voyages = conn.execute(
                "SELECT COUNT(DISTINCT voyage) FROM versions WHERE voyage != ''"
            ).fetchone()[0]
        return {"documents": documents, "versions": versions, "files": files, "voyages": voyages}

    def list_voyages(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT voyage FROM versions WHERE voyage != '' ORDER BY voyage"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def list_documents(
        self,
        *,
        keyword: str | None = None,
        voyage: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._connect() as conn:
            versions = conn.execute(
                "SELECT * FROM versions ORDER BY doc_no, version"
            ).fetchall()
            file_counts = dict(
                conn.execute("SELECT version_id, COUNT(*) FROM files GROUP BY version_id").fetchall()
            )

        docs: dict[str, dict[str, Any]] = {}
        for row in versions:
            entry = docs.setdefault(row["doc_no"], {"version_count": 0, "latest": None})
            entry["version_count"] += 1
            if entry["latest"] is None or row["version"] > entry["latest"]["version"]:
                entry["latest"] = row

        status_map = {
            str(row.get(DOC_NO_KEY)): str(row.get("status") or "")
            for row in store.rows(MANIFEST_MODULE)
        }
        items: list[dict[str, Any]] = []
        for doc_no, entry in docs.items():
            latest = entry["latest"]
            items.append({
                "doc_no": doc_no,
                "doc_type": latest["doc_type"],
                "voyage": latest["voyage"],
                "latest_version": latest["version"],
                "version_count": entry["version_count"],
                "file_count": int(file_counts.get(latest["id"], 0)),
                "last_submit": latest["created_at"],
                "manifest_status": status_map.get(doc_no, "未登记"),
            })
        if keyword:
            items = [item for item in items if keyword in item["doc_no"]]
        if voyage:
            items = [item for item in items if item["voyage"] == voyage]
        items.sort(key=lambda item: item["last_submit"], reverse=True)
        total = len(items)
        start = max(page - 1, 0) * size
        return items[start:start + size], total

    def list_versions(self, doc_no: str) -> dict[str, Any] | None:
        """一份单证的全部版本：旧版本也翻得出来，只是标了不可下载。"""
        with self._connect() as conn:
            versions = conn.execute(
                "SELECT * FROM versions WHERE doc_no = ? ORDER BY version DESC", (doc_no,)
            ).fetchall()
            if not versions:
                return None
            files = conn.execute(
                "SELECT f.* FROM files f JOIN versions v ON f.version_id = v.id"
                " WHERE v.doc_no = ? ORDER BY f.id",
                (doc_no,),
            ).fetchall()

        latest = max(int(row["version"]) for row in versions)
        files_by_version: dict[int, list[dict[str, Any]]] = {}
        for row in files:
            files_by_version.setdefault(int(row["version_id"]), []).append({
                "id": row["id"],
                "name": row["name"],
                "size": row["size"],
                "sha256": row["sha256"],
                "created_at": row["created_at"],
            })
        return {
            "doc_no": doc_no,
            "latest_version": latest,
            "versions": [
                {
                    "version": row["version"],
                    "voyage": row["voyage"],
                    "doc_type": row["doc_type"],
                    "remark": row["remark"],
                    "created_at": row["created_at"],
                    "downloadable": int(row["version"]) == latest,
                    "files": files_by_version.get(int(row["id"]), []),
                }
                for row in versions
            ],
        }

    # ---------- 查看与下载 ----------

    def _find_file(self, doc_no: str, version: int, file_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT f.* FROM files f JOIN versions v ON f.version_id = v.id"
                " WHERE v.doc_no = ? AND v.version = ? AND f.id = ?",
                (doc_no, version, file_id),
            ).fetchone()

    def download_file(self, doc_no: str, version: int, file_id: int) -> tuple[Path, str]:
        """只有当前版本能下载；旧版本拦下并说明原因。"""
        row = self._find_file(doc_no, version, file_id)
        if row is None:
            raise ArchiveNotFound(f"{doc_no} v{version} 没有这份材料")
        latest = self._latest_version(doc_no)
        if version != latest:
            raise OldVersionBlocked(
                f"{doc_no} v{version} 是旧版本，只能查看不能再下载；当前版本为 v{latest}"
            )
        path = FILE_ROOT / str(row["stored_path"])
        if not path.exists():
            raise ArchiveNotFound(f"{doc_no} v{version} 的材料文件已缺失，请联系管理员")
        return path, str(row["name"])

    def preview_file(self, doc_no: str, version: int, file_id: int) -> dict[str, Any]:
        """查看不限版本：旧版本的材料也能翻出来看内容。"""
        row = self._find_file(doc_no, version, file_id)
        if row is None:
            raise ArchiveNotFound(f"{doc_no} v{version} 没有这份材料")
        path = FILE_ROOT / str(row["stored_path"])
        if not path.exists():
            raise ArchiveNotFound(f"{doc_no} v{version} 的材料文件已缺失，请联系管理员")
        raw = path.read_bytes()[:PREVIEW_BYTES]
        return {
            "doc_no": doc_no,
            "version": version,
            "name": str(row["name"]),
            "size": row["size"],
            "sha256": row["sha256"],
            "text": raw.decode("utf-8", errors="replace"),
            "truncated": int(row["size"]) > PREVIEW_BYTES,
        }

    # ---------- 按航次打包 ----------

    def build_voyage_package(self, voyage: str) -> bytes | None:
        """把一个航次下各单证当前版本的材料打成 zip；没有材料时返回 None。"""
        with self._connect() as conn:
            versions = conn.execute(
                "SELECT * FROM versions WHERE voyage = ? ORDER BY doc_no, version", (voyage,)
            ).fetchall()
            if not versions:
                return None
            files = conn.execute(
                "SELECT f.*, v.doc_no AS doc_no, v.version AS version FROM files f"
                " JOIN versions v ON f.version_id = v.id WHERE v.voyage = ? ORDER BY f.id",
                (voyage,),
            ).fetchall()

        latest_by_doc: dict[str, int] = {}
        for row in versions:
            doc_no = str(row["doc_no"])
            latest_by_doc[doc_no] = max(latest_by_doc.get(doc_no, 0), int(row["version"]))

        lines = [f"航次 {voyage} 单证材料打包清单", f"生成时间：{_now()}", ""]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for row in files:
                doc_no = str(row["doc_no"])
                version = int(row["version"])
                if version != latest_by_doc[doc_no]:
                    continue  # 只打当前版本，旧版本留在归档里查看
                path = FILE_ROOT / str(row["stored_path"])
                arcname = f"{doc_no}/v{version}/{row['name']}"
                if path.exists():
                    zf.write(path, arcname)
                    lines.append(f"{doc_no} v{version} {row['name']}（{row['size']} 字节）")
                else:
                    lines.append(f"{doc_no} v{version} {row['name']}（文件缺失，未打入）")
            zf.writestr("材料清单.txt", "\n".join(lines) + "\n")
        return buffer.getvalue()
