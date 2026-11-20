/** Render a UTC instant in the user's IANA time zone, e.g. "Fri, Nov 27, 11:10 AM CST". */
export function formatInTz(iso: string, timeZone: string, opts: { date?: boolean; seconds?: boolean } = {}): string {
  const { date = true, seconds = false } = opts
  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    weekday: date ? 'short' : undefined,
    month: date ? 'short' : undefined,
    day: date ? 'numeric' : undefined,
    hour: 'numeric',
    minute: '2-digit',
    second: seconds ? '2-digit' : undefined,
    timeZoneName: 'short',
  }).format(new Date(iso))
}

export function minutes(seconds: number): string {
  return `${Math.round(seconds / 60)} min`
}
