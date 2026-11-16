import { describe, expect, it } from "vitest";
import { csvCell, readCsv } from "./csv";

describe("CSV helpers", () => {
  it("parses quoted commas and escaped quotes", () => {
    expect(readCsv('name,username\n"Student, Example",octocat\n"She said ""hi""",dev')).toEqual([
      ["name", "username"],
      ["Student, Example", "octocat"],
      ['She said "hi"', "dev"],
    ]);
  });

  it("escapes formula-leading export cells and CSV quotes", () => {
    expect(csvCell("=1+1")).toBe("\"'=1+1\"");
    expect(csvCell('a "quote"')).toBe('"a ""quote"""');
  });
});
