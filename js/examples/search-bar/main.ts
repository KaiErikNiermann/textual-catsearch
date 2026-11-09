/** The example page: a media catalogue searched through the bar. */

import { Schema, enumField, flagField, numberField, textField } from "../../src/index.ts";
import type { Query } from "../../src/index.ts";
import { SearchBar } from "./search-bar.ts";
import "./styles/index.css";

interface Title {
  readonly name: string;
  readonly kind: "movie" | "tv" | "game";
  readonly year: number;
  readonly genres: readonly string[];
  readonly cast: readonly string[];
  readonly watched: boolean;
  readonly favourite: boolean;
}

function title(
  name: string,
  kind: Title["kind"],
  year: number,
  genres: readonly string[],
  cast: readonly string[] = [],
  flags: { readonly watched?: boolean; readonly favourite?: boolean } = {},
): Title {
  return { name, kind, year, genres, cast, watched: flags.watched ?? false, favourite: flags.favourite ?? false };
}

const TITLES: readonly Title[] = [
  title("Dune", "movie", 2021, ["sci-fi", "drama"], ["Timothée Chalamet", "Zendaya"], { watched: true }),
  title("Dune: Part Two", "movie", 2024, ["sci-fi", "drama"], ["Timothée Chalamet", "Zendaya", "Austin Butler"]),
  title("Arrival", "movie", 2016, ["sci-fi", "drama"], ["Amy Adams", "Jeremy Renner"], { watched: true, favourite: true }),
  title("Blade Runner 2049", "movie", 2017, ["sci-fi", "thriller"], ["Ryan Gosling", "Harrison Ford"], { watched: true }),
  title("Spirited Away", "movie", 2001, ["animation", "fantasy"], [], { watched: true, favourite: true }),
  title("Perfect Days", "movie", 2023, ["drama"], ["Kōji Yakusho"]),
  title("Past Lives", "movie", 2023, ["drama", "romance"], ["Greta Lee", "Teo Yoo"], { watched: true }),
  title("Amélie", "movie", 2001, ["comedy", "romance"], ["Audrey Tautou"], { watched: true }),
  title("Parasite", "movie", 2019, ["thriller", "drama"], ["Song Kang-ho"], { watched: true, favourite: true }),
  title("Everything Everywhere All at Once", "movie", 2022, ["sci-fi", "comedy"], ["Michelle Yeoh", "Ke Huy Quan"]),
  title("Severance", "tv", 2022, ["sci-fi", "thriller"], ["Adam Scott", "Britt Lower"], { watched: true, favourite: true }),
  title("Reacher", "tv", 2022, ["action", "crime"], ["Alan Ritchson"]),
  title("Andor", "tv", 2022, ["sci-fi", "drama"], ["Diego Luna"], { watched: true }),
  title("The Bear", "tv", 2022, ["comedy", "drama"], ["Jeremy Allen White", "Ayo Edebiri"]),
  title("Shōgun", "tv", 2024, ["drama", "history"], ["Hiroyuki Sanada", "Anna Sawai"], { watched: true }),
  title("Dark", "tv", 2017, ["sci-fi", "mystery"], ["Louis Hofmann"]),
  title("Fleabag", "tv", 2016, ["comedy", "drama"], ["Phoebe Waller-Bridge"], { watched: true, favourite: true }),
  title("Hades", "game", 2020, ["roguelike", "action"], [], { watched: true }),
  title("Outer Wilds", "game", 2019, ["sci-fi", "mystery"], [], { favourite: true }),
  title("Disco Elysium", "game", 2019, ["rpg", "mystery"], []),
  title("Celeste", "game", 2018, ["platformer"], [], { watched: true }),
  title("Elden Ring", "game", 2022, ["rpg", "action"], []),
];

const SCHEMA = new Schema<Title>(
  [
    textField({ name: "title", get: (t) => t.name, complete: false }),
    enumField({ name: "kind", get: (t) => t.kind, choices: ["movie", "tv", "game"], normalize: (v) => (v === "film" ? "movie" : v) }),
    numberField({ name: "year", get: (t) => t.year }),
    textField({ name: "genre", get: (t) => t.genres, aliases: ["tag"] }),
    textField({ name: "cast", get: (t) => t.cast, aliases: ["actor"] }),
    flagField({ name: "is", flags: { watched: (t) => t.watched, favourite: (t) => t.favourite } }),
  ],
  { bare: "title" },
);

function element(id: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`#${id}`);
  if (found === null) throw new Error(`no #${id} in the page`);
  return found;
}

const results = element("results");
const count = element("count");
const notice = element("notice");

function show(query: Query<Title>): void {
  const kept = query.filter(TITLES);
  count.textContent = `${kept.length} of ${TITLES.length}`;
  notice.textContent = query.notice;
  notice.hidden = query.notice === "";
  results.replaceChildren(
    ...kept.map((t) => {
      const row = document.createElement("li");
      row.className = "result";
      const name = document.createElement("span");
      name.className = "result-name";
      name.textContent = t.name;
      const meta = document.createElement("span");
      meta.className = "result-meta";
      meta.textContent = [t.kind, String(t.year), ...t.genres].join(" · ");
      row.append(name, meta);
      return row;
    }),
  );
}

const bar = new SearchBar({
  editor: element("query"),
  listbox: element("suggestions"),
  schema: SCHEMA,
  vocabulary: SCHEMA.vocabulary(TITLES),
  onQuery: show,
});

for (const button of document.querySelectorAll<HTMLButtonElement>("[data-example]")) {
  button.addEventListener("click", () => {
    bar.set(button.dataset["example"] ?? "");
    element("query").focus();
  });
}
