// Ports the two pure helpers from src/risk.py that the Overview page needs
// (WIB day boundary + loss-percent math) — read-only display, no trade sizing.

export function wibDayStartUtc(now: Date = new Date()): Date {
  const wibNow = new Date(now.getTime() + 7 * 3_600_000);
  const wibMidnightUtcMs = Date.UTC(
    wibNow.getUTCFullYear(),
    wibNow.getUTCMonth(),
    wibNow.getUTCDate(),
  );
  return new Date(wibMidnightUtcMs - 7 * 3_600_000);
}

export function wibWeekStartUtc(now: Date = new Date()): Date {
  const dayStart = wibDayStartUtc(now);
  const wibNow = new Date(now.getTime() + 7 * 3_600_000);
  const daysSinceMonday = (wibNow.getUTCDay() + 6) % 7; // Monday = 0
  return new Date(dayStart.getTime() - daysSinceMonday * 86_400_000);
}

export function dailyLossPct(balanceAtStart: number, balanceNow: number): number {
  if (balanceAtStart <= 0) return 0;
  return Math.max(0, ((balanceAtStart - balanceNow) / balanceAtStart) * 100);
}
