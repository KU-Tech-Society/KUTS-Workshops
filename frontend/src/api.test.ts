import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
	vi.unstubAllEnvs();
	vi.unstubAllGlobals();
	vi.resetModules();
});

describe("hosted organiser API", () => {
	it("keeps CSRF in memory and sends it only to the same-origin API", async () => {
		vi.stubEnv("MODE", "hosted");
		const fetch = vi
			.fn()
			.mockResolvedValue(
				new Response('{"ok":true}', { status: 200 }),
			);
		vi.stubGlobal("fetch", fetch);
		const { api, setCsrfToken } = await import("./api");
		setCsrfToken("test-csrf");
		await api("/api/intake", {
			method: "POST",
			body: '{"enabled":true}',
		});
		expect(fetch).toHaveBeenCalledWith(
			"/api/intake",
			expect.objectContaining({
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/json",
					"X-CSRF-Token": "test-csrf",
				},
			}),
		);
	});

	it("expires the organiser UI session when the backend returns 401", async () => {
		vi.stubEnv("MODE", "hosted");
		const window = new EventTarget();
		const expired = vi.fn();
		window.addEventListener("organiser-session-expired", expired);
		vi.stubGlobal("window", window);
		vi.stubGlobal(
			"fetch",
			vi
				.fn()
				.mockResolvedValue(
					new Response('{"detail":"Sign in"}', {
						status: 401,
					}),
				),
		);
		const { api } = await import("./api");
		await expect(api("/api/intake")).rejects.toThrow("Sign in");
		expect(expired).toHaveBeenCalledOnce();
	});

	it("preserves the loopback API for explicit local development", async () => {
		vi.stubEnv("MODE", "development");
		const fetch = vi
			.fn()
			.mockResolvedValue(new Response("{}", { status: 200 }));
		vi.stubGlobal("fetch", fetch);
		const { api } = await import("./api");
		await api("/api/health");
		expect(fetch).toHaveBeenCalledWith(
			"http://127.0.0.1:8000/api/health",
			expect.anything(),
		);
	});
});
