import type { Health, HistoryPoint, Prediction, Route, ScheduleStop, Stats, Vehicle } from './types'

const API = '/api/v1'

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`API ${response.status}: ${path}`)
  return response.json() as Promise<T>
}

export const api = {
  vehicles: () => request<{ vehicles: Vehicle[]; total: number }>('/vehicles?limit=1000'),
  routes: () => request<{ routes: Route[] }>('/routes'),
  schedules: () => request<{ schedules: ScheduleStop[]; total: number }>('/schedules'),
  stats: () => request<Stats>('/stats'),
  health: () => request<Health>('/health'),
  history: (id: string) => request<{ vehicle_id: string; points: HistoryPoint[] }>(`/vehicles/${encodeURIComponent(id)}/history?limit=100`),
  predictions: (id: string) => request<{ latest: Prediction | null; history: Prediction[] }>(`/vehicles/${encodeURIComponent(id)}/prediction?limit=50`),
}

export function updatesSocket(): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return new WebSocket(`${protocol}//${window.location.host}${API}/ws/updates`)
}
