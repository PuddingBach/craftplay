import { DashAdapter, HlsAdapter, NativeVideoAdapter, VimeoAdapter, YouTubeAdapter } from "./adapters.js";

const ADAPTERS = { mp4: NativeVideoAdapter, hls: HlsAdapter, dash: DashAdapter, youtube: YouTubeAdapter, vimeo: VimeoAdapter };

export class PlayerController extends EventTarget {
  constructor(mount) { super(); this.mount = mount; }
  async load(source) {
    await this.destroy();
    const Adapter = ADAPTERS[String(source?.type || "").toLowerCase()];
    if (!Adapter) throw new Error(`Engine ${source?.type || "desconhecida"} nao suportada`);
    this.adapter = new Adapter(this.mount, source);
    for (const event of ["play", "pause", "ended"]) this.adapter.addEventListener(event, () => this.dispatchEvent(new CustomEvent(event)));
    await this.adapter.initialize();
    return this;
  }
  play() { return this.adapter?.play(); }
  pause() { return this.adapter?.pause(); }
  seek(seconds) { return this.adapter?.seek(seconds); }
  getCurrentTime() { return this.adapter?.getCurrentTime() ?? Promise.resolve(0); }
  getDuration() { return this.adapter?.getDuration() ?? Promise.resolve(0); }
  setVolume(value) { return this.adapter?.setVolume(value); }
  setPlaybackRate(value) { return this.adapter?.setPlaybackRate(value); }
  getState() { return this.adapter?.getState() || "idle"; }
  async destroy() { if (this.adapter) await this.adapter.destroy(); this.adapter = null; if (this.mount) this.mount.innerHTML = ""; }
}
