from fastapi import APIRouter, Depends, Request

from gateway.app.deps import mark_anonymous, proxy_to, require_user


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", dependencies=[Depends(mark_anonymous)])
async def register(request: Request):
    return await proxy_to(request, "auth", "/auth/register")


@router.post("/login", dependencies=[Depends(mark_anonymous)])
async def login(request: Request):
    return await proxy_to(request, "auth", "/auth/login")


@router.post("/refresh", dependencies=[Depends(mark_anonymous)])
async def refresh(request: Request):
    return await proxy_to(request, "auth", "/auth/refresh")


@router.post("/logout", dependencies=[Depends(require_user)])
async def logout(request: Request):
    return await proxy_to(request, "auth", "/auth/logout")
