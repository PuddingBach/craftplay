import { DashAdapter, EmbedAdapter, HlsAdapter, NativeVideoAdapter, VimeoAdapter, YouTubeAdapter } from "./adapters.js";
import { isJWPlayerEnabled } from "../config/jwplayer.js";
import { JWPlayerAdapter } from "./jwplayer-adapter.js";

const ADAPTERS = { mp4: NativeVideoAdapter, webm: NativeVideoAdapter, hls: HlsAdapter, dash: DashAdapter, embed: EmbedAdapter, youtube: YouTubeAdapter, vimeo: VimeoAdapter };

export function adapterForSourceType(sourceType) {
  const type = String(sourceType || "").toLowerCase();
  if (isJWPlayerEnabled() && ["mp4", "webm", "hls", "dash"].includes(type)) return JWPlayerAdapter;
  return ADAPTERS[type] || null;
}

export class PlayerController extends EventTarget {
  constructor(mount) { super(); this.mount = mount; }
  async load(source) {
    await this.destroy();
    const Adapter = adapterForSourceType(source?.type);
    if (!Adapter) throw new Error(`Engine ${source?.type || "desconhecida"} nao suportada`);
    this.adapter = new Adapter(this.mount, source);
    for (const event of ["play", "pause", "ended", "error", "buffer", "firstframe", "autoplayblocked"]) this.adapter.addEventListener(event, () => this.dispatchEvent(new CustomEvent(event)));
    try { await this.adapter.initialize(); }
    catch (error) {
      if (Adapter !== JWPlayerAdapter) throw error;
      await this.adapter.destroy();
      const Fallback = ADAPTERS[String(source.type).toLowerCase()];
      this.adapter = new Fallback(this.mount, source);
      for (const event of ["play", "pause", "ended", "error"]) this.adapter.addEventListener(event, () => this.dispatchEvent(new CustomEvent(event)));
      await this.adapter.initialize();
      this.lastFallback = error.message;
      this.dispatchEvent(new CustomEvent("enginefallback", { detail: { reason: error.message } }));
    }
    return this;
  }
  play() { return this.adapter?.play(); }
  pause() { return this.adapter?.pause(); }
  seek(seconds) { return this.adapter?.seek(seconds); }
  getCurrentTime() { return this.adapter?.getCurrentTime() ?? Promise.resolve(0); }
  getDuration() { return this.adapter?.getDuration() ?? Promise.resolve(0); }
  setVolume(value) { return this.adapter?.setVolume(value); }
  setMuted(value) { return this.adapter?.setMuted(value); }
  setPlaybackRate(value) { return this.adapter?.setPlaybackRate(value); }
  getState() { return this.adapter?.getState() || "idle"; }
  getEngine() { return this.adapter?.constructor?.name || "none"; }
  getBuffer() { return this.adapter?.getBuffer?.() || 0; }
  async destroy() { if (this.adapter) await this.adapter.destroy(); this.adapter = null; if (this.mount) this.mount.innerHTML = ""; }
}
