import { describe, expect, it } from "vitest";
import { csvCell, readCsv, workshopImportCsv } from "./csv";

describe("CSV helpers", () => {
	it("parses quoted commas and escaped quotes", () => {
		expect(
			readCsv(
				'name,username\n"Student, Example",octocat\n"She said ""hi""",dev',
			),
		).toEqual([
			["name", "username"],
			["Student, Example", "octocat"],
			['She said "hi"', "dev"],
		]);
	});

	it("escapes formula-leading export cells and CSV quotes", () => {
		expect(csvCell("=1+1")).toBe('"\'=1+1"');
		expect(csvCell('a "quote"')).toBe('"a ""quote"""');
	});

	it("preserves and combines both workshop applications when importing the live inbox", () => {
		const contents = workshopImportCsv([
			{ username: "Student-One", workshop: "CW" },
			{ username: "student-one", workshop: "AIW" },
			{ username: "student-two", workshop: "AIW" },
			{ username: "STUDENT-ONE", workshop: "CW" },
		]);
		expect(readCsv(contents)).toEqual([
			["github_username", "workshop"],
			["Student-One", "CW;AIW"],
			["student-two", "AIW"],
		]);
	});
});
