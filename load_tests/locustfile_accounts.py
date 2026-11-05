import uuid

from locust import HttpUser, between, task


class AccountsUser(HttpUser):
    wait_time = between(0.01, 0.1)
    account_id = None

    def on_start(self):
        response = self.client.post(
            "/accounts",
            headers={"X-User-Id": str(uuid.uuid4()), "Idempotency-Key": str(uuid.uuid4())},
        )
        if response.ok:
            self.account_id = response.json()["id"]

    @task
    def deposit(self):
        if self.account_id:
            self.client.post(
                f"/accounts/{self.account_id}/deposit",
                json={"amount": "1.00"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
