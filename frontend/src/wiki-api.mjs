export const API = "/tools/wiki/api";
export async function api(path, options = {}) {
  const response = await fetch(API + path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" },
  });
  if (!response.ok)
    throw new Error(
      (await response.json().catch(() => ({}))).error || "Request failed.",
    );
  return response.status === 204 ? null : response.json();
}
