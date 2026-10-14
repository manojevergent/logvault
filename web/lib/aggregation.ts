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
