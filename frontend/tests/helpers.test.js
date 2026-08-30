import test from "node:test";
import assert from "node:assert/strict";
import { buildPlenoFluEpisodeUrl, buildPlenoFluMovieUrl, validateImdbId } from "../src/services/plenoflu.js";
import { adapterForSourceType } from "../src/player/controller.js";
import { configureJWPlayer } from "../src/config/jwplayer.js";
import { normalizePointer, shouldUseLiveKit } from "../src/browser/remote-viewer.js";
import { resolveDiscordClientId } from "../src/discord/activity.js";
import { RoomSync } from "../src/services/room.js";

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

test("JW Player assume mídia direta quando configurado, sem assumir embeds", () => {
  configureJWPlayer({ enabled: true, library_url: "https://cdn.jwplayer.com/libraries/ABCDEFGH.js" });
  for (const type of ["hls", "dash", "mp4", "webm"]) assert.equal(adapterForSourceType(type).name, "JWPlayerAdapter");
  assert.equal(adapterForSourceType("embed").name, "EmbedAdapter");
  assert.equal(adapterForSourceType("youtube").name, "YouTubeAdapter");
  configureJWPlayer({ enabled: false });
});

test("BrowserMode normaliza coordenadas e limita eventos fora da tela", () => {
  const box = { left: 100, top: 50, width: 1000, height: 500 };
  assert.deepEqual(normalizePointer(600, 300, box), { x: .5, y: .5 });
  assert.deepEqual(normalizePointer(-20, 900, box), { x: 0, y: 1 });
});

test("Discord Activity usa o Client ID do proxy como fonte autoritativa", () => {
  assert.equal(resolveDiscordClientId("config-id", "activity-id.discordsays.com"), "activity-id");
  assert.equal(resolveDiscordClientId("config-id", "craftplay.shardweb.app"), "config-id");
});

test("LiveKit só é usado quando SFU e publisher estão saudáveis", () => {
  assert.equal(shouldUseLiveKit({ livekit: { status: "healthy" }, sfu: "healthy", publisher: "unavailable", webrtc: "unavailable" }), false);
  assert.equal(shouldUseLiveKit({ livekit: { status: "healthy" }, sfu: "healthy", publisher: "healthy", webrtc: "healthy" }), true);
});

test("RoomSync guarda o frame antecipado sem apagar o estado da sala", () => {
  const sync = new RoomSync({ id: "room" }, { discord_id: "host" });
  sync.state = { event: "ROOM_JOIN", host_user_id: "host", controllers: [] };
  const frame = { event: "BROWSER_FRAME", mime: "image/jpeg", data: "abc" };
  sync.handleMessage(frame);
  assert.equal(sync.lastBrowserFrame, frame);
  assert.equal(sync.state.host_user_id, "host");
  assert.equal(sync.isHost(), true);
});
