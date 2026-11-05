# Ledger

Неизменяемый журнал проводок и курсорная выписка. Подача тестового события доступна через `/internal/events`.

## Запуск

`poetry install`, `poetry run alembic -c services/ledger/alembic.ini upgrade head`, затем `poetry run uvicorn services.ledger.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/ledger/tests --cov=services/ledger/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/ledger && helm upgrade --install ledger infra/helm/ledger --namespace fpm-processing --atomic --wait --timeout 5m`.
