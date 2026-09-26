"""单证材料归档接口：按单证编号归档随附材料、记版本、按航次打包取走。"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from app.schemas import ArchiveBatchPayload, PageResult
from app.services.docarchive import ArchiveNotFound, DocArchiveService, OldVersionBlocked

router = APIRouter(prefix="/api/docarchive", tags=["单证材料归档"])

service = DocArchiveService()


@router.get("/summary")
def summary() -> dict[str, int]:
    """归档看板：归档单证数、版本数、材料份数、涉及航次数。"""
    return service.summary()


@router.get("/documents", response_model=PageResult[dict])
def list_documents(
    keyword: str | None = Query(default=None, description="按单证编号检索"),
    voyage: str | None = Query(default=None, description="按关联航次过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """归档单证列表：每份单证显示当前版本、版本数与单证状态。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_documents(keyword=keyword, voyage=voyage, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/voyages")
def list_voyages() -> dict[str, Any]:
    """已归档材料涉及的航次清单，给「按航次打包」做选项。"""
    return {"items": service.list_voyages()}


@router.post("/batch")
def submit_batch(payload: ArchiveBatchPayload) -> dict[str, Any]:
    """一次交多份：逐份校验、逐份回执；缺材料或挂不上单证编号的先挡下。"""
    if not payload.items:
        raise HTTPException(status_code=400, detail="本次提交没有内容，至少带一份单证材料")
    receipts = service.submit_batch([item.model_dump() for item in payload.items])
    return {"ok": all(receipt["ok"] for receipt in receipts), "receipts": receipts}


@router.get("/documents/{doc_no}/versions")
def list_versions(doc_no: str) -> dict[str, Any]:
    """一份单证的全部版本与材料清单；旧版本能翻出来看，只是不能再下载。"""
    result = service.list_versions(doc_no)
    if result is None:
        raise HTTPException(status_code=404, detail=f"单证 {doc_no} 还没有归档材料")
    return result


@router.get("/documents/{doc_no}/versions/{version}/files/{file_id}/download")
def download_file(doc_no: str, version: int, file_id: int) -> FileResponse:
    """下载材料：只允许当前版本；旧版本返回 409 并说明只能查看。"""
    try:
        path, name = service.download_file(doc_no, version, file_id)
    except OldVersionBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ArchiveNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=name)


@router.get("/documents/{doc_no}/versions/{version}/files/{file_id}/preview")
def preview_file(doc_no: str, version: int, file_id: int) -> dict[str, Any]:
    """查看材料内容：不限版本，旧版本也能翻出来看。"""
    try:
        return service.preview_file(doc_no, version, file_id)
    except ArchiveNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/voyages/{voyage_no}/package")
def package_voyage(voyage_no: str) -> Response:
    """按航次打包：该航次下各单证当前版本的材料打成一个 zip 取走。"""
    data = service.build_voyage_package(voyage_no)
    if data is None:
        raise HTTPException(status_code=404, detail=f"航次 {voyage_no} 下没有已归档的材料")
    filename = quote(f"{voyage_no}_材料包.zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
