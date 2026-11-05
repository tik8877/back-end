# Payments

Переводы с синхронной проверкой, выяснением состояния операций и восстановлением незавершённых шагов.

## Запуск

`poetry install`, `poetry run alembic -c services/payments/alembic.ini upgrade head`, затем `poetry run uvicorn services.payments.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/payments/tests --cov=services/payments/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/payments && helm upgrade --install payments infra/helm/payments --namespace fpm-processing --atomic --wait --timeout 5m`.
