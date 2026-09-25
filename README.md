# Предиктор изменений движения городского транспорта

Backend MVP для хакатона Московского транспорта. Сервис принимает телеметрию, сопоставляет её с расписанием, рассчитывает текущее отклонение, получает прогноз задержки на горизонте 10-15 минут из отдельного ML-модуля и публикует обновления через REST и WebSocket.

## Быстрый запуск

```bash
docker compose up --build
```

После запуска:

- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- health-check: http://localhost:8000/api/v1/health
- WebSocket: `ws://localhost:8000/api/v1/ws/updates`

Контейнер `mock-stream` каждые 5 секунд отправляет тестовую телеметрию. Демо-маршрут, остановки и расписание создаются автоматически при первом запуске.

## Поток данных

`mock/NDTP -> Backend -> matching/features -> ML service -> PostgreSQL + Redis -> REST/WebSocket`

Если Redis недоступен, Backend продолжает работать с PostgreSQL. Если ML-сервис не отвечает за заданный таймаут, применяется детерминированный fallback-прогноз и в ответе указывается версия `fallback-v1`.

## Пример телеметрии

```bash
curl -X POST http://localhost:8000/api/v1/telematics \
  -H "Content-Type: application/json" \
  -d '{"vehicle_id":"BUS-100","route_id":1,"trip_id":"M2-001","timestamp":"2026-09-25T09:05:00Z","lat":55.7558,"lon":37.6176,"speed":18.5,"heading":90,"nearest_stop_id":1,"door_status":"closed"}'
```

Основные эндпоинты находятся под `/api/v1`: `/vehicles`, `/routes`, `/schedules`, `/telematics`, `/telematics/batch`, `/stats`, `/health`.

## Локальная разработка

Требуется Python 3.12+.

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r backend/requirements-dev.txt
pytest
ruff check backend ml scripts tests
```

По умолчанию приложение ожидает PostgreSQL и Redis. Для автономного запуска можно задать `DATABASE_URL=sqlite+aiosqlite:///./transport.db` и оставить `REDIS_URL` пустым.

## Надёжность и производительность

- таймаут вызова ML по умолчанию 1.5 с;
- входной batch ограничен 1000 точками;
- индексы добавлены для поиска истории и последних прогнозов;
- внешние зависимости деградируют независимо, без падения API;
- `/stats` возвращает среднюю измеренную latency ML за время жизни процесса.

Для нагрузочной проверки можно отправлять batch-запросы на `/api/v1/telematics/batch`. Реальная производительность зависит от модели, числа воркеров и конфигурации PostgreSQL.
