# External

Постраничная синхронизация EveryPay с сохранением курсора и версий исправленных транзакций. Реквизиты источника задаются только через секреты окружения.

## Запуск

`poetry install`, `poetry run alembic -c services/external/alembic.ini upgrade head`, затем `poetry run uvicorn services.external.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/external/tests --cov=services/external/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/external && helm upgrade --install external infra/helm/external --namespace fpm-processing --atomic --wait --timeout 5m`.
