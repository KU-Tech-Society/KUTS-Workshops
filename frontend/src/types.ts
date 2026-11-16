export type Workshop = "CW" | "AIW";

export const workshopNames: Record<Workshop, string> = {
	CW: "Computing Workshops",
	AIW: "Artificial Intelligence Workshops",
};

export type EntryStatus =
	| "awaiting_resolution"
	| "invalid_input"
	| "duplicate_input"
	| "ready_to_invite"
	| "already_member"
	| "pending_invitation"
	| "account_not_found"
	| "lookup_failed"
	| "rate_limited";

export interface PreviewEntry {
	id: string;
	submitted_username: string;
	login: string | null;
	display_name: string | null;
	avatar_url: string | null;
	profile_url: string | null;
	status: EntryStatus;
	message: string | null;
	source_row: number;
	workshops: Workshop[];
}

export interface Team {
	id: number;
	name: string;
	slug: string;
}

export interface Preview {
	id: string;
	organization: string;
	expires_at: string;
	resolved: boolean;
	team: Team | null;
	entries: PreviewEntry[];
}

export interface BatchResult {
	entry_id: string;
	submitted_username: string;
	login: string | null;
	display_name?: string | null;
	workshops: Workshop[];
	status:
		| "invitation_sent"
		| "already_member"
		| "pending_invitation"
		| "failed"
		| "status_unknown";
	message: string;
	invitation_id: number | null;
	rate_limited: boolean;
	retry_after_seconds: number | null;
}

export interface Batch {
	id: string;
	organization: string;
	team_name: string | null;
	created_at: string;
	running: boolean;
	results: BatchResult[];
	totals: { sent: number; failed: number; skipped: number };
}
