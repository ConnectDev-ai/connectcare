import type { EstadoFlotaResponse } from "./types";

// Same-origin proxy prefix (rewritten to the Flask API in next.config.ts).
// Override with NEXT_PUBLIC_BACKEND_BASE if the backend is reached differently.
const BASE = process.env.NEXT_PUBLIC_BACKEND_BASE ?? "/backend";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new ApiError(res.status, `La API respondió ${res.status} en ${path}`);
  }
  return (await res.json()) as T;
}

/** GET /api/estado-flota — fleet maintenance state (no filters; filtered client-side). */
export function fetchEstadoFlota(): Promise<EstadoFlotaResponse> {
  return getJson<EstadoFlotaResponse>("/estado-flota");
}
