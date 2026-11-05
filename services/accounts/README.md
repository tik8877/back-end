# Accounts

Счета, остатки, резервы и закрытие.

## Запуск

`poetry install`, `poetry run alembic -c services/accounts/alembic.ini upgrade head`, затем `poetry run uvicorn services.accounts.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/accounts/tests --cov=services/accounts/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/accounts && helm upgrade --install accounts infra/helm/accounts --namespace fpm-processing --atomic --wait --timeout 5m`.
