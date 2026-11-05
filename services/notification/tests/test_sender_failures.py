import httpx
import pytest

from services.notification.app.sender import DeliveryFailed, TelegramSender


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "reason"),
    [(429, "limited"), (503, "receiver_unavailable"), (400, "receiver_rejected")],
)
async def test_receiver_errors_are_classified(status, reason):
    async def handler(request):
        return httpx.Response(status, headers={"Retry-After": "2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = TelegramSender(client, "http://telegram", 0.1)
        with pytest.raises(DeliveryFailed) as error:
            await sender.send("event", "user", "type")
    assert error.value.reason == reason


@pytest.mark.asyncio
async def test_successful_receiver_returns_normally():
    async def handler(request):
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await TelegramSender(client, "http://telegram", 0.1).send("event", "user", "type")
