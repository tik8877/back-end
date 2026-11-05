from uuid import UUID

from fastapi import APIRouter, Depends, Request

from gateway.app.deps import proxy_to, require_user


router = APIRouter(prefix="/api/v1/external", tags=["external"], dependencies=[Depends(require_user)])


@router.post("/sync")
async def start_sync(request: Request):
    return await proxy_to(request, "external", "/external/sync")


@router.get("/sync/{job_id}")
async def sync_status(request: Request, job_id: UUID):
    return await proxy_to(request, "external", f"/external/sync/{job_id}")


@router.post("/{action}")
async def integration_action(request: Request, action: str):
    if action not in {"connect", "disconnect"}:
        from gateway.app.core.errors import NotFoundError

        raise NotFoundError()
    return await proxy_to(request, "external", f"/external/{action}")
