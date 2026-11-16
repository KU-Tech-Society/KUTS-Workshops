import { FormEvent, useState } from "react";

const endpoint = import.meta.env.VITE_STUDENT_API_URL?.replace(/\/$/, "") ?? "";

const workshops = {
	CW: "KU Computing Workshops",
	AIW: "KU Artificial Intelligence Workshops",
};

export default function StudentApp() {
	const [workshop, setWorkshop] = useState<keyof typeof workshops | null>(
		null,
	);
	const [joining, setJoining] = useState(false);
	const [username, setUsername] = useState("");
	const [code, setCode] = useState("");
	const [busy, setBusy] = useState(false);
	const [received, setReceived] = useState(false);
	const [error, setError] = useState("");

	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (busy || !workshop) return;
		setBusy(true);
		setError("");
		try {
			const response = await fetch(
				`${endpoint}/api/submissions`,
				{
					method: "POST",
					headers: {
						"Content-Type":
							"application/json",
					},
					body: JSON.stringify({
						username: username.trim(),
						join_code: code.trim(),
						workshop,
					}),
					signal: AbortSignal.timeout(15000),
					credentials: "omit",
				},
			);
			const data = await response.json().catch(() => ({}));
			if (!response.ok || data.accepted !== true) {
				throw new Error(
					typeof data.detail === "string"
						? data.detail
						: "Submission was not accepted. Contact the organiser.",
				);
			}
			setReceived(true);
			setUsername("");
			setCode("");
		} catch (cause) {
			setError(
				cause instanceof TypeError ||
					(cause instanceof DOMException &&
						cause.name === "TimeoutError")
					? "Could not confirm receipt. Check your connection or ask the organiser; resubmitting the same username is safe."
					: cause instanceof Error
						? cause.message
						: "Could not submit. Contact the organiser.",
			);
		} finally {
			setBusy(false);
		}
	}

	return (
		<main className="student-shell">
			<header className="student-brand">
				<img
					src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
					alt="GitHub"
					width="48"
					height="48"
					referrerPolicy="no-referrer"
				/>
				<p className="eyebrow">KU Workshops</p>
			</header>
			<h1>
				{joining
					? "Join the workshop"
					: "Choose your workshop"}
			</h1>
			{joining && workshop && (
				<p className="subtitle">
					{workshops[workshop]}
				</p>
			)}
			{!joining ? (
				<form
					className="student-form"
					onSubmit={(event) => {
						event.preventDefault();
						if (workshop) setJoining(true);
					}}
				>
					<fieldset className="workshop-options">
						<legend>Workshop</legend>
						{(
							Object.keys(
								workshops,
							) as (keyof typeof workshops)[]
						).map((id) => (
							<label
								className="workshop-option"
								key={id}
							>
								<input
									type="radio"
									name="workshop"
									value={
										id
									}
									checked={
										workshop ===
										id
									}
									onChange={() =>
										setWorkshop(
											id,
										)
									}
									required
								/>
								<span>
									{
										workshops[
											id
										]
									}
								</span>
							</label>
						))}
					</fieldset>
					<button
						className="button button-primary"
						type="submit"
						disabled={!workshop}
					>
						Continue to join
					</button>
				</form>
			) : received ? (
				<section
					className="student-receipt"
					role="status"
				>
					<h2>Username received</h2>
					<p>
						Your organiser will review your
						account. You still need to
						accept any organisation
						invitation on GitHub.
					</p>
				</section>
			) : (
				<form
					onSubmit={submit}
					className="student-form"
				>
					<label
						className="field-label"
						htmlFor="student-username"
					>
						GitHub username
					</label>
					<input
						id="student-username"
						name="username"
						autoCapitalize="none"
						autoCorrect="off"
						spellCheck={false}
						autoComplete="off"
						maxLength={256}
						required
						value={username}
						onChange={(event) =>
							setUsername(
								event.target
									.value,
							)
						}
						disabled={busy}
						placeholder="your-github-username"
					/>
					<label
						className="field-label"
						htmlFor="workshop-code"
					>
						Workshop code
					</label>
					<input
						id="workshop-code"
						name="workshop-code"
						autoCapitalize="characters"
						autoCorrect="off"
						spellCheck={false}
						autoComplete="off"
						placeholder="K7MP4R"
						maxLength={128}
						required
						value={code}
						onChange={(event) =>
							setCode(
								event.target
									.value,
							)
						}
						disabled={busy}
					/>
					<p className="muted small">
						Your username is shared with the
						workshop organiser and held
						temporarily for account review.
						Do not enter your password,
						token, or email.
					</p>
					{!endpoint && (
						<p
							className="alert error"
							role="alert"
						>
							Submissions are not
							configured. Contact the
							organiser.
						</p>
					)}
					{error && (
						<p
							className="alert error"
							role="alert"
						>
							{error}
						</p>
					)}
					<button
						className="button button-primary"
						type="submit"
						disabled={
							busy ||
							!endpoint ||
							!username.trim() ||
							!code.trim()
						}
					>
						{busy
							? "Submitting..."
							: "Submit username"}
					</button>
					<button
						className="button button-quiet"
						type="button"
						disabled={busy}
						onClick={() => {
							setJoining(false);
							setError("");
						}}
					>
						Change workshop
					</button>
				</form>
			)}
			<footer>KU Workshops</footer>
		</main>
	);
}
