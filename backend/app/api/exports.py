from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from app.api.sessions import get_session_or_404
from app.deps import CurrentUser, DbSession
from app.services import audit
from app.services.exports import bundle, data as export_data, docx, excel, pdf

router = APIRouter(tags=["exports"])

Format = Literal["pdf", "xlsx", "docx"]

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

RENDERERS = {"pdf": pdf.render, "xlsx": excel.render, "docx": docx.render}


@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    db: DbSession,
    user: CurrentUser,
    format: Format = Query(default="pdf"),
    scope: export_data.Scope = Query(default="all"),
    include_cvs: bool = Query(
        default=False, description="Return a ZIP containing the report plus a CVs/ folder"
    ),
):
    session = await get_session_or_404(db, session_id)
    dataset = await export_data.build(db, session_id, scope)

    # ReportLab, openpyxl and python-docx are all synchronous and CPU-bound.
    document = await asyncio.to_thread(RENDERERS[format], dataset)

    stem = export_data.safe_filename(session.title) or "tricv"
    report_name = f"{stem}_{dataset.generated_at:%Y%m%d}.{format}"

    await audit.record(
        db,
        action="session.export",
        entity_type="recruitment_session",
        entity_id=session_id,
        user_id=user.id,
        details={
            "format": format,
            "scope": scope,
            "include_cvs": include_cvs,
            "candidates": len(dataset.candidates),
        },
    )
    await db.commit()

    if not include_cvs:
        return Response(
            content=document,
            media_type=MEDIA_TYPES[format],
            headers={"Content-Disposition": f'attachment; filename="{report_name}"'},
        )

    zip_name = f"{stem}_{dataset.generated_at:%Y%m%d}.zip"
    return StreamingResponse(
        bundle.stream_zip(dataset, document, report_name),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
