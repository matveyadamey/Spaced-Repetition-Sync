import { describe, expect, it } from "vitest";
import { dedupeByQuestion, parseCards } from "./parser";

describe("parseCards", () => {
  it("parses single-line cards with default delimiter", () => {
    const cards = parseCards(
      "What is Python? :: A language\n\nWhat is SM-2? :: Algorithm",
      "::",
      "note.md",
    );
    expect(cards).toEqual([
      { question: "What is Python?", answer: "A language", source_file: "note.md" },
      { question: "What is SM-2?", answer: "Algorithm", source_file: "note.md" },
    ]);
  });

  it("parses multiline cards", () => {
    const cards = parseCards("Q line?\nmore\n::\nA line\nmore", "::", "a.md");
    expect(cards).toHaveLength(1);
    expect(cards[0].question).toBe("Q line?\nmore");
    expect(cards[0].answer).toBe("A line\nmore");
  });

  it("skips blocks without question mark", () => {
    const cards = parseCards("No mark :: answer", "::", "a.md");
    expect(cards).toEqual([]);
  });

  it("skips empty delimiter", () => {
    expect(parseCards("Q? :: A", "", "a.md")).toEqual([]);
  });

  it("requires both question and answer", () => {
    expect(parseCards("Only? ::", "::", "a.md")).toEqual([]);
    expect(parseCards(":: only answer", "::", "a.md")).toEqual([]);
  });
});

describe("dedupeByQuestion", () => {
  it("keeps first occurrence", () => {
    const result = dedupeByQuestion([
      { question: "Q?", answer: "1", source_file: "a.md" },
      { question: "Q?", answer: "2", source_file: "b.md" },
      { question: "Other?", answer: "3", source_file: "a.md" },
    ]);
    expect(result).toEqual([
      { question: "Q?", answer: "1", source_file: "a.md" },
      { question: "Other?", answer: "3", source_file: "a.md" },
    ]);
  });
});
