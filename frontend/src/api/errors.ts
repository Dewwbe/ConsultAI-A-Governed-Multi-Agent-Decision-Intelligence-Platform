/** Typed API errors. Callers branch on the class (`instanceof ConflictError`), not on status codes. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly body?: unknown,
  ) {
    super(detail);
    this.name = new.target.name;
  }
}

/** 401: missing, invalid or expired credentials. */
export class UnauthorizedError extends ApiError {}
/** 403: signed in but not allowed (for example approving without the Partner role). */
export class ForbiddenError extends ApiError {}
/** 404: engagement or resource does not exist. */
export class NotFoundError extends ApiError {}
/** 409: the engagement is not awaiting approval (someone else already decided, or it is still running). */
export class ConflictError extends ApiError {}
/** 422: the request failed validation; `fields` lists what to fix when the server says which. */
export class ValidationError extends ApiError {
  constructor(status: number, detail: string, body: unknown, readonly fields: string[] = []) {
    super(status, detail, body);
  }
}
export class ServerError extends ApiError {}
/** The request never got an answer: offline, DNS, CORS failure or the API is down. */
export class NetworkError extends Error {
  constructor(message = "Cannot reach the API") {
    super(message);
    this.name = "NetworkError";
  }
}

interface FastApiValidationItem {
  loc?: unknown[];
  msg?: string;
}

function detailOf(body: unknown, fallback: string): { detail: string; fields: string[] } {
  const raw = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof raw === "string") return { detail: raw, fields: [] };
  if (Array.isArray(raw)) {
    const items = raw as FastApiValidationItem[];
    return {
      detail: items.map((i) => i.msg).filter(Boolean).join("; ") || fallback,
      fields: items.map((i) => (i.loc ?? []).filter((p) => p !== "body").join(".")).filter(Boolean),
    };
  }
  return { detail: fallback, fields: [] };
}

export function apiErrorFrom(status: number, body: unknown): ApiError {
  const { detail, fields } = detailOf(body, `Request failed (${status})`);
  switch (status) {
    case 401:
      return new UnauthorizedError(status, detail, body);
    case 403:
      return new ForbiddenError(status, detail, body);
    case 404:
      return new NotFoundError(status, detail, body);
    case 409:
      return new ConflictError(status, detail, body);
    case 422:
      return new ValidationError(status, detail, body, fields);
    default:
      return status >= 500 ? new ServerError(status, detail, body) : new ApiError(status, detail, body);
  }
}

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Await an openapi-fetch call and return its data, or throw a typed error. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new NetworkError(e instanceof Error ? e.message : undefined);
  }
  if (result.error !== undefined || !result.response.ok) {
    throw apiErrorFrom(result.response.status, result.error);
  }
  return result.data as T;
}

/** Only transient failures are worth retrying; a 404 or 409 will not fix itself. */
export function isRetryable(error: unknown): boolean {
  return error instanceof NetworkError || error instanceof ServerError;
}

export interface ErrorSummary {
  title: string;
  message: string;
}

/** Human wording for an error, used by the shared error state. */
export function describeError(error: unknown): ErrorSummary {
  if (error instanceof UnauthorizedError)
    return { title: "Sign-in required", message: "Your session is missing or has expired. Sign in again." };
  if (error instanceof ForbiddenError)
    return { title: "Not permitted", message: error.detail || "You do not have the role this action needs." };
  if (error instanceof NotFoundError)
    return { title: "Not found", message: "That engagement does not exist, or you cannot see it." };
  if (error instanceof ConflictError)
    return {
      title: "Not awaiting approval",
      message: error.detail || "This engagement is not waiting for a decision. It may already have been decided.",
    };
  if (error instanceof ValidationError)
    return { title: "Check your input", message: error.detail };
  if (error instanceof NetworkError)
    return { title: "Cannot reach the API", message: "Check that the backend is running and the API address is right." };
  if (error instanceof ServerError)
    return { title: "The server had a problem", message: "Try again in a moment. If it keeps failing, tell an administrator." };
  if (error instanceof ApiError) return { title: "Request failed", message: error.detail };
  return { title: "Something went wrong", message: error instanceof Error ? error.message : "Unknown error" };
}
