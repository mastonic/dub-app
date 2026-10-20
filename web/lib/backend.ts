export function backend(path: string, init: RequestInit = {}) {
  const base = process.env.BACKEND_URL;
  const key = process.env.BACKEND_API_KEY;
  if (!base || !key) {
    throw new Error("BACKEND_URL ou BACKEND_API_KEY manquant");
  }
  return fetch(`${base}${path}`, {
    ...init,
    headers: { ...(init.headers || {}), "x-api-key": key },
    cache: "no-store",
  });
}
