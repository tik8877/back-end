# Auth

Регистрация, вход, одноразовое обновление токенов, выход и JWKS. Требуются RSA-ключи через переменные окружения или смонтированные файлы.

## Запуск

`poetry install`, `poetry run alembic -c services/auth/alembic.ini upgrade head`, затем `poetry run uvicorn services.auth.app.main:app --port 8000`.

## Тестирование

`poetry run pytest services/auth/tests --cov=services/auth/app --cov-report=term --cov-fail-under=80`.

## Развёртывание

`helm dependency build infra/helm/auth && helm upgrade --install auth infra/helm/auth --namespace fpm-processing --atomic --wait --timeout 5m`.
