export interface ParsedCard {
  question: string;
  answer: string;
  source_file: string;
}

/**
 * Extract Q&A cards from markdown text.
 * A card is valid only if the question part contains '?'.
 * Cards are separated by one or more blank lines.
 */
export function parseCards(content: string, delimiter: string, sourceFile: string): ParsedCard[] {
  if (!delimiter) {
    return [];
  }

  const blocks = content.split(/\n\s*\n+/);
  const cards: ParsedCard[] = [];

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) {
      continue;
    }

    const idx = trimmed.indexOf(delimiter);
    if (idx === -1) {
      continue;
    }

    const question = trimmed.slice(0, idx).trim();
    const answer = trimmed.slice(idx + delimiter.length).trim();

    if (!question || !answer) {
      continue;
    }
    if (!question.includes("?")) {
      continue;
    }

    cards.push({
      question,
      answer,
      source_file: sourceFile,
    });
  }

  return cards;
}

export function dedupeByQuestion(cards: ParsedCard[]): ParsedCard[] {
  const seen = new Set<string>();
  const result: ParsedCard[] = [];
  for (const card of cards) {
    if (seen.has(card.question)) {
      continue;
    }
    seen.add(card.question);
    result.push(card);
  }
  return result;
}
