import type { APIRoute } from "astro";
import vblood from "../data/vrising_vblood.json";
import weapons from "../data/vrising_weapons.json";
import armor from "../data/vrising_armor.json";
import consumables from "../data/vrising_consumables.json";

interface Entry {
  t: string;
  u: string;
  k: string;
  i?: string;
}

export const GET: APIRoute = () => {
  const tools: Entry[] = [
    { t: "V Blood boss order (by level)", u: "/rankings/#vblood", k: "Tool" },
    { t: "Weapon power rankings", u: "/rankings/#weapons", k: "Tool" },
    { t: "Armour gear rankings", u: "/rankings/#armor", k: "Tool" },
    { t: "Loot Finder", u: "/loot-finder/", k: "Tool" },
    { t: "All pages A–Z", u: "/search/", k: "Tool" },
  ];
  const items: Entry[] = [
    ...vblood.map((b: any) => ({ t: b.title, u: `/vblood/${b.slug}/`, k: "Boss", i: b.icon || "" })),
    ...weapons.map((w: any) => ({ t: w.title, u: `/weapons/${w.slug}/`, k: "Weapon", i: w.icon || "" })),
    ...armor.map((a: any) => ({ t: a.title, u: `/armor/${a.slug}/`, k: "Armour", i: a.icon || "" })),
    ...consumables.map((c: any) => ({ t: c.title, u: `/consumables/${c.slug}/`, k: "Consumable", i: c.icon || "" })),
  ];
  return new Response(JSON.stringify({ tools, items }), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
};
