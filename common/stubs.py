import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Response


app = FastAPI(title="FPM local integration doubles")
sent_events: set[str] = set()


@app.post("/send")
async def send_notification(
    body: dict,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    mode: str | None = Header(None, alias="X-Test-Mode"),
):
    if mode == "delay":
        await asyncio.sleep(2)
    if mode == "limited":
        raise HTTPException(status_code=429, headers={"Retry-After": "2"})
    if mode == "error":
        raise HTTPException(status_code=503)
    if mode == "disconnect":
        return Response(status_code=444)
    duplicate = idempotency_key in sent_events
    sent_events.add(idempotency_key)
    return {"accepted": True, "duplicate": duplicate}


@app.get("/transactions")
async def transactions(
    cursor: str | None = None,
    mode: str | None = Header(None, alias="X-Test-Mode"),
):
    if mode == "delay":
        await asyncio.sleep(4)
    if mode == "limited":
        raise HTTPException(status_code=429, headers={"Retry-After": "1"})
    if mode == "error":
        raise HTTPException(status_code=503)
    if mode == "disconnect":
        return Response(status_code=444)
    page = int(cursor or "0")
    item_id = f"local-{page}"
    return {
        "items": [
            {
                "id": item_id,
                "account_id": str(uuid4()),
                "amount": "100.00",
                "currency": "RUB",
                "occurred_at": datetime.now(UTC).isoformat(),
            }
        ],
        "next_cursor": str(page + 1) if page < 1 else None,
        "total_pages": 2,
    }
