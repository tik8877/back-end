import asyncio

from fastapi import FastAPI, HTTPException, Request, Response


app = FastAPI(title="Antifraud test double")


@app.post("/check")
async def check(request: Request):
    mode = request.headers.get("X-Test-Mode", "ok")
    if mode == "delay":
        await asyncio.sleep(float(request.headers.get("X-Test-Delay", "1")))
    if mode == "limited":
        raise HTTPException(status_code=429)
    if mode == "error":
        raise HTTPException(status_code=503)
    if mode == "disconnect":
        return Response(status_code=444)
    return {"allowed": True, "reason_code": "allowed", "rules_version": "stub"}
