import test from "node:test";
import assert from "node:assert/strict";
import { buildPlenoFluEpisodeUrl, buildPlenoFluMovieUrl, validateImdbId } from "../src/services/plenoflu.js";
import { adapterForSourceType } from "../src/player/controller.js";

test("URLSearchParams codifica filtros de busca", () => {
  const params = new URLSearchParams({ q: "ficção científica", rating: "8" });
  assert.equal(params.get("q"), "ficção científica");
  assert.match(params.toString(), /fic%C3%A7%C3%A3o/);
});

test("progresso é limitado para apresentação", () => {
  const progress = Math.min(100, (150 / 100) * 100);
  assert.equal(progress, 100);
});

test("PlenoFlu aceita somente IMDb IDs e índices válidos", () => {
  assert.equal(validateImdbId("tt1234567"), true);
  assert.equal(validateImdbId("https://evil.example"), false);
  assert.equal(buildPlenoFluMovieUrl("tt1234567"), "https://plenoflu.com/movie/tt1234567");
  assert.equal(buildPlenoFluEpisodeUrl("tt1234567", 1, 3), "https://plenoflu.com/tvshow/tt1234567/1/3");
  assert.throws(() => buildPlenoFluEpisodeUrl("tt1234567", 0, 3));
});

test("PlayerController seleciona adapters HLS, DASH, WEBM e embed", () => {
  for (const type of ["hls", "dash", "mp4", "webm", "embed", "youtube", "vimeo"]) {
    assert.equal(typeof adapterForSourceType(type), "function");
  }
  assert.equal(adapterForSourceType("unknown"), null);
});
