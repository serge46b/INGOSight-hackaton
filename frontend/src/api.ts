export type ApiError = {
  code: string;
  message: string;
  details?: { fields?: string[] } | null;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw {
      code: "NETWORK_ERROR",
      message: "Нет соединения. Повторите позже",
    } satisfies ApiError;
  }
  if (!response.ok) {
    try {
      throw (await response.json()) as ApiError;
    } catch (error) {
      if (typeof error === "object" && error && "code" in error) {
        throw error;
      }
      throw {
        code: "NETWORK_ERROR",
        message: "Нет соединения. Повторите позже",
      } satisfies ApiError;
    }
  }
  return response.json() as Promise<T>;
}

export function isApiError(error: unknown): error is ApiError {
  return typeof error === "object" && error !== null && "message" in error && "code" in error;
}
