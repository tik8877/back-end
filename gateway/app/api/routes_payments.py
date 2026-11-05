from uuid import UUID

from fastapi import APIRouter, Depends, Request

from gateway.app.deps import proxy_to, require_user


router = APIRouter(prefix="/api/v1/payments", tags=["payments"], dependencies=[Depends(require_user)])


@router.post("/transfers")
async def create_transfer(request: Request):
    return await proxy_to(request, "payments", "/transfers")


@router.get("/transfers/{transfer_id}")
async def get_transfer(request: Request, transfer_id: UUID):
    return await proxy_to(request, "payments", f"/transfers/{transfer_id}")
