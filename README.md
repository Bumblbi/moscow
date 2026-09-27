# Предиктор изменений движения городского транспорта

Комплексная система для хакатона Московского транспорта: диспетчерский React-дашборд, Backend и отдельный ML-модуль. Сервис принимает телеметрию, сопоставляет её с расписанием, рассчитывает текущее отклонение, получает прогноз задержки на горизонте 10-15 минут и публикует обновления в реальном времени.

## Быстрый запуск

```bash
docker compose up --build
```

После запуска:

- диспетчерский дашборд: http://localhost:8080
- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- health-check: http://localhost:8000/api/v1/health
- WebSocket: `ws://localhost:8000/api/v1/ws/updates`
- NDTP TCP listener: `localhost:9201`

Контейнер `mock-stream` каждые 5 секунд отправляет тестовую телеметрию. Демо-маршрут, остановки и расписание создаются автоматически при первом запуске.

### Сценарий демонстрации

1. Откройте http://localhost:8080 и дождитесь статуса «Данные в реальном времени».
2. На карте появится тестовое ТС `BUS-100`; его положение, скорость и прогноз обновляются каждые 5 секунд.
3. Выберите ТС на карте или в приоритетной очереди, чтобы открыть карточку с причиной риска, горизонтом прогноза, историей и параметрами модели.
4. Перейдите во вкладку «Маршруты» для сводки по маршрутной сети или в «Мониторинг» для проверки состояния сервисов и latency.
5. Для проверки API и ручной подачи телеметрии используйте Swagger по адресу http://localhost:8000/docs.

Если WebSocket временно недоступен, интерфейс сохраняет последнее состояние и продолжает обновлять данные через REST каждые 30 секунд.

## Поток данных

`HTTP mock или NDTP TCP -> Backend -> matching/features -> ML service -> PostgreSQL + Redis -> REST/WebSocket -> React dashboard`

Если Redis недоступен, Backend продолжает работать с PostgreSQL. Если ML-сервис не отвечает за заданный таймаут, применяется детерминированный fallback-прогноз и в ответе указывается версия `fallback-v1`.

### Проверка потока NDTP

Backend слушает бинарный NDTP на TCP-порту `9201`, разбирает handshake/realtime-кадры и ячейку `G6CellNav00`. Для запуска официального эмулятора:

```bash
docker load -i /path/to/ndtp-telemetry-emulator.tar
docker run --rm -p 18080:18080 --add-host=host.docker.internal:host-gateway \
  --name ndtp-emu ndtp-telemetry-emulator:1.0
curl -X POST http://localhost:18080/api/config \
  -H "Content-Type: application/json" \
  -d '{"targetHost":"host.docker.internal","targetPort":9201,"units":[{"unitId":1166336,"intervalMs":5000,"autoGenerate":true,"cells":[]}]}'
```

На дашборде появится `NDTP-1166336`. Счётчик принятых пакетов доступен в `/api/v1/stats`, состояние listener — в `/api/v1/health`.

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
sphinx-build -b html docs/source docs/_build/html -W
```

По умолчанию приложение ожидает PostgreSQL и Redis. Для автономного запуска можно задать `DATABASE_URL=sqlite+aiosqlite:///./transport.db` и оставить `REDIS_URL` пустым.

## Надёжность и производительность

- таймаут вызова ML по умолчанию 1.5 с;
- входной batch ограничен 1000 точками;
- индексы добавлены для поиска истории и последних прогнозов;
- внешние зависимости деградируют независимо, без падения API;
- `/stats` возвращает среднюю измеренную latency ML за время жизни процесса.

ML health-check также возвращает `model_loaded`, `model_version` и число признаков. В штатном Docker-запуске ожидаются `model_loaded: true`, `model_version: catboost-telemetry-v1`, `feature_count: 58`. Если это не так, демонстрацию нельзя считать проверенной.

## Чек-лист демонстрации для жюри

1. Выполнить `docker compose up --build` и дождаться healthy-состояния сервисов.
2. Проверить `http://localhost:8000/api/v1/health` и `http://localhost:8001/health` внутри compose-сети либо по логам health-check.
3. Открыть дашборд и убедиться, что HTTP mock создаёт восемь ТС и обновляет их каждые пять секунд.
4. При необходимости подключить официальный NDTP-эмулятор по инструкции выше и увидеть `NDTP-*` на карте.
5. Открыть карточку ТС: проверить горизонт 15 минут, вероятность, прогноз, причину и динамику.
6. Открыть Swagger и выполнить пробный запрос `/api/v1/vehicles`.
7. Зафиксировать `/api/v1/stats`: среднюю latency, количество ТС, high-risk и число NDTP-пакетов.

Для нагрузочной проверки можно отправлять batch-запросы на `/api/v1/telematics/batch`. Реальная производительность зависит от модели, числа воркеров и конфигурации PostgreSQL.
