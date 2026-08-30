export class PlayerAdapter extends EventTarget {
  constructor(mount, source) { super(); this.mount = mount; this.source = source; this.state = "idle"; }
  async initialize() {}
  async play() {}
  pause() {}
  seek() {}
  async getCurrentTime() { return 0; }
  async getDuration() { return 0; }
  async setVolume() {}
  async setPlaybackRate() {}
  getState() { return this.state; }
  destroy() { this.mount.innerHTML = ""; }
  emit(name) { this.dispatchEvent(new CustomEvent(name)); }
}

export class NativeVideoAdapter extends PlayerAdapter {
  async initialize() {
    this.video = document.createElement("video");
    Object.assign(this.video, { playsInline: true, preload: "metadata", crossOrigin: "anonymous" });
    this.mount.append(this.video);
    this.video.src = this.source.url;
    this.video.addEventListener("play", () => { this.state = "playing"; this.emit("play"); });
    this.video.addEventListener("pause", () => { this.state = "paused"; this.emit("pause"); });
    this.video.addEventListener("ended", () => { this.state = "ended"; this.emit("ended"); });
  }
  play() { return this.video.play(); }
  pause() { this.video.pause(); }
  seek(seconds) { this.video.currentTime = Math.max(0, Number(seconds) || 0); }
  async getCurrentTime() { return this.video.currentTime || 0; }
  async getDuration() { return Number.isFinite(this.video.duration) ? this.video.duration : 0; }
  async setVolume(value) { this.video.volume = Math.max(0, Math.min(1, value)); }
  async setPlaybackRate(value) { this.video.playbackRate = value; }
  destroy() { this.video?.pause(); this.video?.removeAttribute("src"); this.video?.load(); super.destroy(); }
}

export class HlsAdapter extends NativeVideoAdapter {
  async initialize() {
    await super.initialize();
    this.video.removeAttribute("src");
    const { default: Hls } = await import("hls.js");
    if (Hls.isSupported()) { this.engine = new Hls(); this.engine.loadSource(this.source.url); this.engine.attachMedia(this.video); }
    else if (this.video.canPlayType("application/vnd.apple.mpegurl")) this.video.src = this.source.url;
    else throw new Error("HLS nao suportado neste dispositivo");
  }
  destroy() { this.engine?.destroy(); super.destroy(); }
}

export class DashAdapter extends NativeVideoAdapter {
  async initialize() {
    await super.initialize();
    this.video.removeAttribute("src");
    const { default: shaka } = await import("shaka-player/dist/shaka-player.compiled.js");
    shaka.polyfill.installAll();
    if (!shaka.Player.isBrowserSupported()) throw new Error("DASH nao suportado neste dispositivo");
    this.engine = new shaka.Player();
    await this.engine.attach(this.video);
    await this.engine.load(this.source.url);
  }
  destroy() { this.engine?.destroy(); super.destroy(); }
}

let youtubeReady;
function loadYouTubeAPI() {
  if (globalThis.YT?.Player) return Promise.resolve(globalThis.YT);
  if (!youtubeReady) youtubeReady = new Promise((resolve, reject) => {
    const previous = globalThis.onYouTubeIframeAPIReady;
    globalThis.onYouTubeIframeAPIReady = () => { previous?.(); resolve(globalThis.YT); };
    const script = document.createElement("script"); script.src = "https://www.youtube.com/iframe_api";
    script.onerror = () => reject(new Error("YouTube Player API indisponivel")); document.head.append(script);
  });
  return youtubeReady;
}

export class YouTubeAdapter extends PlayerAdapter {
  async initialize() {
    const YT = await loadYouTubeAPI();
    const host = document.createElement("div"); this.mount.append(host);
    const videoId = this.source.metadata?.video_id || new URL(this.source.url).pathname.split("/").pop();
    await new Promise((resolve, reject) => {
      this.player = new YT.Player(host, { videoId, playerVars: { enablejsapi: 1, playsinline: 1, origin: location.origin },
        events: { onReady: resolve, onError: (event) => reject(new Error(`YouTube erro ${event.data}`)), onStateChange: (event) => {
          if (event.data === YT.PlayerState.PLAYING) { this.state = "playing"; this.emit("play"); }
          if (event.data === YT.PlayerState.PAUSED) { this.state = "paused"; this.emit("pause"); }
          if (event.data === YT.PlayerState.ENDED) { this.state = "ended"; this.emit("ended"); }
        } } });
    });
  }
  play() { this.player.playVideo(); }
  pause() { this.player.pauseVideo(); }
  seek(seconds) { this.player.seekTo(Number(seconds) || 0, true); }
  async getCurrentTime() { return this.player.getCurrentTime() || 0; }
  async getDuration() { return this.player.getDuration() || 0; }
  async setVolume(value) { this.player.setVolume(Math.max(0, Math.min(1, value)) * 100); }
  async setPlaybackRate(value) { this.player.setPlaybackRate(value); }
  destroy() { this.player?.destroy(); super.destroy(); }
}

export class VimeoAdapter extends PlayerAdapter {
  async initialize() {
    const { default: VimeoPlayer } = await import("@vimeo/player");
    const iframe = document.createElement("iframe"); iframe.src = this.source.url; iframe.allow = "autoplay; fullscreen; picture-in-picture"; iframe.allowFullscreen = true;
    this.mount.append(iframe); this.player = new VimeoPlayer(iframe); await this.player.ready();
    this.player.on("play", () => { this.state = "playing"; this.emit("play"); });
    this.player.on("pause", () => { this.state = "paused"; this.emit("pause"); });
    this.player.on("ended", () => { this.state = "ended"; this.emit("ended"); });
  }
  play() { return this.player.play(); }
  pause() { return this.player.pause(); }
  seek(seconds) { return this.player.setCurrentTime(Number(seconds) || 0); }
  getCurrentTime() { return this.player.getCurrentTime(); }
  getDuration() { return this.player.getDuration(); }
  setVolume(value) { return this.player.setVolume(Math.max(0, Math.min(1, value))); }
  setPlaybackRate(value) { return this.player.setPlaybackRate(value).catch(() => {}); }
  async destroy() { await this.player?.destroy(); this.mount.innerHTML = ""; }
}
