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

## Обучение ML-модели и сабмит

Offline-контур строит признаки строго из телеметрии с `event_time <= T`, обучает CatBoost-регрессию на задержку в секундах, проверяет её на размеченном `test` и затем дообучает финальную модель на `train + test`.

```bash
pip install -r ml/requirements.txt
python -m ml.pipeline.train \
  --data-dir "C:/path/to/dataset" \
  --model-dir ml/models \
  --submission ml/outputs/submission.csv
```

Команда сохраняет:

- `ml/models/evaluation_metrics.json` — MAE модели и baselines на локальном test;
- `ml/models/competition_delay_model.cbm` — финальную модель для validate;
- `ml/models/competition_delay_model.metadata.json` — версию, признаки и параметры обучения;
- `ml/outputs/submission.csv` — файл `sample_id;prediction`, готовый к загрузке.

Повторно сформировать сабмит из сохранённой модели:

```bash
python -m ml.pipeline.submission \
  --data-dir "C:/path/to/dataset" \
  --model ml/models/competition_delay_model.cbm \
  --output ml/outputs/submission.csv
```

Основные признаки: текущее отклонение и его динамика, плановый горизонт, циклическое время суток, положение целевой остановки, расстояние и направление к ней, возраст последней телеметрии, а также статистики скорости/остановок/движения за окна 1, 3, 5 и 10 минут. Будущая телеметрия и фактическое время целевой остановки в признаки не попадают.

Текущий результат на локальном размеченном `test`: **MAE 53.09 сек**. Для сравнения, baseline `prediction = cur_dev_s` даёт **93.36 сек**, нулевой прогноз — **103.34 сек**. Метрика посчитана до дообучения финальной модели на `test`; поэтому test не использовался при получении этой оценки.

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
