import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode, command }) => {
	if (mode === "student" && command === "build") {
		const endpoint = loadEnv(
			mode,
			".",
			"VITE_",
		).VITE_STUDENT_API_URL;
		let valid = false;
		try {
			const url = new URL(endpoint);
			valid =
				url.protocol === "https:" &&
				!url.username &&
				!url.password &&
				url.pathname === "/" &&
				!url.search &&
				!url.hash &&
				!["localhost", "127.0.0.1", "[::1]"].includes(
					url.hostname,
				);
		} catch {
			valid = false;
		}
		if (!valid)
			throw new Error(
				"Set VITE_STUDENT_API_URL to the HTTPS backend origin before building the student page.",
			);
	}
	return {
		plugins: [
			react(),
			{
				name: "student-root-page",
				enforce: "post",
				generateBundle(_, bundle) {
					if (mode !== "student") return;
					const entry = bundle["student.html"];
					if (entry?.type === "asset")
						this.emitFile({
							type: "asset",
							fileName: "index.html",
							source: entry.source,
						});
				},
			},
		],
		base: mode === "hosted" ? "/" : "./",
		build:
			mode === "student"
				? {
						outDir: "dist-student",
						rollupOptions: {
							input: "student.html",
						},
					}
				: mode === "hosted"
					? {
							outDir: "../public",
							emptyOutDir: true,
						}
					: undefined,
		server: {
			host: "127.0.0.1",
			port: 5173,
			strictPort: true,
		},
	};
});
