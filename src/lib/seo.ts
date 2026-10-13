/**
 * SERP description builders for vrising-db.
 * Mirror of these functions lives in _desc_preview_vrising.mjs (offline rehearsal).
 */

const TYPO: [RegExp, string][] = [
  [/\bpurly\b/gi, "purely"],
  [/\bseperate\b/gi, "separate"],
  [/\boccured\b/gi, "occurred"],
];

/**
 * Repair holes left by stripping wiki icon markup, e.g.
 * "Your next primary attack inflicts and , dealing 50% magic damage".
 * Only removes/repairs; never invents stats.
 */
export const tidy = (s: string): string =>
  s
    .replace(/\binflicts\s+and\s*,\s*dealing\b/gi, "deals")
    .replace(/\binflicts\s+and\s+(?=conjures)/gi, "")
    .replace(/\binflicting\s+to\b/gi, "dealing damage to")
    .replace(/\btriggers\s+an?\s+dealing\b/gi, "deals")
    .replace(/\btriggers\s+an?\s+deal\b/gi, "deals")
    .replace(/\binflicting\s+and\s+granting\s+[^,.;]*\s+of\s*(?=[,.;])/gi, "")
    .replace(/\band\s+(?:inflicting|triggers|granting)\s*(?=[,.;])/gi, "")
    .replace(/\bdamage\s+after\s+(\d+\s*s)\s+and\s+spawning\b/gi, "damage after $1, spawning")
    .replace(/\b(and|or|with|of|to)\s+(?=[,.;])/gi, "")
    .replace(/\s+,\s*/g, ", ")
    .replace(/,\s*,+/g, ",")
    .replace(/,\s*([.;])/g, "$1")
    .replace(/\s+([,.;:])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();

/** Collapse whitespace, fix known wiki typos, repair icon holes, trim. */
export const clean = (s: unknown): string =>
  tidy(TYPO.reduce((a, [re, to]) => a.replace(re, to), String(s ?? "").replace(/\s+/g, " ").trim()));

/** Clean, but treat sentinel strings ("None"/"N/A"/"-") as empty. */
const SENTINEL = /^(none|null|n\/?a|undefined|-|—)$/i;
export const sane = (v: unknown): string => {
  const s = clean(v);
  return SENTINEL.test(s) ? "" : s;
};

/** Truncate to <= n chars on a word boundary, dropping trailing punctuation. */
export const cut = (s: string, n = 155): string => {
  const t = clean(s);
  if (t.length <= n) return t;
  const hard = t.slice(0, n);
  const sp = hard.lastIndexOf(" ");
  return (sp > n * 0.6 ? hard.slice(0, sp) : hard).replace(/[\s,;:.\-–—]+$/, "");
};

/** Leading sentence only (fallback when the full intro would be cut mid-thought). */
export const firstSentence = (s: unknown, n = 155): string => {
  const t = clean(s);
  const m = t.match(/^[^.!?]*[.!?]/);
  return cut(m ? m[0].trim() : t, n);
};

/**
 * Weapon. Stats first (gear level / physical power are 100% populated),
 * closed by a type tag — written as "V Rising Daggers stats" rather than
 * "a Daggers", which was the article bug on plural weapon types.
 */
export const weaponDesc = (w: any, n = 158): string => {
  const bits: string[] = [];
  const gl = sane(w?.gear_level);
  const pp = sane(w?.physical_power);
  const st = sane(w?.stats);
  if (gl) bits.push(`gear level ${gl}`);
  if (pp) bits.push(`${pp} physical power`);
  if (st) bits.push(st);
  const type = sane(w?.weapon_type);
  const tail = type ? `V Rising ${type} stats` : "V Rising weapon stats";
  if (bits.length) return cut(`${sane(w?.title)}: ${bits.join(", ")} — ${tail}.`, n);
  return cut(`${sane(w?.title)}: ${tail}. ${firstSentence(w?.intro, 90)}`, n);
};

/**
 * Armour. gear_level is populated on only 33% of rows and stats is the sentinel
 * "None" on 34, so a stat-only snippet reads "gear level None". Our intro carries
 * drop rates / vendors / availability, so lead with it and keep stats as a last resort.
 */
export const armorDesc = (a: any, n = 158): string => {
  const intro = clean(a?.intro);
  if (intro.length >= 40) return cut(intro, n);
  const bits: string[] = [];
  const gl = sane(a?.gear_level);
  const st = sane(a?.stats);
  const sb = sane(a?.set_bonus);
  if (gl) bits.push(`gear level ${gl}`);
  if (st) bits.push(st);
  if (sb) bits.push(`set bonus ${sb}`);
  const tail = bits.length ? `${bits.join(", ")} — V Rising armour stats.` : "in V Rising.";
  return cut(`${sane(a?.title)}: ${tail}`, n);
};

/**
 * Consumable. The effect text is the real content; the old lead
 * "X is a Consumable in V Rising." said nothing (item_type is "Consumable" 93%).
 */
export const consumableDesc = (c: any, n = 158): string => {
  const d = clean(c?.description);
  if (d.length >= 40) return cut(`${sane(c?.title)} — ${d}`, n);
  const t = sane(c?.item_type) || "consumable";
  return cut(`${sane(c?.title)} is a ${t} in V Rising.`, n);
};

/** V Blood boss (already stat-first and correct; kept for one-line call sites). */
export const vbloodDesc = (b: any, n = 158): string => {
  const lvl = sane(b?.level);
  const loc = sane(b?.location);
  const unlock = sane(b?.unlock);
  const head = `${sane(b?.title)} is a ${lvl ? `level ${lvl} ` : ""}V Blood carrier in V Rising`;
  const tail = `${loc ? ` found at ${loc}` : ""}.${unlock ? ` Defeating it unlocks ${unlock}.` : ""}`;
  return cut(`${head}${tail}`, n);
};
