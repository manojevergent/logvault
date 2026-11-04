// Shared between the New Extraction wizard and the Saved Searches edit form —
// both let you pick which parsed fields land in the output file.

/** Named groups a regex defines, in the order they appear — drives the
 *  "which fields land in the output" checklist straight from the pattern
 *  itself, so the list shows up as soon as a group is typed, not only after
 *  a sample line happens to match it. */
export function extractGroupNames(regex: string): string[] {
  const names: string[] = [];
  const re = /\(\?<([a-zA-Z_][a-zA-Z0-9_]*)>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(regex))) {
    if (!names.includes(m[1])) names.push(m[1]);
  }
  return names;
}

/** Split the phrases box into loose words and quoted exact phrases.
 *
 *  Last9's `$contains` is word-based: as words, "API : 502" is satisfied by a
 *  stray "502" anywhere in the line — including a millisecond field in the log's
 *  JSON — which silently returns 200s when you asked for 502s. A quoted phrase
 *  is sent as a regex instead, where the tokens must be adjacent.
 *
 *      getStatusCode for "API : 502"   ->  ["getStatusCode", "for"] + ["API : 502"]
 */
export function parsePhraseInput(raw: string): { words: string[]; exact: string[] } {
  const words: string[] = [];
  const exact: string[] = [];
  for (const token of raw.match(/"[^"]*"|[^\s"]+/g) ?? []) {
    if (token.startsWith('"')) {
      const inner = token.slice(1, -1).trim();
      if (inner) exact.push(inner);
    } else {
      words.push(token);
    }
  }
  return { words, exact };
}

/** Escaped literals joined by `\s+` — mirrors worker/app/last9/pipeline.py. */
export function exactPhraseRegex(phrase: string): string {
  const esc = (s: string) => s.replace(/([.^$*+?()[\]{}|\\])/g, "\\$1");
  return phrase
    .split(/\s+/)
    .filter(Boolean)
    .map(esc)
    .join("\\s+");
}
