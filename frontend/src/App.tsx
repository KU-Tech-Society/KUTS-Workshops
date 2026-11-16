import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { csvCell, readCsv } from "./csv";
import LiveInbox from "./LiveInbox";
import { api, HOSTED } from "./api";
import type { Batch, EntryStatus, Preview, PreviewEntry, Team } from "./types";

const DEFAULT_MAX_INPUT_BYTES = 1_048_576;
const DEFAULT_MAX_INPUT_ROWS = 500;
const DEFAULT_MAX_INVITES = 50;
const labels: Record<EntryStatus, string> = {
	awaiting_resolution: "Not resolved",
	invalid_input: "Invalid input",
	duplicate_input: "Duplicate input",
	ready_to_invite: "Ready to invite",
	already_member: "Already a member",
	pending_invitation: "Invitation pending",
	account_not_found: "Account not found",
	lookup_failed: "Lookup failed",
	rate_limited: "Rate limited",
};

function App() {
	const [inputMode, setInputMode] = useState<"lines" | "csv">("lines");
	const [text, setText] = useState("");
	const [hasHeader, setHasHeader] = useState(true);
	const [usernameColumn, setUsernameColumn] = useState(0);
	const [teams, setTeams] = useState<Team[]>([]);
	const [teamId, setTeamId] = useState<number | null>(null);
	const [preview, setPreview] = useState<Preview | null>(null);
	const [batch, setBatch] = useState<Batch | null>(null);
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [filter, setFilter] = useState("");
	const [step, setStep] = useState<
		"import" | "review" | "confirm" | "results"
	>("import");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [notice, setNotice] = useState("");
	const [tokenConfigured, setTokenConfigured] = useState<boolean | null>(
		null,
	);
	const [reviewConfirmed, setReviewConfirmed] = useState(false);
	const fileInput = useRef<HTMLInputElement>(null);
	const [maxInputBytes, setMaxInputBytes] = useState(
		DEFAULT_MAX_INPUT_BYTES,
	);
	const [maxInputRows, setMaxInputRows] = useState(
		DEFAULT_MAX_INPUT_ROWS,
	);
	const [maxInvites, setMaxInvites] = useState(DEFAULT_MAX_INVITES);

	useEffect(() => {
		void Promise.allSettled([
			api<{
				github_token_configured: boolean;
				max_input_bytes: number;
				max_input_rows: number;
				max_invites_per_batch: number;
			}>("/api/health"),
			api<Team[]>("/api/teams"),
		]).then(([health, availableTeams]) => {
			if (health.status === "fulfilled") {
				setTokenConfigured(
					health.value.github_token_configured,
				);
				setMaxInputBytes(health.value.max_input_bytes);
				setMaxInputRows(health.value.max_input_rows);
				setMaxInvites(
					health.value.max_invites_per_batch,
				);
			}
			if (availableTeams.status === "fulfilled")
				setTeams(availableTeams.value);
			else
				setError(
					availableTeams.reason instanceof Error
						? availableTeams.reason.message
						: "Could not connect to the local backend.",
				);
		});
	}, []);

	useEffect(() => {
		if (!HOSTED) return;
		void api<{ batch: Batch | null }>("/api/batches/latest")
			.then(({ batch: saved }) => {
				if (saved) {
					setBatch(saved);
					setStep("results");
				}
			})
			.catch((cause) => {
				setError(
					cause instanceof Error
						? `Could not recover saved batch results: ${cause.message}`
						: "Could not recover saved batch results. Review GitHub before starting another batch.",
				);
			});
	}, []);

	useEffect(() => {
		if (!HOSTED || !batch?.running) return;
		let active = true;
		let timer: ReturnType<typeof setTimeout>;
		const poll = async () => {
			try {
				const current = await api<Batch>(
					`/api/batches/${batch.id}`,
				);
				if (active) setBatch(current);
			} catch (cause) {
				if (active) {
					setError(
						cause instanceof Error
							? `Could not load batch results: ${cause.message}`
							: "Could not load batch results.",
					);
				}
			} finally {
				if (active) timer = setTimeout(poll, 5000);
			}
		};
		void poll();
		return () => {
			active = false;
			clearTimeout(timer);
		};
	}, [batch?.id, batch?.running]);

	const csvRows = useMemo(() => {
		if (inputMode !== "csv" || !text) return [];
		try {
			return readCsv(text);
		} catch {
			return [];
		}
	}, [inputMode, text]);
	const headers = csvRows[0] ?? [];
	const previewRows = preview?.entries ?? [];
	const visibleRows = previewRows.filter((entry) => {
		const query = filter.trim().toLowerCase();
		return (
			!query ||
			[
				entry.submitted_username,
				entry.login ?? "",
				labels[entry.status],
			].some((value) => value.toLowerCase().includes(query))
		);
	});
	const readyEntries = previewRows.filter(
		(entry) => entry.status === "ready_to_invite",
	);
	const selectedEntries = readyEntries.filter((entry) =>
		selected.has(entry.id),
	);

	async function loadCsv(event: ChangeEvent<HTMLInputElement>) {
		const file = event.target.files?.[0];
		if (!file) return;
		if (file.size > maxInputBytes) {
			setError(
				`CSV exceeds the ${formatBytes(maxInputBytes)} input limit.`,
			);
			return;
		}
		setError("");
		try {
			setText(await file.text());
			setUsernameColumn(0);
		} catch {
			setError("Could not read the selected CSV file.");
		}
	}

	async function createPreview() {
		setError("");
		setNotice("");
		setBusy(true);
		try {
			const created = await api<Preview>("/api/previews", {
				method: "POST",
				body: JSON.stringify({
					source: inputMode,
					text,
					username_column:
						inputMode === "csv"
							? usernameColumn
							: null,
					has_header:
						inputMode === "csv" &&
						hasHeader,
				}),
			});
			setPreview(created);
			setText("");
			if (fileInput.current) fileInput.current.value = "";
			setSelected(new Set());
			setStep("review");
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Could not import usernames.",
			);
		} finally {
			setBusy(false);
		}
	}

	async function resolveAccounts() {
		if (!preview) return;
		setError("");
		setBusy(true);
		try {
			const resolved = await api<Preview>(
				`/api/previews/${preview.id}/resolve`,
				{
					method: "POST",
					body: JSON.stringify({
						team_id: teamId,
					}),
				},
			);
			setPreview(resolved);
			setSelected(
				new Set(
					resolved.entries
						.filter(
							(entry) =>
								entry.status ===
								"ready_to_invite",
						)
						.map((entry) => entry.id),
				),
			);
			setNotice(
				"Lookups are read-only. Verify every resolved account visually; a valid GitHub account does not prove student identity.",
			);
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Account resolution failed.",
			);
		} finally {
			setBusy(false);
		}
	}

	async function sendInvitations() {
		if (!preview || selectedEntries.length === 0) return;
		setError("");
		setBusy(true);
		try {
			const sent = await api<Batch>(
				`/api/previews/${preview.id}/confirm-and-send`,
				{
					method: "POST",
					body: JSON.stringify({
						confirmed: true,
						selected_entry_ids:
							selectedEntries.map(
								(entry) =>
									entry.id,
							),
					}),
				},
			);
			setBatch(sent);
			setStep("results");
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Invitation batch failed.",
			);
			if (HOSTED) {
				const saved = await api<{
					batch: Batch | null;
				}>("/api/batches/latest").catch(() => null);
				if (saved?.batch) {
					setBatch(saved.batch);
					setStep("results");
				}
			}
		} finally {
			setBusy(false);
		}
	}

	async function clearSession() {
		if (
			!window.confirm(
				"Clear student submissions, imported usernames, previews, and results? This also closes collection and rotates the workshop code.",
			)
		)
			return;
		setError("");
		setBusy(true);
		try {
			await api("/api/session", {
				method: "DELETE",
				body: JSON.stringify({ confirm: true }),
			});
			setText("");
			if (fileInput.current) fileInput.current.value = "";
			setPreview(null);
			setBatch(null);
			setSelected(new Set());
			setStep("import");
			setNotice("Session data cleared from the backend.");
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Could not clear the session.",
			);
		} finally {
			setBusy(false);
		}
	}

	function toggleEntry(id: string) {
		setSelected((current) => {
			const next = new Set(current);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			return next;
		});
	}

	function exportResults() {
		if (!batch) return;
		const rows = [
			[
				"Submitted username",
				"Resolved login",
				"Outcome",
				"Invitation ID",
				"Details",
			],
			...batch.results.map((result) => [
				result.submitted_username,
				result.login ?? "",
				result.status,
				result.invitation_id ?? "",
				result.message,
			]),
		];
		const contents = rows
			.map((row) => row.map(csvCell).join(","))
			.join("\r\n");
		const url = URL.createObjectURL(
			new Blob([contents], {
				type: "text/csv;charset=utf-8",
			}),
		);
		const anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = "workshop-invitation-results.csv";
		anchor.click();
		URL.revokeObjectURL(url);
	}

	return (
		<main className="shell">
			<header className="topbar">
				<div>
					<p className="eyebrow">
						KU COMPUTING WORKSHOPS
					</p>
					<h1>Student onboarding</h1>
					<p className="subtitle">
						Review GitHub accounts before
						sending organisation
						invitations.
					</p>
				</div>
				<button
					className="button button-quiet"
					onClick={clearSession}
					disabled={busy}
				>
					Clear session
				</button>
			</header>

			<div className="notice" role="note">
				<strong>
					{HOSTED
						? "Organiser-only access."
						: "Local-only organiser tool."}
				</strong>{" "}
				Invitations grant organisation membership and
				can expose existing repositories. GitHub
				accounts do not verify student identity.
				{tokenConfigured === false && (
					<p className="inline-warning">
						{HOSTED
							? "GitHub invitation credentials are not configured. Contact the society administrator."
							: "Configure GITHUB_TOKEN in the backend .env file to use GitHub features."}
					</p>
				)}
			</div>

			<LiveInbox
				disabled={busy || step !== "import"}
				onUse={(usernames) => {
					setInputMode("lines");
					setText(usernames);
					setNotice(
						"Student usernames copied into a fresh import. Import, resolve, and visually review before confirming invitations.",
					);
				}}
			/>

			<nav className="steps" aria-label="Onboarding progress">
				{(
					[
						"import",
						"review",
						"confirm",
						"results",
					] as const
				).map((item, index) => (
					<div
						className={`step ${step === item ? "active" : ""} ${["import", "review", "confirm", "results"].indexOf(step) > index ? "complete" : ""}`}
						key={item}
					>
						<span>{index + 1}</span>
						{item === "import"
							? "Import"
							: item === "review"
								? "Resolve & review"
								: item ===
									  "confirm"
									? "Confirm"
									: "Results"}
					</div>
				))}
			</nav>

			{error && (
				<div className="alert error" role="alert">
					{error}
				</div>
			)}
			{notice && (
				<div className="alert info" role="status">
					{notice}
				</div>
			)}

			{step === "import" && (
				<section className="card">
					<h2>1. Import usernames</h2>
					<p className="muted">
						Paste one GitHub username per
						line, or import a CSV. Input is
						limited to{" "}
						{formatBytes(maxInputBytes)} and{" "}
						{maxInputRows.toLocaleString()}{" "}
						rows.
					</p>
					<div
						className="choice-row"
						role="group"
						aria-label="Input format"
					>
						<button
							className={
								inputMode ===
								"lines"
									? "choice selected"
									: "choice"
							}
							onClick={() =>
								setInputMode(
									"lines",
								)
							}
						>
							Paste usernames
						</button>
						<button
							className={
								inputMode ===
								"csv"
									? "choice selected"
									: "choice"
							}
							onClick={() =>
								setInputMode(
									"csv",
								)
							}
						>
							CSV
						</button>
					</div>
					{inputMode === "csv" && (
						<div className="csv-controls">
							<label
								className="field-label"
								htmlFor="csv-file"
							>
								Choose a CSV
								file
							</label>
							<input
								ref={fileInput}
								id="csv-file"
								type="file"
								accept=".csv,text/csv"
								onChange={
									loadCsv
								}
							/>
							<label className="checkbox-line">
								<input
									type="checkbox"
									checked={
										hasHeader
									}
									onChange={(
										event,
									) =>
										setHasHeader(
											event
												.target
												.checked,
										)
									}
								/>
								First row is a
								header
							</label>
							{csvRows.length > 0 && (
								<label
									className="field-label"
									htmlFor="username-column"
								>
									Username
									column
									<select
										id="username-column"
										value={
											usernameColumn
										}
										onChange={(
											event,
										) =>
											setUsernameColumn(
												Number(
													event
														.target
														.value,
												),
											)
										}
									>
										{(hasHeader
											? headers
											: csvRows[0]
										).map(
											(
												header,
												index,
											) => (
												<option
													key={
														index
													}
													value={
														index
													}
												>
													{hasHeader
														? header ||
															`Column ${index + 1}`
														: `Column ${index + 1} (e.g. ${header || "empty"})`}
												</option>
											),
										)}
									</select>
								</label>
							)}
							{csvRows.length > 0 && (
								<p className="muted small">
									Detected
									columns:{" "}
									{headers
										.map(
											(
												value,
												index,
											) =>
												`${index + 1}: ${value || "(blank)"}`,
										)
										.join(
											" · ",
										)}
								</p>
							)}
						</div>
					)}
					<label
						className="field-label"
						htmlFor="usernames"
					>
						{inputMode === "csv"
							? "CSV contents"
							: "GitHub usernames"}
					</label>
					<textarea
						id="usernames"
						rows={10}
						value={text}
						onChange={(event) =>
							setText(
								event.target
									.value,
							)
						}
						placeholder={
							inputMode === "csv"
								? "Upload a CSV or paste CSV rows here"
								: "octocat\nstudent-example"
						}
					/>
					<div className="form-footer">
						<span className="muted">
							{text.length.toLocaleString()}{" "}
							characters
						</span>
						<button
							className="button button-primary"
							onClick={createPreview}
							disabled={
								busy ||
								!text.trim()
							}
						>
							{busy
								? "Importing…"
								: "Import and continue"}
						</button>
					</div>
				</section>
			)}

			{step === "review" && preview && (
				<section className="card">
					<div className="section-heading">
						<div>
							<h2>
								2. Resolve and
								review
							</h2>
							<p className="muted">
								Fixed
								organisation:{" "}
								<strong>
									{
										preview.organization
									}
								</strong>
								. No invitations
								are sent during
								lookup.
							</p>
						</div>
					</div>
					{!preview.resolved && (
						<>
							<label
								className="field-label"
								htmlFor="team"
							>
								Optional team
								assignment
							</label>
							<select
								id="team"
								value={
									teamId ??
									""
								}
								onChange={(
									event,
								) =>
									setTeamId(
										event
											.target
											.value
											? Number(
													event
														.target
														.value,
												)
											: null,
									)
								}
							>
								<option value="">
									No team
								</option>
								{teams.map(
									(
										team,
									) => (
										<option
											key={
												team.id
											}
											value={
												team.id
											}
										>
											{
												team.name
											}{" "}
											(
											{
												team.slug
											}

											)
										</option>
									),
								)}
							</select>
							<p className="warning-text">
								Team membership
								can grant
								existing
								repository
								access. This
								tool does not
								change
								repository
								permissions.
							</p>
							<button
								className="button button-primary"
								onClick={
									resolveAccounts
								}
								disabled={busy}
							>
								{busy
									? "Resolving accounts…"
									: "Resolve accounts (read-only)"}
							</button>
						</>
					)}
					{preview.resolved && (
						<>
							<p className="muted">
								Selected team:{" "}
								<strong>
									{preview.team
										? `${preview.team.name} (${preview.team.slug})`
										: "None"}
								</strong>
							</p>
							<div className="table-actions">
								<label
									className="field-label search-label"
									htmlFor="search"
								>
									Filter
									accounts
								</label>
								<input
									id="search"
									type="search"
									value={
										filter
									}
									onChange={(
										event,
									) =>
										setFilter(
											event
												.target
												.value,
										)
									}
									placeholder="Username or status"
								/>
								<button
									className="button button-quiet"
									onClick={() =>
										setSelected(
											new Set(
												readyEntries
													.slice(
														0,
														maxInvites,
													)
													.map(
														(
															entry,
														) =>
															entry.id,
													),
											),
										)
									}
								>
									Select
									up to
									limit
								</button>
								<button
									className="button button-quiet"
									onClick={() =>
										setSelected(
											new Set(),
										)
									}
								>
									Deselect
									all
								</button>
							</div>
							<div className="table-wrap">
								<table>
									<thead>
										<tr>
											<th>
												Invite
											</th>
											<th>
												Submitted
											</th>
											<th>
												Resolved
												account
											</th>
											<th>
												Status
											</th>
										</tr>
									</thead>
									<tbody>
										{visibleRows.map(
											(
												entry,
											) => (
												<PreviewRow
													key={
														entry.id
													}
													entry={
														entry
													}
													checked={selected.has(
														entry.id,
													)}
													atLimit={
														!selected.has(
															entry.id,
														) &&
														selected.size >=
															maxInvites
													}
													onToggle={() =>
														toggleEntry(
															entry.id,
														)
													}
												/>
											),
										)}
									</tbody>
								</table>
							</div>
							<p className="muted small">
								{
									readyEntries.length
								}{" "}
								eligible ·{" "}
								{
									selectedEntries.length
								}{" "}
								selected
								(maximum{" "}
								{maxInvites}) ·{" "}
								{
									previewRows.length
								}{" "}
								rows
							</p>
							<div className="form-footer">
								<button
									className="button button-quiet"
									onClick={() => {
										setPreview(
											null,
										);
										setStep(
											"import",
										);
									}}
								>
									Start a
									fresh
									import
								</button>
								<button
									className="button button-primary"
									onClick={() => {
										setReviewConfirmed(
											false,
										);
										setStep(
											"confirm",
										);
									}}
									disabled={
										!selectedEntries.length
									}
								>
									Review
									invitation
								</button>
							</div>
						</>
					)}
				</section>
			)}

			{step === "confirm" && preview && (
				<section className="card">
					<h2>3. Confirm invitations</h2>
					<div className="confirmation">
						<p>
							<span>
								Organisation
							</span>
							<strong>
								{
									preview.organization
								}
							</strong>
						</p>
						<p>
							<span>Role</span>
							<strong>
								Ordinary member
							</strong>
						</p>
						<p>
							<span>Team</span>
							<strong>
								{preview.team
									? `${preview.team.name} (${preview.team.slug})`
									: "None"}
							</strong>
						</p>
						<p>
							<span>
								Invitations to
								send
							</span>
							<strong>
								{
									selectedEntries.length
								}
							</strong>
						</p>
					</div>
					<h3>Exact resolved usernames</h3>
					<ul className="username-list">
						{selectedEntries.map(
							(entry) => (
								<li
									key={
										entry.id
									}
								>
									{
										entry.login
									}
								</li>
							),
						)}
					</ul>
					<p className="warning-text">
						Team membership can grant
						existing repository access.
						Invitations are not membership;
						students must accept them.
					</p>
					<label className="checkbox-line confirmation-check">
						<input
							type="checkbox"
							checked={
								reviewConfirmed
							}
							onChange={(event) =>
								setReviewConfirmed(
									event
										.target
										.checked,
								)
							}
						/>
						I have visually reviewed these
						resolved accounts and approve
						this exact invitation batch.
					</label>
					<div className="form-footer">
						<button
							className="button button-quiet"
							onClick={() => {
								setReviewConfirmed(
									false,
								);
								setStep(
									"review",
								);
							}}
							disabled={busy}
						>
							Back to review
						</button>
						<button
							className="button button-danger"
							onClick={
								sendInvitations
							}
							disabled={
								busy ||
								!reviewConfirmed
							}
						>
							{busy
								? "Sending invitations…"
								: `Send ${selectedEntries.length} invitations to ${preview.organization}`}
						</button>
					</div>
				</section>
			)}

			{step === "results" && batch && (
				<section className="card">
					<h2>4. Results</h2>
					{batch.running && (
						<p role="status">
							Batch processing or
							recovery is in progress.
							Do not start a
							replacement batch.
						</p>
					)}
					<p className="muted">
						Batch time:{" "}
						{new Date(
							batch.created_at,
						).toLocaleString()}{" "}
						· {batch.organization}
					</p>
					<div className="totals">
						<div>
							<strong>
								{
									batch
										.totals
										.sent
								}
							</strong>
							<span>Sent</span>
						</div>
						<div>
							<strong>
								{
									batch
										.totals
										.failed
								}
							</strong>
							<span>
								Failed / unknown
							</span>
						</div>
						<div>
							<strong>
								{
									batch
										.totals
										.skipped
								}
							</strong>
							<span>Skipped</span>
						</div>
					</div>
					<div className="table-wrap">
						<table>
							<thead>
								<tr>
									<th>
										Username
									</th>
									<th>
										Outcome
									</th>
									<th>
										Invitation
										ID
									</th>
									<th>
										Details
									</th>
								</tr>
							</thead>
							<tbody>
								{batch.results.map(
									(
										result,
									) => (
										<tr
											key={
												result.entry_id
											}
										>
											<td>
												{result.login ??
													result.submitted_username}
											</td>
											<td>
												<span
													className={`badge ${result.status}`}
												>
													{result.status.replace(
														/_/g,
														" ",
													)}
												</span>
											</td>
											<td>
												{result.invitation_id ??
													"—"}
											</td>
											<td>
												{
													result.message
												}
												{result.retry_after_seconds !==
													null &&
													result.retry_after_seconds !==
														undefined &&
													` Retry after ${result.retry_after_seconds} seconds.`}
											</td>
										</tr>
									),
								)}
							</tbody>
						</table>
					</div>
					<p className="warning-text">
						Students must accept their
						invitations before joining. Do
						not retry unknown or failed
						accounts without a new review.
					</p>
					<div className="form-footer">
						<button
							className="button button-quiet"
							onClick={exportResults}
						>
							Export results CSV
						</button>
						<button
							className="button button-primary"
							onClick={clearSession}
							disabled={busy}
						>
							Clear session
						</button>
					</div>
				</section>
			)}

			<footer>
				KU-Computing-Workshops ·{" "}
				{HOSTED
					? "Organiser workflow"
					: "Local organiser workflow"}{" "}
				· No student identity verification
			</footer>
		</main>
	);
}

function formatBytes(bytes: number): string {
	return bytes >= 1_048_576
		? `${(bytes / 1_048_576).toLocaleString()} MiB`
		: `${bytes.toLocaleString()} bytes`;
}

function PreviewRow({
	entry,
	checked,
	atLimit,
	onToggle,
}: {
	entry: PreviewEntry;
	checked: boolean;
	atLimit: boolean;
	onToggle: () => void;
}) {
	const canSelect = entry.status === "ready_to_invite";
	return (
		<tr>
			<td>
				<input
					aria-label={`Select ${entry.login ?? entry.submitted_username}`}
					type="checkbox"
					checked={checked}
					disabled={!canSelect || atLimit}
					onChange={onToggle}
				/>
			</td>
			<td>
				<span>
					{entry.submitted_username || "(blank)"}
				</span>
				<small>Row {entry.source_row}</small>
			</td>
			<td>
				{entry.login ? (
					<div className="account">
						{entry.avatar_url && (
							<img
								src={
									entry.avatar_url
								}
								alt=""
								referrerPolicy="no-referrer"
							/>
						)}
						<div>
							<a
								href={
									entry.profile_url ??
									undefined
								}
								target="_blank"
								rel="noopener noreferrer"
							>
								{entry.login}
							</a>
							{entry.display_name && (
								<small>
									{
										entry.display_name
									}
								</small>
							)}
						</div>
					</div>
				) : (
					"—"
				)}
			</td>
			<td>
				<span className={`badge ${entry.status}`}>
					{labels[entry.status]}
				</span>
				{entry.message && (
					<small>{entry.message}</small>
				)}
			</td>
		</tr>
	);
}

export default App;
