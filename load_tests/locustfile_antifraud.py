import random
import uuid

from locust import HttpUser, between, task


class AntifraudUser(HttpUser):
    wait_time = between(0.001, 0.01)

    @task
    def check(self):
        payload = {
            "transfer_id": str(uuid.uuid4()),
            "sender_id": str(uuid.uuid4()),
            "receiver_id": str(uuid.uuid4()),
            "amount": random.randint(100, 100_000),
        }
        with self.client.post("/check", json=payload, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"status {response.status_code}")
            elif response.elapsed.total_seconds() > 0.05:
                response.failure(f"SLA exceeded: {response.elapsed.total_seconds()}")
