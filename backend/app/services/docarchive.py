"""单证材料归档业务规则：按单证编号建档、记版本，批量提交整批校验、整批入库。

几条硬规矩都收在这里：
- 材料必须挂得上单证编号（单证处理里查得到的才算数），挂不上先挡下；
- 必备材料缺了也整批挡下，回执里逐份列明缺什么，补齐再交；
- 整批要么全部入库要么一份不留，交到一半断掉不会留下半份材料；
- 同一份单证再交就是换版：旧版本留着只能查看，不再提供下载；
- 归档数据落盘保存，刷新页面、重启服务都丢不掉。
"""
from __future__ import annotations

import copy
import io
import zipfile
from datetime import datetime
from typing import Any

from app.schemas import ArchiveBatchPayload, ArchiveSubmitItem, MaterialPayload
from app.store import store

MODULE = "docarchive"
MANIFEST_MODULE = "manifest"

STATUS_ORDER = ["待审核", "已审核", "已退回"]
ACTION_RULES = {"审核通过": "已审核", "退回材料": "已退回"}

# 各类单证归档时必须具备的材料类型；没列到的单证类型按 DEFAULT 要求。
REQUIRED_MATERIALS = {
    "进口舱单": ["舱单", "提单", "装箱单"],
    "出口舱单": ["舱单", "报关单", "装箱单"],
}
DEFAULT_REQUIRED_MATERIALS = ["单证正文", "随附清单"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_filename(name: str) -> str:
    """材料名拼进 zip 路径前，把文件名里不能出现的字符换掉。"""
    cleaned = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in name).strip()
    return cleaned or "材料"


class DocarchiveService:
    def __init__(self) -> None:
        store.enable_persistence(MODULE)

    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        voyage: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("单证编号", ""))]
        if voyage:
            rows = [row for row in rows if voyage in str(row.get("关联航次", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._list_row(row) for row in rows[start:start + size]], total

    @staticmethod
    def _list_row(row: dict[str, Any]) -> dict[str, Any]:
        """列表行不带材料正文，版本细节走详情接口。"""
        return {key: value for key, value in row.items() if key != "versions"} | {
            "版本数": len(row.get("versions", []))
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_version(
        self, entry_id: int, version: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, None, f"归档 {entry_id} 不存在"
        record = next(
            (item for item in entry.get("versions", []) if int(item.get("version", 0)) == version),
            None,
        )
        if record is None:
            return entry, None, f"单证 {entry.get('单证编号')} 没有版本 {version}"
        return entry, record, ""

    # ---------- 批量提交 ----------

    def submit_batch(self, payload: ArchiveBatchPayload) -> tuple[bool, str, list[dict[str, Any]]]:
        items = payload.items
        if not items:
            return False, "本批没有需要归档的单证材料", []
        operator = payload.提交人.strip() or "未留名"

        receipts: list[dict[str, Any]] = []
        prepared: list[tuple[ArchiveSubmitItem, str, list[MaterialPayload]]] = []
        seen: set[str] = set()
        blocked = 0
        for idx, item in enumerate(items, 1):
            code = item.单证编号.strip()
            issues: list[str] = []
            missing: list[str] = []

            manifest_entry = self._find_manifest(code)
            if not code:
                issues.append("单证编号为空，材料挂不上")
            elif manifest_entry is None:
                issues.append(f"单证编号 {code} 在单证处理里查不到，材料挂不上")
            if code and code in seen:
                issues.append(f"单证编号 {code} 本批重复提交")
            if code:
                seen.add(code)

            materials = [m for m in item.材料 if m.名称.strip()]
            if not materials:
                issues.append("未随附任何材料")
            else:
                got = {m.类型.strip() for m in materials if m.类型.strip()}
                missing = [t for t in self._required_types(manifest_entry) if t not in got]
                if missing:
                    issues.append(f"缺少必备材料：{'、'.join(missing)}")

            voyage = (item.关联航次 or "").strip() or str(
                (manifest_entry or {}).get("关联航次") or ""
            ).strip()
            if not voyage:
                issues.append("关联航次缺失，无法按航次归档")

            if issues:
                blocked += 1
                receipts.append(self._receipt(idx, code, "被挡下", issues, missing))
            else:
                prepared.append((item, voyage, materials))
                receipts.append(self._receipt(idx, code, "校验通过", [], []))

        if blocked:
            message = f"整批被挡下：{blocked} 份不合格，一份都未入库；按回执补齐后整批重新提交"
            return False, message, receipts

        # 全部校验通过才入库：先留内存快照，落盘失败就整体还原，不留半份材料。
        backup = copy.deepcopy(store.rows(MODULE))
        try:
            for (item, voyage, materials), receipt in zip(prepared, receipts):
                _, version_no = self._upsert(item, voyage, materials, operator)
                receipt["结果"] = "已归档"
                receipt["版本号"] = version_no
            store.save(MODULE)
        except Exception:
            store.rows(MODULE)[:] = backup
            raise

        return True, f"{len(receipts)} 份单证材料已归档，回执逐份列明版本号", receipts

    def _upsert(
        self,
        item: ArchiveSubmitItem,
        voyage: str,
        materials: list[MaterialPayload],
        operator: str,
    ) -> tuple[dict[str, Any], int]:
        """同一份单证再次交材料就是换版：旧版本只留查看，新版本成为当前版并重新待审。"""
        code = item.单证编号.strip()
        rows = store.rows(MODULE)
        entry = next((row for row in rows if row.get("单证编号") == code), None)
        now = _now()
        record = {
            "version": 1,
            "上传时间": now,
            "说明": (item.说明 or "").strip(),
            "可取": True,
            "材料": [
                {"名称": m.名称.strip(), "类型": m.类型.strip() or "未分类", "内容": m.内容}
                for m in materials
            ],
        }
        if entry is None:
            entry = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "单证编号": code,
                "关联航次": voyage,
                "当前版本": 1,
                "材料份数": len(materials),
                "提交人": operator,
                "归档时间": now,
                "审核人员": "",
                "status": STATUS_ORDER[0],
                "pending": True,
                "abnormal": False,
                "versions": [record],
            }
            rows.append(entry)
            return entry, 1

        for old in entry.get("versions", []):
            old["可取"] = False
        record["version"] = int(entry.get("当前版本", 0)) + 1
        entry.setdefault("versions", []).append(record)
        entry["关联航次"] = voyage
        entry["当前版本"] = record["version"]
        entry["材料份数"] = len(materials)
        entry["提交人"] = operator
        entry["归档时间"] = now
        entry["审核人员"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        return entry, record["version"]

    @staticmethod
    def _receipt(
        idx: int, code: str, result: str, issues: list[str], missing: list[str]
    ) -> dict[str, Any]:
        return {
            "回执编号": f"RCPT-{datetime.now():%Y%m%d%H%M%S}-{idx:02d}",
            "单证编号": code or "（未填）",
            "结果": result,
            "版本号": None,
            "缺少材料": missing,
            "说明": "；".join(issues) if issues else "材料齐全，已挂到单证编号下",
            "时间": _now(),
        }

    @staticmethod
    def _find_manifest(code: str) -> dict[str, Any] | None:
        if not code:
            return None
        for row in store.rows(MANIFEST_MODULE):
            if str(row.get("单证编号", "")).strip() == code:
                return row
        return None

    @staticmethod
    def _required_types(manifest_entry: dict[str, Any] | None) -> list[str]:
        doc_type = str((manifest_entry or {}).get("单证类型") or "").strip()
        return REQUIRED_MATERIALS.get(doc_type, DEFAULT_REQUIRED_MATERIALS)

    # ---------- 审核动作 ----------

    def run_action(
        self, entry_id: int, action: str, operator: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"归档 {entry_id} 不存在"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于单证材料归档可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target == STATUS_ORDER[0]
        entry["abnormal"] = target == "已退回"
        if target == "已审核":
            entry["审核人员"] = operator or "值班审核"
        store.save(MODULE)
        return entry, f"单证材料已{action}"

    # ---------- 查看与打包 ----------

    @staticmethod
    def build_version_zip(entry: dict[str, Any], record: dict[str, Any]) -> bytes:
        """把一个版本的材料打成 zip：每份材料一个文本文件。"""
        code = str(entry.get("单证编号", ""))
        version_no = record.get("version", 0)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for mat in record.get("材料", []):
                name = _safe_filename(f"{code}-v{version_no}-{mat.get('名称', '材料')}.txt")
                zf.writestr(name, mat.get("内容") or "")
        return buf.getvalue()

    def package_voyage(self, voyage: str) -> tuple[bytes | None, str]:
        """按航次打包取走：只装各单证当前版本的材料，附一份归档清单。"""
        rows = [row for row in store.rows(MODULE) if str(row.get("关联航次", "")) == voyage]
        if not rows:
            return None, f"航次 {voyage} 下没有已归档的单证材料"
        lines = [f"航次 {voyage} 单证材料归档清单", f"打包时间：{_now()}", ""]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in rows:
                code = str(entry.get("单证编号", ""))
                current = int(entry.get("当前版本", 0))
                record = next(
                    (
                        item
                        for item in entry.get("versions", [])
                        if int(item.get("version", 0)) == current
                    ),
                    None,
                )
                if record is None:
                    continue
                materials = record.get("材料", [])
                lines.append(
                    f"{code}　版本 v{current}　状态 {entry.get('status', '')}　材料 {len(materials)} 份"
                )
                for mat in materials:
                    folder = _safe_filename(code)
                    name = _safe_filename(f"v{current}-{mat.get('名称', '材料')}.txt")
                    zf.writestr(f"{folder}/{name}", mat.get("内容") or "")
            zf.writestr("归档清单.txt", "\n".join(lines) + "\n")
        return buf.getvalue(), f"航次 {voyage} 已打包 {len(rows)} 份单证的当前版本材料"
