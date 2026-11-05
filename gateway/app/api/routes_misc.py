from fastapi import APIRouter, Depends, Request

from gateway.app.deps import proxy_to, require_user


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_user)])


@router.post("/antifraud/check", tags=["antifraud"])
async def antifraud(request: Request):
    return await proxy_to(request, "antifraud", "/check")


@router.post("/notifications/{action}", tags=["notification"])
async def notification_action(request: Request, action: str):
    if action not in {"subscribe", "unsubscribe"}:
        from gateway.app.core.errors import NotFoundError

        raise NotFoundError()
    return await proxy_to(request, "notification", f"/notifications/{action}")
