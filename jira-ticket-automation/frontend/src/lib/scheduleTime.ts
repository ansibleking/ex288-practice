export function todayLocalDate(): string {
  const d = new Date();
  const offsetMs = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - offsetMs).toISOString().slice(0, 10);
}

export function localDateAndTimeToIso(date: string, time: string): string {
  return new Date(`${date}T${time}`).toISOString();
}

export function dayRangeIso(date: string): { start: string; end: string } {
  const start = new Date(`${date}T00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start: start.toISOString(), end: end.toISOString() };
}
