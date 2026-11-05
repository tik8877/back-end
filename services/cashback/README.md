# Cashback

Начисления по версиям правил, компенсации и атомарное завершение периода после сверки.

## Запуск

`poetry install`, `poetry run alembic -c services/cashback/alembic.ini upgrade head`, затем `poetry run uvicorn services.cashback.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/cashback/tests --cov=services/cashback/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/cashback && helm upgrade --install cashback infra/helm/cashback --namespace fpm-processing --atomic --wait --timeout 5m`.
