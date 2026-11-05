# Antifraud

Детерминированные решения на основе Redis, списка 115-ФЗ и динамических правил.

## Запуск

После настройки Redis: `poetry install`, затем `poetry run uvicorn services.antifraud.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/antifraud/tests --cov=services/antifraud/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/antifraud && helm upgrade --install antifraud infra/helm/antifraud --namespace fpm-processing --atomic --wait --timeout 5m`.
