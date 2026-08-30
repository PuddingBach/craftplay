import { PlenoFluPlayer } from "../services/plenoflu.js";

const formatTime = (seconds) => {
  if (!Number.isFinite(seconds)) return "00:00";
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return [hours || null, String(minutes).padStart(hours ? 2 : 1, "0"), String(secs).padStart(2, "0")].filter((part) => part !== null).join(":");
};
const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

export class CraftPlayer {
  constructor({ mount, media, sources, unavailable = [], roomSync, api, season = 0, episode = 0, onClose, onEpisode }) {
    Object.assign(this, { mount, media, sources, unavailable, roomSync, api, season, episode, onClose, onEpisode });
    this.sourceIndex = 0;
    this.source = sources[0] || null;
    this.video = null;
    this.hls = null;
    this.shaka = null;
    this.remoteUpdate = false;
    this.lastProgressSave = 0;
    this.render();
    this.bindRoom();
  }

  render() {
    this.cleanupSource();
    const playable = this.source && this.source.source_type !== "EMBED";
    this.mount.innerHTML = `
      <section class="player-layer" aria-label="Player de ${escapeHTML(this.media.title)}">
        <header class="player-top">
          <button class="icon-btn close-player" aria-label="Voltar">←</button>
          <div class="player-title"><strong>${escapeHTML(this.media.title)}</strong><small>${this.episode ? `T${this.season} · E${this.episode}` : "watch_party()"}</small></div>
          ${this.sources.length > 1 ? `<label class="mono">Servidor: <select class="player-select server-select">${this.sources.map((source, index) => `<option value="${index}" ${index === this.sourceIndex ? "selected" : ""}>${escapeHTML(source.provider_name === "PlenoFlu" ? "PlenoFlu" : index === 0 ? "Principal" : source.provider_name)}</option>`).join("")}</select></label>` : ""}
          <span class="host-pill">HOST: <b class="host-name">conectando</b></span>
          <div class="watchers" aria-label="Participantes"></div>
          <button class="btn btn-ghost request-control hidden">Solicitar controle</button>
        </header>
        <div class="player-stage">
          ${playable ? `<video playsinline preload="metadata" crossorigin="anonymous"></video>` : this.source?.source_type === "EMBED" ? `<iframe src="${this.source.embed_url}" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>` : `
            <div class="player-empty"><span class="brand-mark">!</span><h2>Nenhuma fonte disponível</h2><p>${escapeHTML(this.unavailable[0]?.message || "Este conteúdo está no catálogo, mas nenhuma fonte de reprodução está disponível no momento.")}</p></div>`}
          <span class="sync-status">● sincronizando sala</span>
          <div class="control-request hidden"></div>
          ${playable ? this.controlsTemplate() : ""}
        </div>
      </section>`;
    this.layer = this.mount.querySelector(".player-layer");
    this.video = this.mount.querySelector("video");
    this.mount.querySelector(".close-player").onclick = () => this.destroy();
    this.mount.querySelector(".request-control").onclick = () => this.roomSync.send("REQUEST_CONTROL");
    this.mount.querySelector(".server-select")?.addEventListener("change", (event) => this.switchSource(Number(event.target.value)));
    if (this.source?.provider_name === "PlenoFlu") {
      this.externalPlayer = new PlenoFluPlayer({
        container: this.mount.querySelector(".player-stage"),
        imdbId: this.media.external_ids.imdb,
        type: this.media.media_type === "movie" ? "movie" : "tv",
        season: this.season, episode: this.episode,
        onBack: () => this.switchSource(0),
      });
      this.externalPlayer.mount();
    }
    if (this.video) {
      this.attachSource();
      this.bindControls();
    }
  }

  switchSource(index) {
    if (!this.sources[index] || index === this.sourceIndex) return;
    this.sourceIndex = index;
    this.source = this.sources[index];
    this.render();
  }

  cleanupSource() {
    this.hls?.destroy(); this.hls = null;
    this.shaka?.destroy(); this.shaka = null;
    this.externalPlayer?.destroy(); this.externalPlayer = null;
  }

  controlsTemplate() {
    const episodes = this.media.seasons?.flatMap((season) => season.episodes.map((ep) => ({ ...ep, season: season.number }))) || [];
    return `<div class="player-controls visible">
      <input class="seek" type="range" min="0" max="100" value="0" step="0.1" aria-label="Progresso">
      <div class="control-row">
        <button class="control-btn play" aria-label="Reproduzir">▶</button>
        <button class="control-btn previous" aria-label="Episódio anterior" ${episodes.length ? "" : "disabled"}>⏮</button>
        <button class="control-btn next" aria-label="Próximo episódio" ${episodes.length ? "" : "disabled"}>⏭</button>
        <button class="control-btn mute" aria-label="Silenciar">🔊</button>
        <input class="volume" type="range" min="0" max="1" value="1" step="0.05" aria-label="Volume">
        <span class="timecode">00:00 / 00:00</span>
        <span class="control-spacer"></span>
        ${episodes.length ? `<select class="player-select episode-select" aria-label="Episódio">${episodes.map((ep) => `<option value="${ep.season}:${ep.number}" ${ep.season === this.season && ep.number === this.episode ? "selected" : ""}>T${ep.season} E${ep.number}</option>`).join("")}</select>` : ""}
        <select class="player-select subtitle-select" aria-label="Legenda"><option value="">Legendas</option>${(this.source.subtitles || []).map((track) => `<option value="${escapeHTML(track.language)}">${escapeHTML(track.label)}</option>`).join("")}</select>
        <select class="player-select audio-select" aria-label="Áudio"><option value="">Áudio</option>${(this.source.audio_tracks || []).map((track) => `<option value="${escapeHTML(track.language)}">${escapeHTML(track.label)}</option>`).join("")}</select>
        <select class="player-select speed-select" aria-label="Velocidade">${[.5,.75,1,1.25,1.5,2].map((rate) => `<option value="${rate}" ${rate === 1 ? "selected" : ""}>${rate}x</option>`).join("")}</select>
        <button class="control-btn fullscreen" aria-label="Tela cheia">⛶</button>
      </div>
    </div>`;
  }

  async attachSource() {
    const url = this.source.stream_url;
    try {
      if (this.source.source_type === "HLS") {
        const { default: Hls } = await import("hls.js");
        if (Hls.isSupported()) { this.hls = new Hls(); this.hls.loadSource(url); this.hls.attachMedia(this.video); }
        else if (this.video.canPlayType("application/vnd.apple.mpegurl")) this.video.src = url;
        else throw new Error("HLS não suportado neste dispositivo");
      } else if (this.source.source_type === "DASH") {
        const { default: shaka } = await import("shaka-player/dist/shaka-player.compiled.js");
        shaka.polyfill.installAll(); this.shaka = new shaka.Player(); await this.shaka.attach(this.video); await this.shaka.load(url);
      } else {
        this.video.src = url;
      }
    } catch (error) {
      this.showStatus("stream offline", true);
    }
  }

  bindControls() {
    const $ = (selector) => this.mount.querySelector(selector);
    const play = $(".play"), seek = $(".seek"), volume = $(".volume"), mute = $(".mute");
    play.onclick = () => this.control(this.video.paused ? "PLAYER_PLAY" : "PLAYER_PAUSE", () => this.video.paused ? this.video.play() : this.video.pause());
    this.video.addEventListener("play", () => { play.textContent = "❚❚"; if (!this.remoteUpdate) this.roomSync.send("PLAYER_PLAY", { position: this.video.currentTime }); });
    this.video.addEventListener("pause", () => { play.textContent = "▶"; if (!this.remoteUpdate) this.roomSync.send("PLAYER_PAUSE", { position: this.video.currentTime }); });
    this.video.addEventListener("timeupdate", () => {
      seek.max = this.video.duration || 100; seek.value = this.video.currentTime;
      $(".timecode").textContent = `${formatTime(this.video.currentTime)} / ${formatTime(this.video.duration)}`;
      if (Date.now() - this.lastProgressSave > 15000) { this.saveProgress(); this.lastProgressSave = Date.now(); }
    });
    seek.onchange = () => this.control("PLAYER_SEEK", () => { this.video.currentTime = Number(seek.value); }, { position: Number(seek.value) });
    volume.oninput = () => { this.video.volume = Number(volume.value); mute.textContent = this.video.volume ? "🔊" : "🔇"; };
    mute.onclick = () => { this.video.muted = !this.video.muted; mute.textContent = this.video.muted ? "🔇" : "🔊"; };
    $(".speed-select").onchange = (event) => this.control("PLAYER_SYNC", () => { this.video.playbackRate = Number(event.target.value); }, { position: this.video.currentTime, playback_rate: Number(event.target.value) });
    $(".subtitle-select").onchange = (event) => this.control("PLAYER_SYNC", () => {}, { position: this.video.currentTime, subtitle: event.target.value });
    $(".audio-select").onchange = (event) => this.control("PLAYER_SYNC", () => {}, { position: this.video.currentTime, audio_track: event.target.value });
    $(".fullscreen").onclick = () => this.layer.requestFullscreen?.();
    $(".episode-select")?.addEventListener("change", (event) => { const [season, episode] = event.target.value.split(":").map(Number); this.control("EPISODE_CHANGE", () => this.onEpisode?.(season, episode), { season, episode }); });
    $(".previous").onclick = () => this.moveEpisode(-1);
    $(".next").onclick = () => this.moveEpisode(1);
    this.syncTimer = setInterval(() => { if (this.roomSync.canControl() && !this.video.paused) this.roomSync.send("PLAYER_SYNC", { position: this.video.currentTime, playback_rate: this.video.playbackRate }); }, 5000);
  }

  moveEpisode(delta) {
    const select = this.mount.querySelector(".episode-select");
    if (!select) return;
    const index = Math.max(0, Math.min(select.options.length - 1, select.selectedIndex + delta));
    select.selectedIndex = index; select.dispatchEvent(new Event("change"));
  }

  control(event, action, extra = {}) {
    if (!this.roomSync.canControl()) { this.roomSync.send("REQUEST_CONTROL"); return; }
    action();
    if (!["PLAYER_PLAY", "PLAYER_PAUSE"].includes(event)) this.roomSync.send(event, { position: this.video?.currentTime || 0, ...extra });
  }

  bindRoom() {
    this.roomHandler = ({ detail }) => {
      if (detail.event === "REQUEST_CONTROL" && this.roomSync.isHost()) return this.showControlRequest(detail);
      if (detail.event === "ERROR") return this.showStatus(detail.message, true);
      this.updateParticipants(detail);
      const canControl = this.roomSync.canControl();
      this.mount.querySelector(".request-control").classList.toggle("hidden", canControl);
      if (!this.video || !detail.event?.startsWith("PLAYER_")) return;
      this.remoteUpdate = true;
      const drift = Math.abs(this.video.currentTime - Number(detail.position || 0));
      if (detail.event === "PLAYER_SEEK" || drift > 2.5) this.video.currentTime = Number(detail.position || 0);
      this.video.playbackRate = Number(detail.playback_rate || 1);
      if (detail.state === "playing" && this.video.paused) this.video.play().catch(() => this.showStatus("clique em reproduzir para liberar o áudio"));
      if (detail.state === "paused" && !this.video.paused) this.video.pause();
      queueMicrotask(() => { this.remoteUpdate = false; });
      this.showStatus(drift > 2.5 ? "● ressincronizado" : "● sala sincronizada");
    };
    this.roomSync.addEventListener("message", this.roomHandler);
  }

  updateParticipants(state) {
    const watchers = this.mount.querySelector(".watchers");
    watchers.innerHTML = (state.participants || []).slice(0, 6).map((user) => `<button class="watcher" data-user-id="${escapeHTML(user.discord_id)}" title="${escapeHTML(this.roomSync.isHost() && user.discord_id !== this.roomSync.user.discord_id ? `Transferir host para ${user.username}` : user.username)}">${user.avatar ? `<img class="avatar" src="${escapeHTML(user.avatar)}" alt="${escapeHTML(user.username)}">` : `<span class="avatar avatar-fallback">${escapeHTML(user.username?.[0] || "?")}</span>`}${user.discord_id === state.host_user_id ? `<i>host</i>` : ""}</button>`).join("");
    watchers.querySelectorAll(".watcher").forEach((button) => button.onclick = () => {
      if (this.roomSync.isHost() && button.dataset.userId !== this.roomSync.user.discord_id && confirm("Transferir o controle de host para este participante?")) {
        this.roomSync.send("HOST_CHANGE", { target_user_id: button.dataset.userId });
      }
    });
    const host = (state.participants || []).find((user) => user.discord_id === state.host_user_id);
    this.mount.querySelector(".host-name").textContent = host?.username || "ativo";
  }

  showControlRequest(request) {
    const panel = this.mount.querySelector(".control-request");
    panel.classList.remove("hidden");
    panel.innerHTML = `<p><b>${escapeHTML(request.username || "Participante")}</b> deseja controlar a reprodução.</p><div class="action-row"><button class="btn btn-primary allow">Permitir</button><button class="btn btn-ghost deny">Negar</button></div>`;
    panel.querySelector(".allow").onclick = () => { this.roomSync.send("GRANT_CONTROL", { target_user_id: request.user_id }); panel.classList.add("hidden"); };
    panel.querySelector(".deny").onclick = () => panel.classList.add("hidden");
  }

  showStatus(message, error = false) {
    const status = this.mount.querySelector(".sync-status");
    if (!status) return;
    status.textContent = message; status.style.color = error ? "var(--danger)" : "var(--green)";
  }

  saveProgress() {
    if (!this.video?.duration) return;
    this.api.saveProgress({ media_id: this.media.id, media_type: this.media.media_type, season: this.season, episode: this.episode, position: this.video.currentTime, duration: this.video.duration }).catch(() => {});
  }

  destroy() {
    this.saveProgress(); clearInterval(this.syncTimer); this.roomSync.removeEventListener("message", this.roomHandler);
    this.cleanupSource(); this.mount.innerHTML = ""; this.onClose?.();
  }
}
