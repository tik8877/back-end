from locust import HttpUser, between, task


class GatewayUser(HttpUser):
    wait_time = between(0.01, 0.1)

    @task
    def live(self):
        self.client.get("/health/live")
