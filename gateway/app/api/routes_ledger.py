from uuid import UUID

from fastapi import APIRouter, Depends, Request

from gateway.app.deps import proxy_to, require_user


router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"], dependencies=[Depends(require_user)])


@router.get("/statements/{account_id}")
async def statement(request: Request, account_id: UUID):
    return await proxy_to(request, "ledger", f"/statements/{account_id}")
