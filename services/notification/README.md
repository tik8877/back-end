# Notification

Подписки, доставка во внешний канал, отложенные попытки и очередь ручного разбора.

## Запуск

`poetry install`, `poetry run alembic -c services/notification/alembic.ini upgrade head`, затем `poetry run uvicorn services.notification.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/notification/tests --cov=services/notification/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/notification && helm upgrade --install notification infra/helm/notification --namespace fpm-processing --atomic --wait --timeout 5m`.
