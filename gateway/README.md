# Gateway

Проверяет RSA JWT, добавляет внутреннюю идентичность, ограничивает частоту запросов и безопасно проксирует их сервисам.

## Запуск

После заполнения `.env`: `poetry install`, затем `poetry run uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000`.

## Тестирование

`poetry run pytest gateway/tests --cov=gateway/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm upgrade --install gateway infra/helm/gateway --namespace fpm-processing --create-namespace --atomic --wait --timeout 5m`.
