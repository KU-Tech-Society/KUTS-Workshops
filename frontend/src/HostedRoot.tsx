import { useEffect, useState } from "react";
import App from "./App";
import { api, setCsrfToken } from "./api";

interface Session {
	login: string;
	csrf_token: string;
}

export default function HostedRoot() {
	const [session, setSession] = useState<Session | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;
		const expired = () => {
			setSession(null);
			setCsrfToken("");
		};
		window.addEventListener("organiser-session-expired", expired);
		void api<Session>("/api/auth/session")
			.then((value) => {
				if (active) {
					setCsrfToken(value.csrf_token);
					setSession(value);
				}
			})
			.catch((cause) => {
				if (active)
					setError(
						cause instanceof Error
							? cause.message
							: "Sign-in unavailable.",
					);
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
			window.removeEventListener(
				"organiser-session-expired",
				expired,
			);
		};
	}, []);

	async function logout() {
		try {
			await api("/api/auth/logout", {
				method: "POST",
				body: "{}",
			});
			setCsrfToken("");
			setSession(null);
			setError("");
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Could not sign out.",
			);
		}
	}

	if (loading)
		return (
			<main className="student-shell">
				<p role="status">
					Checking organiser session...
				</p>
			</main>
		);
	if (!session)
		return (
			<main className="student-shell">
				<h1>KU Workshops</h1>
				<h2>Organiser sign-in</h2>
				<p>Approved GitHub accounts only.</p>
				{error && (
					<p
						className="warning-text"
						role="status"
					>
						{error}
					</p>
				)}
				<a
					className="button button-primary"
					href="/auth/login"
				>
					Sign in with GitHub
				</a>
			</main>
		);

	return (
		<>
			<div className="organiser-session">
				<span>Signed in as {session.login}</span>
				<button
					className="button button-quiet"
					onClick={logout}
				>
					Sign out
				</button>
			</div>
			{error && (
				<p role="alert" className="alert error">
					{error}
				</p>
			)}
			<App />
		</>
	);
}
