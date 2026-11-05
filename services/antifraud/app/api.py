from fastapi import APIRouter, Request

from services.antifraud.app.schemas import CheckRequest, CheckResponse


router = APIRouter(tags=["antifraud"])


@router.post("/check", response_model=CheckResponse)
async def check(request: Request, body: CheckRequest):
    return await request.app.state.decision_service.check(body)
