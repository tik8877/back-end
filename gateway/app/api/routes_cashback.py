from fastapi import APIRouter, Depends, Request

from gateway.app.deps import proxy_to, require_user


router = APIRouter(prefix="/api/v1/cashback", tags=["cashback"], dependencies=[Depends(require_user)])


@router.get("/expected")
async def expected(request: Request):
    return await proxy_to(request, "cashback", "/cashback/expected")


@router.get("/credited")
async def credited(request: Request):
    return await proxy_to(request, "cashback", "/cashback/credited")
