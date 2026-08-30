import { getJWPlayerConfig, loadJWPlayerLibrary } from "../config/jwplayer.js";
import { PlayerAdapter } from "./adapters.js";

export const jwMetrics = { loads: 0, success: 0, errors: 0, bufferEvents: 0, sourceFailures: 0, totalStartupTime: 0 };

export class JWPlayerAdapter extends PlayerAdapter {
  async initialize() {
    const started = performance.now(); jwMetrics.loads += 1;
    const jwplayer = await loadJWPlayerLibrary();
    this.host = document.createElement("div"); this.host.id = `jw-${crypto.randomUUID()}`; this.mount.append(this.host);
    this.player = jwplayer(this.host.id);
    const config = getJWPlayerConfig();
    const variants = (this.source.sources?.length ? this.source.sources : [this.source]).filter((item) => ["hls", "dash", "mp4", "webm"].includes(item.type));
    const playlist = [{
      title: this.source.title || "CraftPlay", image: this.source.poster || undefined,
      mediaid: this.source.media_id,
      sources: variants.map((item, index) => ({ file: item.url, type: item.type, label: item.quality || undefined, default: index === 0 ? "true" : "false" })),
      tracks: (this.source.subtitles || []).map((track) => ({ file: track.file || track.url, label: track.label, kind: "captions", default: Boolean(track.default) })),
    }];
    const ready = new Promise((resolve, reject) => {
      this.player.once("ready", resolve);
      this.player.once("setupError", (event) => reject(new Error(event?.message || "Falha ao preparar JW Player")));
    });
    this.player.on("play", () => { this.state = "playing"; this.emit("play"); });
    this.player.on("pause", () => { this.state = "paused"; this.emit("pause"); });
    this.player.on("complete", () => { this.state = "ended"; this.emit("ended"); });
    this.player.on("buffer", () => { this.state = "buffering"; jwMetrics.bufferEvents += 1; this.emit("buffer"); });
    this.player.on("firstFrame", () => { jwMetrics.success += 1; jwMetrics.totalStartupTime += performance.now() - started; this.emit("firstframe"); });
    this.player.on("error", () => { this.state = "error"; jwMetrics.errors += 1; jwMetrics.sourceFailures += 1; this.emit("error"); });
    this.player.on("autostartNotAllowed", () => this.emit("autoplayblocked"));
    this.player.setup({ ...config.setup, playlist });
    await ready; this.state = "paused";
  }
  play() { this.player.play(true); }
  pause() { this.player.pause(true); }
  seek(seconds) { this.player.seek(Math.max(0, Number(seconds) || 0)); }
  async getCurrentTime() { return Number(this.player.getPosition()) || 0; }
  async getDuration() { return Number(this.player.getDuration()) || 0; }
  async setVolume(value) { this.player.setVolume(Math.max(0, Math.min(1, value)) * 100); }
  async setMuted(value) { this.player.setMute(Boolean(value)); }
  async setPlaybackRate(value) { this.player.setPlaybackRate?.(Number(value)); }
  getBuffer() { return Number(this.player.getBuffer?.()) || 0; }
  getVersion() { return globalThis.jwplayer?.version || "unknown"; }
  destroy() { try { this.player?.remove(); } finally { this.player = null; super.destroy(); } }
}
