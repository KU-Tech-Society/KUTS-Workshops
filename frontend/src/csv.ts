import type { Workshop } from "./types";

export function readCsv(text: string): string[][] {
	const rows: string[][] = [];
	let row: string[] = [];
	let cell = "";
	let quoted = false;

	for (let index = 0; index < text.length; index += 1) {
		const character = text[index];
		if (quoted) {
			if (character === '"' && text[index + 1] === '"') {
				cell += '"';
				index += 1;
			} else if (character === '"') {
				quoted = false;
			} else {
				cell += character;
			}
		} else if (character === '"' && cell.length === 0) {
			quoted = true;
		} else if (character === ",") {
			row.push(cell);
			cell = "";
		} else if (character === "\n") {
			row.push(cell.replace(/\r$/, ""));
			rows.push(row);
			row = [];
			cell = "";
		} else {
			cell += character;
		}
	}
	if (quoted) throw new Error("CSV has an unclosed quoted field.");
	if (cell.length > 0 || row.length > 0) {
		row.push(cell.replace(/\r$/, ""));
		rows.push(row);
	}
	return rows;
}

export function csvCell(value: string | number | null): string {
	let text = String(value ?? "");
	if (/^[\s\u0000-\u001f]*[=+\-@]/.test(text)) text = `'${text}`;
	return `"${text.replace(/"/g, '""')}"`;
}

export function workshopImportCsv(
	submissions: { username: string; workshop: Workshop }[],
): string {
	const accounts = new Map<
		string,
		{ username: string; workshops: Set<Workshop> }
	>();
	for (const submission of submissions) {
		const key = submission.username.toLowerCase();
		const account = accounts.get(key) ?? {
			username: submission.username,
			workshops: new Set<Workshop>(),
		};
		account.workshops.add(submission.workshop);
		accounts.set(key, account);
	}
	return [
		["github_username", "workshop"],
		...Array.from(accounts.values(), (account) => [
			account.username,
			(["CW", "AIW"] as Workshop[])
				.filter((workshop) =>
					account.workshops.has(workshop),
				)
				.join(";"),
		]),
	]
		.map((row) => row.map(csvCell).join(","))
		.join("\r\n");
}
