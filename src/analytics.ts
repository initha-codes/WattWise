export type Location = {
  id: string
  name: string
  category: string
  color: string
  base: number
}

export type Reading = {
  timestamp: string
  locationId: string
  kwh: number
  quality: 'valid' | 'flagged' | 'missing'
}

export const locations: Location[] = [
  { id: 'admin', name: 'Administration Building', category: 'Office', color: '#0d9488', base: 18 },
  { id: 'engineering', name: 'Engineering Block', category: 'Academic', color: '#4f7c69', base: 31 },
  { id: 'computer', name: 'Computer Laboratory', category: 'Laboratory', color: '#d59235', base: 26 },
  { id: 'library', name: 'Library', category: 'Academic', color: '#5287a1', base: 20 },
  { id: 'hostel', name: 'Student Hostel', category: 'Residential', color: '#9a7560', base: 34 },
  { id: 'utilities', name: 'Central Utilities', category: 'Infrastructure', color: '#688571', base: 42 },
]

const start = new Date('2026-07-27T00:00:00Z')
const seededNoise = (seed: number) => {
  const value = Math.sin(seed * 127.1 + 311.7) * 43758.5453
  return (value - Math.floor(value)) * 2 - 1
}

export const demoReadings: Reading[] = (() => {
  const output: Reading[] = []
  for (let day = 0; day < 90; day += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      for (let index = 0; index < locations.length; index += 1) {
        const location = locations[index]
        const weekend = (start.getUTCDay() + day) % 7 === 0 || (start.getUTCDay() + day) % 7 === 6
        const daytime = hour >= 8 && hour < 19
        const evening = hour >= 18 && hour < 23
        let factor = daytime ? 1.46 : hour >= 0 && hour < 6 ? 0.43 : 0.76
        if (location.id === 'hostel') factor = evening ? 1.48 : daytime ? 0.92 : 0.82
        if (location.id === 'utilities') factor = daytime ? 1.28 : 0.88
        if (weekend && location.id !== 'hostel') factor *= daytime ? 0.68 : 0.88
        const trend = day > 58 && location.id === 'engineering' ? 1.16 : 1
        let kwh = location.base * factor * trend + seededNoise(day * 144 + hour * 6 + index) * location.base * 0.1
        const isSpike = (day === 75 && hour === 13 && index === 2) || (day === 82 && hour === 17 && index === 4) || (day === 88 && hour === 11 && index === 1)
        if (isSpike) kwh *= 2.25
        const isZero = day === 67 && hour >= 9 && hour <= 10 && index === 0
        if (isZero) kwh = 0
        const outage = (day === 55 && hour >= 3 && hour <= 5 && index === 3) || (day === 84 && hour === 2 && index === 5)
        if (!outage) {
          const timestamp = new Date(start.getTime() + (day * 24 + hour) * 60 * 60 * 1000).toISOString()
          output.push({ timestamp, locationId: location.id, kwh: Math.max(0, Number(kwh.toFixed(2))), quality: isSpike || isZero ? 'flagged' : 'valid' })
        }
      }
    }
  }
  return output
})()

export function previousRange(readings: Reading[], days: number, locationId: string) {
  const latest = readings.reduce((maximum, reading) => Math.max(maximum, new Date(reading.timestamp).getTime()), 0)
  const end = latest ? Math.floor(latest / 3_600_000) * 3_600_000 + 3_600_000 : new Date('2026-10-25T00:00:00Z').getTime()
  const from = end - days * 24 * 60 * 60 * 1000
  return readings.filter((reading) => {
    const time = new Date(reading.timestamp).getTime()
    return time >= from && time < end && (locationId === 'all' || reading.locationId === locationId)
  })
}

export function formatKwh(value: number) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value)
}