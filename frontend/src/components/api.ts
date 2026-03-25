"use client";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

type RequestOptions = {
  method?: string;
  token?: string | null;
  body?: unknown;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {})
    },
    body: options.body ? JSON.stringify(options.body) : undefined
  });

  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("awg-auth-expired"));
    }
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      throw new Error(parsed.detail || `Request failed with status ${response.status}`);
    } catch {
      throw new Error(text || `Request failed with status ${response.status}`);
    }
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
