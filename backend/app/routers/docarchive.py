"""单证材料归档接口：批量交材料、逐份回执、版本查看与按航次打包。

固定路径（/submit、/export、/package）声明在 /{entry_id} 之前，
否则 "submit" 会被当成 entry_id 匹配，走不到正确的处理函数。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, ArchiveBatchPayload, EntryPayload, PageResult
from app.services.docarchive import DocarchiveService

router = APIRouter(prefix="/api/docarchive", tags=["单证材料归档"])

service = DocarchiveService()

LIST_FIELDS = ["单证编号", "关联航次", "当前版本", "材料份数", "提交人", "归档时间", "审核人员", "归档状态"]
STATUSES = ["待审核", "已审核", "已退回"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按单证编号检索"),
    voyage: str | None = Query(default=None, description="按关联航次过滤"),
    status: str | None = Query(default=None, description="待审核、已审核、已退回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按单证编号、航次与状态过滤归档列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, voyage=voyage, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/submit")
def submit_batch(payload: ArchiveBatchPayload) -> dict[str, Any]:
    """一次交多份：逐份校验、逐份回执；有缺漏整批挡下，一份都不入库。"""
    ok, message, receipts = service.submit_batch(payload)
    return {"ok": ok, "message": message, "回执": receipts}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出归档清单：返回当前全量数据（不含材料正文）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "docarchive", "total": total, "items": items}


@router.get("/package")
def package_voyage(voyage: str = Query(..., description="航次编号")) -> Response:
    """按航次打包取走：zip 里是该航次各单证当前版本的材料与归档清单。"""
    data, message = service.package_voyage(voyage.strip())
    if data is None:
        raise HTTPException(status_code=404, detail=message)
    filename = quote(f"{voyage.strip()}-单证材料包.zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条归档明细（含全部版本）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"归档 {entry_id} 不存在")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条归档执行审核通过、退回材料；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    operator = str(payload.values.get("operator") or "").strip()
    entry, message = service.run_action(entry_id, action, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}/versions/{version}")
def view_version(entry_id: int, version: int) -> dict[str, Any]:
    """查看任意版本的材料内容：旧版本留着就是为了能翻出来看。"""
    entry, record, message = service.get_version(entry_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail=message)
    return {
        "单证编号": entry["单证编号"],
        "关联航次": entry["关联航次"],
        "归档状态": entry["status"],
        **record,
    }


@router.get("/{entry_id}/versions/{version}/download")
def download_version(entry_id: int, version: int) -> Response:
    """下载某个版本的材料包；换版后旧版本只能查看，下载会被拦下。"""
    entry, record, message = service.get_version(entry_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail=message)
    if not record.get("可取"):
        raise HTTPException(status_code=409, detail="旧版本材料仅可查看，不能再下载；请取当前版本")
    data = service.build_version_zip(entry, record)
    filename = quote(f"{entry['单证编号']}-v{version}.zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
