export const HOSTED = import.meta.env.MODE === "hosted";
export const API = HOSTED ? "" : "http://127.0.0.1:8000";
let csrfToken = "";

export function setCsrfToken(token: string) {
	csrfToken = token;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(`${API}${path}`, {
		...init,
		credentials: "same-origin",
		headers: {
			...(init?.body
				? { "Content-Type": "application/json" }
				: {}),
			...(HOSTED && init?.method && init.method !== "GET"
				? { "X-CSRF-Token": csrfToken }
				: {}),
			...init?.headers,
		},
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) {
		if (HOSTED && response.status === 401)
			window.dispatchEvent(
				new Event("organiser-session-expired"),
			);
		const detail =
			typeof data.detail === "string"
				? data.detail
				: `Request failed (${response.status}).`;
		const wait = data.retry_after_seconds
			? ` Retry after ${data.retry_after_seconds} seconds.`
			: "";
		throw new Error(`${detail}${wait}`);
	}
	return data as T;
}
