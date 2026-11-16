import { useEffect, useState } from "react";
import { API, api, HOSTED } from "./api";

interface Inbox {
	enabled: boolean;
	join_code: string;
	expires_at: string;
	submissions: {
		id: string;
		username: string;
		workshop: "CW" | "AIW";
		submitted_at: string;
	}[];
}

export default function LiveInbox({
	disabled,
	onUse,
}: {
	disabled: boolean;
	onUse: (usernames: string) => void;
}) {
	const [inbox, setInbox] = useState<Inbox | null>(null);
	const [connected, setConnected] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		if (HOSTED) {
			let active = true;
			let timer: ReturnType<typeof setTimeout>;
			const poll = async () => {
				try {
					const snapshot =
						await api<Inbox>("/api/intake");
					if (active) {
						setInbox(snapshot);
						setConnected(true);
					}
				} catch {
					if (active) setConnected(false);
				} finally {
					if (active)
						timer = setTimeout(poll, 3000);
				}
			};
			void poll();
			return () => {
				active = false;
				clearTimeout(timer);
			};
		}
		const stream = new EventSource(`${API}/api/intake/events`);
		stream.onmessage = (event) => {
			try {
				setInbox(JSON.parse(event.data) as Inbox);
				setConnected(true);
			} catch {
				setConnected(false);
			}
		};
		stream.onerror = () => setConnected(false);
		return () => stream.close();
	}, []);

	async function toggleCollection() {
		if (!inbox || busy) return;
		setBusy(true);
		setError("");
		try {
			const updated = await api<Inbox>("/api/intake", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					enabled: !inbox.enabled,
				}),
			});
			setInbox(updated);
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Backend unavailable.",
			);
		} finally {
			setBusy(false);
		}
	}

	return (
		<section className="live-inbox" aria-labelledby="inbox-title">
			<div className="inbox-heading">
				<h2 id="inbox-title">
					Student submissions{" "}
					<span className="inbox-count">
						{inbox?.submissions.length ?? 0}
					</span>
				</h2>
				<span
					role="status"
					className={
						connected
							? "connection-live"
							: "warning-text"
					}
				>
					{connected
						? "Live"
						: "Connecting / reconnecting..."}
				</span>
			</div>
			{inbox && (
				<>
					<div className="inbox-controls">
						<button
							className="button button-quiet"
							disabled={
								busy ||
								disabled ||
								!connected
							}
							onClick={
								toggleCollection
							}
						>
							{inbox.enabled
								? "Close collection"
								: "Open collection"}
						</button>
						<span>
							{inbox.enabled
								? "Collection open"
								: "Collection closed"}
						</span>
						<span className="workshop-code">
							Workshop code:{" "}
							<code>
								{
									inbox.join_code
								}
							</code>
						</span>
					</div>
					<p className="muted small">
						Session expires{" "}
						{new Date(
							inbox.expires_at,
						).toLocaleTimeString()}
						. New submissions remain
						separate from invitation
						reviews.
					</p>
					{inbox.submissions.length > 0 ? (
						<>
							<div className="inbox-rows">
								<table>
									<thead>
										<tr>
											<th>
												Username
											</th>
											<th>
												Workshop
											</th>
											<th>
												Received
											</th>
										</tr>
									</thead>
									<tbody>
										{inbox.submissions.map(
											(
												row,
											) => (
												<tr
													key={
														row.id
													}
												>
													<td>
														{
															row.username
														}
													</td>
													<td>
														{row.workshop ===
														"AIW"
															? "KU Artificial Intelligence Workshops (AIW)"
															: "KU Computing Workshops (CW)"}
													</td>
													<td>
														{new Date(
															row.submitted_at,
														).toLocaleTimeString()}
													</td>
												</tr>
											),
										)}
									</tbody>
								</table>
							</div>
							<button
								className="button button-primary"
								disabled={
									disabled ||
									!connected
								}
								onClick={() =>
									onUse(
										inbox.submissions
											.map(
												(
													row,
												) =>
													row.username,
											)
											.join(
												"\n",
											),
									)
								}
							>
								Use usernames in
								fresh import
							</button>
						</>
					) : (
						<p className="muted">
							No usernames received
							yet.
						</p>
					)}
				</>
			)}
			{error && (
				<p className="alert error" role="alert">
					{error}
				</p>
			)}
		</section>
	);
}
