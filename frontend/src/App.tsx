import { useEffect, useMemo, useState } from 'react'
import L, { type LatLngExpression } from 'leaflet'
import { MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  BusFront,
  ChevronDown,
  CircleHelp,
  Clock3,
  Gauge,
  Layers3,
  Map as MapIcon,
  Radio,
  RefreshCw,
  Route as RouteIcon,
  Search,
  Server,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'
import { api, updatesSocket } from './api'
import type { Health, HistoryPoint, Prediction, RiskLevel, Route, ScheduleStop, Stats, Vehicle } from './types'

const riskMeta: Record<RiskLevel, { label: string; short: string; color: string }> = {
  high: { label: 'Высокий риск', short: 'Высокий', color: '#d8493f' },
  medium: { label: 'Требует внимания', short: 'Средний', color: '#e89b35' },
  low: { label: 'Следует графику', short: 'Низкий', color: '#209c6b' },
}

const emptyStats: Stats = {
  vehicle_count: 0,
  high_risk_predictions: 0,
  average_predicted_delay_min: 0,
  average_ml_latency_ms: 0,
  websocket_clients: 0,
}

const formatClock = (date: Date) => new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
}).format(date)
const formatDelay = (value: number | null) => {
  if (value === null) return '—'
  if (Math.abs(value) < 0.05) return 'По графику'
  return `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(1)} мин`
}
const timeAgo = (value: string) => {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000))
  if (seconds < 10) return 'только что'
  if (seconds < 60) return `${seconds} сек назад`
  return `${Math.floor(seconds / 60)} мин назад`
}

function MapViewport({ points }: { points: LatLngExpression[] }) {
  const map = useMap()
  useEffect(() => {
    if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [64, 64], maxZoom: 15 })
    else if (points.length === 1) map.setView(points[0], 14)
  }, [map, points])
  return null
}

function TransportMap({
  vehicles,
  stops,
  selected,
  onSelect,
}: {
  vehicles: Vehicle[]
  stops: ScheduleStop[]
  selected: Vehicle | null
  onSelect: (vehicle: Vehicle) => void
}) {
  const uniqueStops = useMemo(() => {
    const seen = new Set<number>()
    return stops
      .filter((stop) => !seen.has(stop.stop_id) && seen.add(stop.stop_id))
      .sort((a, b) => a.stop_sequence - b.stop_sequence)
  }, [stops])
  const routeLine = uniqueStops.map((stop) => [stop.stop_lat, stop.stop_lon] as LatLngExpression)
  const vehiclePoints = vehicles
    .filter((vehicle) => vehicle.lat !== null && vehicle.lon !== null)
    .map((vehicle) => [vehicle.lat!, vehicle.lon!] as LatLngExpression)
  const viewportPoints = [...routeLine, ...vehiclePoints]

  return (
    <div className="map-shell">
      <MapContainer center={[55.7558, 37.6176]} zoom={13} zoomControl={false} attributionControl={false}>
        <TileLayer url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" />
        {routeLine.length > 1 && (
          <>
            <Polyline positions={routeLine} pathOptions={{ color: '#ffffff', weight: 9, opacity: 0.9 }} />
            <Polyline positions={routeLine} pathOptions={{ color: '#d64137', weight: 4, opacity: 0.95 }} />
          </>
        )}
        {uniqueStops.map((stop, index) => (
          <Marker
            key={stop.stop_id}
            position={[stop.stop_lat, stop.stop_lon]}
            icon={L.divIcon({
              className: 'stop-icon-wrap',
              html: `<span class="stop-icon"><b>${index + 1}</b></span>`,
              iconSize: [24, 24],
              iconAnchor: [12, 12],
            })}
          >
            <Tooltip direction="top" offset={[0, -10]}>{stop.stop_name}</Tooltip>
          </Marker>
        ))}
        {vehicles.filter((vehicle) => vehicle.lat !== null && vehicle.lon !== null).map((vehicle) => {
          const risk = vehicle.risk_level ?? 'low'
          const isSelected = selected?.vehicle_id === vehicle.vehicle_id
          return (
            <Marker
              key={vehicle.vehicle_id}
              position={[vehicle.lat!, vehicle.lon!]}
              eventHandlers={{ click: () => onSelect(vehicle) }}
              zIndexOffset={isSelected ? 1000 : risk === 'high' ? 500 : 0}
              icon={L.divIcon({
                className: 'vehicle-marker-wrap',
                html: `<span class="vehicle-marker vehicle-marker--${risk}${isSelected ? ' is-selected' : ''}"><i></i></span>`,
                iconSize: [38, 38],
                iconAnchor: [19, 19],
              })}
            >
              <Popup className="vehicle-popup" offset={[0, -12]}>
                <strong>{vehicle.vehicle_id}</strong>
                <span>Маршрут {vehicle.route_number}</span>
                <b>{formatDelay(vehicle.predicted_delay_min)}</b>
              </Popup>
            </Marker>
          )
        })}
        {viewportPoints.length > 0 && <MapViewport points={viewportPoints} />}
      </MapContainer>
      <div className="map-topline">
        <span><Layers3 size={15} /> Оперативная карта</span>
        <div className="map-legend">
          <span><i className="legend-dot low" /> Норма</span>
          <span><i className="legend-dot medium" /> Внимание</span>
          <span><i className="legend-dot high" /> Риск</span>
        </div>
      </div>
      <div className="map-counter"><BusFront size={15} /> {vehicles.length} ТС на карте</div>
    </div>
  )
}

function MetricCard({
  icon,
  label,
  value,
  note,
  tone = 'neutral',
}: {
  icon: React.ReactNode
  label: string
  value: string
  note: string
  tone?: 'neutral' | 'danger' | 'good'
}) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-icon">{icon}</div>
      <div className="metric-copy"><span>{label}</span><strong>{value}</strong></div>
      <small>{note}</small>
    </article>
  )
}

function IncidentRow({ vehicle, active, onClick }: { vehicle: Vehicle; active: boolean; onClick: () => void }) {
  const risk = vehicle.risk_level ?? 'low'
  return (
    <button className={`incident-row ${active ? 'is-active' : ''}`} onClick={onClick}>
      <span className={`risk-rail risk-rail--${risk}`} />
      <span className="incident-main">
        <span className="incident-heading">
          <b>{vehicle.vehicle_id}</b>
          <em className={`risk-tag risk-tag--${risk}`}>{riskMeta[risk].short}</em>
        </span>
        <span className="incident-route">Маршрут {vehicle.route_number} · {vehicle.reason ?? 'без аномалий'}</span>
        <span className="incident-meta">
          <span><Clock3 size={13} /> {formatDelay(vehicle.predicted_delay_min)}</span>
          <span><Gauge size={13} /> {Math.round((vehicle.probability ?? 0) * 100)}%</span>
        </span>
      </span>
      <ArrowUpRight size={17} className="incident-arrow" />
    </button>
  )
}

function DetailDrawer({ vehicle, onClose }: { vehicle: Vehicle; onClose: () => void }) {
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [predictions, setPredictions] = useState<Prediction[]>([])
  const [loading, setLoading] = useState(true)
  const risk = vehicle.risk_level ?? 'low'

  useEffect(() => {
    let current = true
    setLoading(true)
    Promise.all([api.history(vehicle.vehicle_id), api.predictions(vehicle.vehicle_id)])
      .then(([historyData, predictionData]) => {
        if (!current) return
        setHistory([...historyData.points].reverse())
        setPredictions([...predictionData.history].reverse())
      })
      .finally(() => current && setLoading(false))
    return () => { current = false }
  }, [vehicle.vehicle_id])

  const chartData = predictions.map((item) => ({
    time: new Date(item.predicted_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
    delay: item.predicted_delay_min,
  }))
  const latestPrediction = predictions.at(-1)
  const nextStopId = history.at(-1)?.nearest_stop_id

  return (
    <aside className="drawer" aria-label={`Детали ${vehicle.vehicle_id}`}>
      <div className="drawer-head">
        <button className="icon-button mobile-back" onClick={onClose}><ArrowLeft size={19} /></button>
        <div><span>Карточка транспортного средства</span><h2>{vehicle.vehicle_id}</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="Закрыть"><X size={19} /></button>
      </div>
      <div className="drawer-scroll">
        <section className={`incident-summary incident-summary--${risk}`}>
          <div className="summary-top">
            <span className={`risk-badge risk-badge--${risk}`}><i /> {riskMeta[risk].label}</span>
            <span>{Math.round((vehicle.probability ?? 0) * 100)}% вероятность</span>
          </div>
          <strong>{formatDelay(vehicle.predicted_delay_min)}</strong>
          <p>прогноз отклонения через {latestPrediction?.horizon_min ?? 15} минут</p>
          <div className="reason-box"><Sparkles size={16} /><span><small>Вероятная причина</small>{vehicle.reason ?? 'Рисковый паттерн не выявлен'}</span></div>
        </section>

        <section className="drawer-section">
          <div className="section-heading"><h3>Текущие показатели</h3><span>{timeAgo(vehicle.updated_at)}</span></div>
          <div className="data-grid">
            <div><span>Маршрут</span><b>{vehicle.route_number}</b></div>
            <div><span>Рейс</span><b>{vehicle.trip_id ?? '—'}</b></div>
            <div><span>Скорость</span><b>{vehicle.speed?.toFixed(0) ?? '—'} км/ч</b></div>
            <div><span>Остановка</span><b>{nextStopId ? `№ ${nextStopId}` : '—'}</b></div>
          </div>
        </section>

        <section className="drawer-section chart-section">
          <div className="section-heading"><h3>Динамика прогноза</h3><span>минуты</span></div>
          {loading ? <div className="chart-skeleton" /> : chartData.length > 1 ? (
            <ResponsiveContainer width="100%" height={190}>
              <AreaChart data={chartData} margin={{ top: 12, right: 4, left: -24, bottom: 0 }}>
                <defs><linearGradient id="delayFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#d8493f" stopOpacity={0.25} /><stop offset="100%" stopColor="#d8493f" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e7eaed" />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#7e8894' }} minTickGap={28} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#7e8894' }} />
                <ChartTooltip contentStyle={{ border: 0, borderRadius: 10, boxShadow: '0 12px 30px rgba(18,24,32,.15)', fontSize: 12 }} />
                <Area type="monotone" dataKey="delay" stroke="#d8493f" strokeWidth={2.5} fill="url(#delayFill)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <div className="empty-chart"><Activity size={22} /><span>График появится после нескольких прогнозов</span></div>}
        </section>

        <section className="drawer-section">
          <div className="section-heading"><h3>Контур модели</h3></div>
          <div className="model-line"><span><Server size={15} /> Версия</span><b>{latestPrediction?.model_version ?? 'ожидание данных'}</b></div>
          <div className="model-line"><span><Activity size={15} /> Latency</span><b>{latestPrediction ? `${latestPrediction.latency_ms.toFixed(0)} мс` : '—'}</b></div>
          <div className="model-line"><span><Radio size={15} /> Точек телеметрии</span><b>{history.length}</b></div>
        </section>
      </div>
    </aside>
  )
}

type ViewName = 'map' | 'routes' | 'monitoring' | 'help'

function RoutesView({
  routes,
  vehicles,
  schedules,
  onOpenRoute,
}: {
  routes: Route[]
  vehicles: Vehicle[]
  schedules: ScheduleStop[]
  onOpenRoute: (routeId: number) => void
}) {
  return (
    <div className="content secondary-page">
      <div className="page-heading">
        <div><span className="eyebrow">Маршрутная сеть</span><h1>Управление маршрутами</h1><p>Сводное состояние движения и прогноз рисков по направлениям</p></div>
        <div className="page-status"><i className="online" /> Маршрутов в работе: {routes.filter((route) => route.is_active).length}</div>
      </div>

      <section className="route-overview">
        <div className="overview-copy">
          <span>Состояние сети</span>
          <strong>{vehicles.filter((item) => item.risk_level !== 'high').length} из {vehicles.length} ТС</strong>
          <p>движутся без критического риска</p>
        </div>
        <div className="overview-scale" aria-label="Распределение рисков">
          {(['low', 'medium', 'high'] as RiskLevel[]).map((risk) => {
            const count = vehicles.filter((item) => item.risk_level === risk).length
            const width = vehicles.length ? Math.max(5, count / vehicles.length * 100) : 5
            return <span key={risk} className={`scale-${risk}`} style={{ width: `${width}%` }} title={`${riskMeta[risk].label}: ${count}`} />
          })}
        </div>
        <div className="overview-legend">
          {(['low', 'medium', 'high'] as RiskLevel[]).map((risk) => <span key={risk}><i className={`legend-dot ${risk}`} />{riskMeta[risk].label}<b>{vehicles.filter((item) => item.risk_level === risk).length}</b></span>)}
        </div>
      </section>

      <section className="routes-card">
        <div className="table-title"><div><h2>Маршруты в работе</h2><p>Актуальные данные обновляются вместе с телеметрией</p></div><RouteIcon size={20} /></div>
        <div className="routes-table">
          <div className="routes-table-head"><span>Маршрут</span><span>Транспорт</span><span>Остановки</span><span>Средний прогноз</span><span>Риск</span><span /></div>
          {routes.map((route) => {
            const routeVehicles = vehicles.filter((item) => item.route_id === route.id)
            const stops = new Set(schedules.filter((item) => item.route_id === route.id).map((item) => item.stop_id)).size
            const highRisk = routeVehicles.filter((item) => item.risk_level === 'high').length
            const mediumRisk = routeVehicles.filter((item) => item.risk_level === 'medium').length
            const delayValues = routeVehicles.map((item) => item.predicted_delay_min).filter((value): value is number => value !== null)
            const averageDelay = delayValues.length ? delayValues.reduce((sum, value) => sum + value, 0) / delayValues.length : 0
            const risk: RiskLevel = highRisk ? 'high' : mediumRisk ? 'medium' : 'low'
            return (
              <button className="route-row" key={route.id} onClick={() => onOpenRoute(route.id)}>
                <span className="route-identity"><b>{route.route_number}</b><span>{route.name ?? 'Без названия'}</span></span>
                <span className="table-value"><BusFront size={15} />{routeVehicles.length}</span>
                <span className="table-value">{stops}</span>
                <span className="table-value">+{averageDelay.toFixed(1)} мин</span>
                <span><em className={`risk-tag risk-tag--${risk}`}>{riskMeta[risk].short}</em></span>
                <span className="open-route">На карту <ArrowUpRight size={15} /></span>
              </button>
            )
          })}
        </div>
      </section>
    </div>
  )
}

function MonitoringView({ health, stats, connected }: { health: Health | null; stats: Stats; connected: boolean }) {
  const services = [
    { name: 'Backend API', detail: 'Оркестрация и REST', ok: health?.database ?? false, value: '8000' },
    { name: 'PostgreSQL', detail: 'Оперативное хранилище', ok: health?.database ?? false, value: 'online' },
    { name: 'Redis', detail: 'Кэш состояний ТС', ok: health?.redis ?? false, value: '120 sec' },
    { name: 'ML Service', detail: 'Контур прогнозирования', ok: health?.ml_service_ok ?? false, value: `${stats.average_ml_latency_ms.toFixed(0)} ms` },
    { name: 'WebSocket', detail: 'Поток обновлений', ok: connected, value: `${stats.websocket_clients} clients` },
  ]
  const allOnline = services.every((service) => service.ok)

  return (
    <div className="content secondary-page">
      <div className="page-heading">
        <div><span className="eyebrow">Технический контроль</span><h1>Мониторинг системы</h1><p>Доступность сервисов и производительность контура прогнозирования</p></div>
        <div className={`page-status ${allOnline ? 'status-good' : 'status-warning'}`}><i className={allOnline ? 'online' : ''} />{allOnline ? 'Все системы работают' : 'Есть ограничения'}</div>
      </div>

      <section className="monitor-kpis">
        <div><span>Средняя latency</span><strong>{stats.average_ml_latency_ms.toFixed(0)}<small>мс</small></strong><p>целевое значение &lt; 1 000 мс</p></div>
        <div><span>Активные ТС</span><strong>{stats.vehicle_count}<small>ед.</small></strong><p>принимают телеметрию</p></div>
        <div><span>Критические риски</span><strong>{stats.high_risk_predictions}<small>ТС</small></strong><p>требуют внимания</p></div>
        <div><span>Горизонт</span><strong>15<small>мин</small></strong><p>раннее предупреждение</p></div>
      </section>

      <div className="monitor-grid">
        <section className="services-card">
          <div className="table-title"><div><h2>Состояние сервисов</h2><p>Проверка связности компонентов</p></div><Server size={20} /></div>
          <div className="services-list">
            {services.map((service) => (
              <div className="service-row" key={service.name}>
                <span className={`service-icon ${service.ok ? 'is-up' : ''}`}><Server size={17} /></span>
                <span className="service-name"><b>{service.name}</b><small>{service.detail}</small></span>
                <span className="service-value">{service.value}</span>
                <span className={`service-state ${service.ok ? 'is-up' : ''}`}><i />{service.ok ? 'Работает' : 'Недоступен'}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="pipeline-card">
          <div className="table-title"><div><h2>Контур данных</h2><p>Обработка одного события телеметрии</p></div><Activity size={20} /></div>
          <div className="pipeline-flow">
            <div><span>01</span><b>Телеметрия</b><small>Координаты, скорость, двери</small></div>
            <i />
            <div><span>02</span><b>Backend</b><small>Matching и признаки</small></div>
            <i />
            <div><span>03</span><b>ML-прогноз</b><small>Риск на 10–15 минут</small></div>
            <i />
            <div><span>04</span><b>Диспетчер</b><small>Алерт и решение</small></div>
          </div>
          <div className="performance-note"><Gauge size={18} /><span><b>{stats.average_ml_latency_ms < 1000 ? 'Производительность в норме' : 'Повышенная latency'}</b><small>Последнее среднее значение — {stats.average_ml_latency_ms.toFixed(2)} мс</small></span></div>
        </section>
      </div>
    </div>
  )
}

function HelpView({ onOpenMap }: { onOpenMap: () => void }) {
  return (
    <div className="content secondary-page help-page">
      <div className="page-heading">
        <div><span className="eyebrow">Быстрый старт</span><h1>Работа с системой</h1><p>Короткая инструкция для диспетчера и демонстрации решения</p></div>
      </div>
      <section className="help-hero">
        <div><span>КОНТУР / 01</span><h2>Увидеть отклонение<br />до того, как оно произошло</h2><p>Система анализирует поток телеметрии и формирует предупреждение за 10–15 минут до ожидаемой задержки.</p><button onClick={onOpenMap}>Перейти к оперативной карте <ArrowUpRight size={16} /></button></div>
        <div className="help-signal"><Radio size={28} /><span><b>LIVE</b><small>Поток обрабатывается в реальном времени</small></span></div>
      </section>
      <section className="guide-grid">
        <article><span>01</span><MapIcon size={22} /><h3>Оцените обстановку</h3><p>На карте сразу видны положение транспорта и цветовой уровень риска.</p></article>
        <article><span>02</span><AlertTriangle size={22} /><h3>Откройте инцидент</h3><p>Выберите ТС на карте или в очереди, чтобы увидеть прогноз и причину.</p></article>
        <article><span>03</span><RouteIcon size={22} /><h3>Проверьте маршрут</h3><p>В разделе маршрутов сравните загрузку, задержки и проблемные направления.</p></article>
        <article><span>04</span><Activity size={22} /><h3>Контролируйте контур</h3><p>Мониторинг показывает доступность сервисов и реальную latency модели.</p></article>
      </section>
      <section className="help-links">
        <div><h3>Техническая документация</h3><p>Интерактивная спецификация и методы интеграции с системой.</p></div>
        <a href="/docs" target="_blank" rel="noreferrer">Открыть Swagger <ArrowUpRight size={16} /></a>
      </section>
    </div>
  )
}

export default function App() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [routes, setRoutes] = useState<Route[]>([])
  const [schedules, setSchedules] = useState<ScheduleStop[]>([])
  const [stats, setStats] = useState<Stats>(emptyStats)
  const [health, setHealth] = useState<Health | null>(null)
  const [selected, setSelected] = useState<Vehicle | null>(null)
  const [selectedRoute, setSelectedRoute] = useState<string>('all')
  const [riskFilter, setRiskFilter] = useState<'all' | RiskLevel>('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [connected, setConnected] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [clock, setClock] = useState(new Date())
  const [activeView, setActiveView] = useState<ViewName>('map')

  const loadDashboard = async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const [vehicleData, routeData, scheduleData, statsData, healthData] = await Promise.all([
        api.vehicles(), api.routes(), api.schedules(), api.stats(), api.health(),
      ])
      setVehicles(vehicleData.vehicles)
      setRoutes(routeData.routes)
      setSchedules(scheduleData.schedules)
      setStats(statsData)
      setHealth(healthData)
      setLastUpdated(new Date())
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadDashboard() }, [])
  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000)
    const poll = window.setInterval(() => void loadDashboard(true), 30_000)
    return () => { window.clearInterval(timer); window.clearInterval(poll) }
  }, [])
  useEffect(() => {
    let disposed = false
    let retry: number | undefined
    let socket: WebSocket | undefined
    const connect = () => {
      socket = updatesSocket()
      socket.onopen = () => setConnected(true)
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as { type: string; vehicle: Vehicle }
        if (payload.type !== 'vehicle.updated') return
        setVehicles((current) => {
          const exists = current.some((item) => item.vehicle_id === payload.vehicle.vehicle_id)
          return exists
            ? current.map((item) => item.vehicle_id === payload.vehicle.vehicle_id ? payload.vehicle : item)
            : [payload.vehicle, ...current]
        })
        setSelected((current) => current?.vehicle_id === payload.vehicle.vehicle_id ? payload.vehicle : current)
        setLastUpdated(new Date())
      }
      socket.onclose = () => {
        setConnected(false)
        if (!disposed) retry = window.setTimeout(connect, 2500)
      }
      socket.onerror = () => socket?.close()
    }
    connect()
    return () => {
      disposed = true
      if (retry) window.clearTimeout(retry)
      socket?.close()
    }
  }, [])

  const filteredVehicles = useMemo(() => vehicles.filter((vehicle) => {
    const routeMatches = selectedRoute === 'all' || vehicle.route_id === Number(selectedRoute)
    const riskMatches = riskFilter === 'all' || vehicle.risk_level === riskFilter
    const queryMatches = !query || `${vehicle.vehicle_id} ${vehicle.route_number}`.toLowerCase().includes(query.toLowerCase())
    return routeMatches && riskMatches && queryMatches
  }), [vehicles, selectedRoute, riskFilter, query])
  const sortedIncidents = useMemo(() => [...filteredVehicles].sort((a, b) => {
    const rank = { high: 3, medium: 2, low: 1 }
    return (rank[b.risk_level ?? 'low'] - rank[a.risk_level ?? 'low']) || ((b.probability ?? 0) - (a.probability ?? 0))
  }), [filteredVehicles])
  const visibleSchedules = selectedRoute === 'all' ? schedules : schedules.filter((item) => item.route_id === Number(selectedRoute))
  const highRiskShare = stats.vehicle_count ? Math.round((stats.high_risk_predictions / stats.vehicle_count) * 100) : 0

  return (
    <div className="app-shell">
      <nav className="nav-rail">
        <div className="brand-mark"><span>К</span></div>
        <div className="nav-items">
          <button className={`nav-item ${activeView === 'map' ? 'is-active' : ''}`} onClick={() => setActiveView('map')} aria-label="Карта"><MapIcon size={20} /><span>Карта</span></button>
          <button className={`nav-item ${activeView === 'routes' ? 'is-active' : ''}`} onClick={() => setActiveView('routes')} aria-label="Маршруты"><RouteIcon size={20} /><span>Маршруты</span></button>
          <button className={`nav-item ${activeView === 'monitoring' ? 'is-active' : ''}`} onClick={() => setActiveView('monitoring')} aria-label="Мониторинг"><Activity size={20} /><span>Мониторинг</span></button>
        </div>
        <button className={`nav-item nav-help ${activeView === 'help' ? 'is-active' : ''}`} onClick={() => setActiveView('help')} aria-label="Помощь"><CircleHelp size={20} /><span>Помощь</span></button>
      </nav>

      <main className="workspace">
        <header className="topbar">
          <div className="product-title"><b>КОНТУР</b><span>Центр управления движением</span></div>
          <div className="topbar-right">
            <div className={`live-state ${connected ? 'is-online' : ''}`}><i />{connected ? 'Данные в реальном времени' : 'Переподключение'}</div>
            <div className="system-time"><span>МСК</span><b>{formatClock(clock)}</b></div>
            <div className="operator"><span>ДЦ</span><div><b>Диспетчер</b><small>Смена № 04</small></div></div>
          </div>
        </header>

        <div className={`content ${activeView !== 'map' ? 'is-hidden' : ''}`}>
          <div className="page-heading">
            <div><span className="eyebrow">Оперативная обстановка</span><h1>Мониторинг движения</h1><p>{lastUpdated ? `Обновлено ${timeAgo(lastUpdated.toISOString())}` : 'Получение актуальных данных…'}</p></div>
            <div className="filters">
              <label className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Номер ТС или маршрут" /></label>
              <label className="select-box"><RouteIcon size={16} /><select value={selectedRoute} onChange={(event) => setSelectedRoute(event.target.value)}><option value="all">Все маршруты</option>{routes.map((route) => <option key={route.id} value={route.id}>Маршрут {route.route_number}</option>)}</select><ChevronDown size={15} /></label>
              <button className="refresh-button" onClick={() => void loadDashboard()} aria-label="Обновить"><RefreshCw size={17} className={loading ? 'is-spinning' : ''} /></button>
            </div>
          </div>

          {error && <div className="error-banner"><AlertTriangle size={18} /><span><b>Связь с контуром прервана.</b> На экране остаются последние полученные данные.</span><button onClick={() => void loadDashboard()}>Повторить</button></div>}

          <section className="metrics-grid">
            <MetricCard icon={<BusFront size={20} />} label="Транспорт на линии" value={String(stats.vehicle_count)} note={`${routes.length} активных маршрута`} />
            <MetricCard icon={<AlertTriangle size={20} />} label="Высокий риск" value={String(stats.high_risk_predictions)} note={`${highRiskShare}% от транспорта`} tone={stats.high_risk_predictions > 0 ? 'danger' : 'good'} />
            <MetricCard icon={<Clock3 size={20} />} label="Средний прогноз" value={`+${stats.average_predicted_delay_min.toFixed(1)} мин`} note="горизонт 10–15 минут" />
            <MetricCard icon={<Activity size={20} />} label="Отклик модели" value={`${stats.average_ml_latency_ms.toFixed(0)} мс`} note={stats.average_ml_latency_ms < 1000 ? 'в пределах нормы' : 'выше целевого'} tone={stats.average_ml_latency_ms < 1000 ? 'good' : 'danger'} />
          </section>

          <section className="operations-grid">
            <TransportMap vehicles={filteredVehicles} stops={visibleSchedules} selected={selected} onSelect={setSelected} />
            <aside className="incidents-panel">
              <div className="panel-head">
                <div><span>Приоритетная очередь</span><h2>Ситуации на линии</h2></div>
                <button className="icon-button"><SlidersHorizontal size={17} /></button>
              </div>
              <div className="risk-tabs">
                {(['all', 'high', 'medium', 'low'] as const).map((risk) => (
                  <button key={risk} className={riskFilter === risk ? 'is-active' : ''} onClick={() => setRiskFilter(risk)}>
                    {risk === 'all' ? 'Все' : riskMeta[risk].short}
                    <span>{risk === 'all' ? vehicles.length : vehicles.filter((item) => item.risk_level === risk).length}</span>
                  </button>
                ))}
              </div>
              <div className="incidents-list">
                {loading && !vehicles.length ? Array.from({ length: 4 }).map((_, index) => <div className="row-skeleton" key={index} />) : sortedIncidents.length ? sortedIncidents.map((vehicle) => (
                  <IncidentRow key={vehicle.vehicle_id} vehicle={vehicle} active={selected?.vehicle_id === vehicle.vehicle_id} onClick={() => setSelected(vehicle)} />
                )) : <div className="empty-state"><span><BusFront size={23} /></span><b>ТС не найдены</b><p>Измените выбранные фильтры</p></div>}
              </div>
              <div className="panel-footer"><span><i className={connected ? 'online' : ''} /> {connected ? 'Поток подключён' : 'Резервное обновление'}</span><span>{stats.websocket_clients} WS</span></div>
            </aside>
          </section>
        </div>
        {activeView === 'routes' && <RoutesView routes={routes} vehicles={vehicles} schedules={schedules} onOpenRoute={(routeId) => { setSelectedRoute(String(routeId)); setActiveView('map') }} />}
        {activeView === 'monitoring' && <MonitoringView health={health} stats={stats} connected={connected} />}
        {activeView === 'help' && <HelpView onOpenMap={() => setActiveView('map')} />}
      </main>

      {selected && <><div className="drawer-backdrop" onClick={() => setSelected(null)} /><DetailDrawer vehicle={selected} onClose={() => setSelected(null)} /></>}
    </div>
  )
}
