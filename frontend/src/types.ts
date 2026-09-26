export type RiskLevel = 'low' | 'medium' | 'high'

export interface Vehicle {
  vehicle_id: string
  route_id: number
  route_number: string
  trip_id: string | null
  lat: number | null
  lon: number | null
  speed: number | null
  current_delay_min: number
  probability: number | null
  predicted_delay_min: number | null
  risk_level: RiskLevel | null
  reason: string | null
  updated_at: string
}

export interface Route {
  id: number
  route_number: string
  name: string | null
  is_active: boolean
}

export interface ScheduleStop {
  id: number
  route_id: number
  trip_id: string
  stop_id: number
  stop_name: string
  stop_lat: number
  stop_lon: number
  stop_sequence: number
  planned_arrival: string
  planned_departure: string | null
}

export interface Stats {
  vehicle_count: number
  high_risk_predictions: number
  average_predicted_delay_min: number
  average_ml_latency_ms: number
  websocket_clients: number
}

export interface Health {
  status: 'ok' | 'degraded'
  database: boolean
  redis: boolean
  ml_service: string
  ml_service_ok: boolean
}

export interface HistoryPoint {
  timestamp: string
  lat: number
  lon: number
  speed: number
  heading: number | null
  nearest_stop_id: number | null
  door_status: string | null
}

export interface Prediction {
  predicted_at: string
  horizon_min: number
  probability: number
  predicted_delay_min: number
  risk_level: RiskLevel
  reason: string | null
  model_version: string
  latency_ms: number
}
