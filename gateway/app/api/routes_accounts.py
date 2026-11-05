from uuid import UUID

from fastapi import APIRouter, Depends, Request

from gateway.app.deps import proxy_to, require_user


router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"], dependencies=[Depends(require_user)])


@router.api_route("", methods=["GET", "POST"])
async def accounts(request: Request):
    return await proxy_to(request, "accounts", "/accounts")


@router.get("/{account_id}")
async def account(request: Request, account_id: UUID):
    return await proxy_to(request, "accounts", f"/accounts/{account_id}")


@router.post("/{account_id}/{operation}")
async def account_operation(request: Request, account_id: UUID, operation: str):
    if operation not in {"deposit", "withdraw", "reserve", "close"}:
        from gateway.app.core.errors import NotFoundError

        raise NotFoundError()
    return await proxy_to(request, "accounts", f"/accounts/{account_id}/{operation}")


@router.post("/reservations/{reservation_id}/{operation}")
async def reservation_operation(request: Request, reservation_id: UUID, operation: str):
    if operation not in {"confirm", "cancel"}:
        from gateway.app.core.errors import NotFoundError

        raise NotFoundError()
    return await proxy_to(
        request,
        "accounts",
        f"/accounts/reservations/{reservation_id}/{operation}",
    )
