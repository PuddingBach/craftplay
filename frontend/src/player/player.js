import { PlayerController } from "./controller.js";

const formatTime = (seconds) => {
  if (!Number.isFinite(seconds)) return "00:00";
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), secs = total % 60;
  return [hours || null, String(minutes).padStart(hours ? 2 : 1, "0"), String(secs).padStart(2, "0")].filter((part) => part !== null).join(":");
};
const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const controlledTypes = new Set(["mp4", "hls", "dash", "youtube", "vimeo"]);

export class CraftPlayer {
  constructor(options) {
    Object.assign(this, options);
    this.sources = this.sources || [];
    this.sourceIndex = 0; this.source = this.sources[0] || null; this.remoteUpdate = false; this.lastProgressSave = 0;
    this.render(); this.bindRoom();
  }

  controlsTemplate() {
    const episodes = this.media.seasons?.flatMap((season) => season.episodes.map((episode) => ({ ...episode, season: season.number }))) || [];
    return `<div class="player-controls visible"><input class="seek" type="range" min="0" max="100" value="0" step="0.1" aria-label="Progresso"><div class="control-row">
      <button class="control-btn play" aria-label="Reproduzir">▶</button><button class="control-btn previous" ${episodes.length ? "" : "disabled"}>⏮</button><button class="control-btn next" ${episodes.length ? "" : "disabled"}>⏭</button>
      <button class="control-btn mute" aria-label="Silenciar">🔊</button><input class="volume" type="range" min="0" max="1" value="1" step="0.05"><span class="timecode">00:00 / 00:00</span><span class="control-spacer"></span>
      ${episodes.length ? `<select class="player-select episode-select">${episodes.map((ep) => `<option value="${ep.season}:${ep.number}" ${ep.season === this.season && ep.number === this.episode ? "selected" : ""}>T${ep.season} E${ep.number}</option>`).join("")}</select>` : ""}
      <select class="player-select subtitle-select"><option value="">Legendas</option>${(this.source.subtitles || []).map((track) => `<option value="${escapeHTML(track.language)}">${escapeHTML(track.label)}</option>`).join("")}</select>
      <select class="player-select audio-select"><option value="">Áudio</option>${(this.source.audio_tracks || []).map((track) => `<option value="${escapeHTML(track.language)}">${escapeHTML(track.label)}</option>`).join("")}</select>
      <select class="player-select speed-select">${[.5,.75,1,1.25,1.5,2].map((rate) => `<option value="${rate}" ${rate === 1 ? "selected" : ""}>${rate}x</option>`).join("")}</select><button class="control-btn fullscreen">⛶</button>
    </div></div>`;
  }

  async render() {
    await this.controller?.destroy(); clearInterval(this.uiTimer); clearInterval(this.syncTimer);
    const playable = this.source?.is_playable && controlledTypes.has(this.source.type);
    this.mount.innerHTML = `<section class="player-layer" aria-label="Player de ${escapeHTML(this.media.title)}"><header class="player-top">
      <button class="icon-btn close-player">←</button><div class="player-title"><strong>${escapeHTML(this.media.title)}</strong><small>${this.episode ? `T${this.season} · E${this.episode}` : "watch_party()"}</small></div>
      ${this.sources.length > 1 ? `<label class="mono">Fonte: <select class="player-select server-select">${this.sources.map((source, index) => `<option value="${index}" ${index === this.sourceIndex ? "selected" : ""}>${escapeHTML(source.provider)} · ${escapeHTML(source.quality)}</option>`).join("")}</select></label>` : ""}
      <span class="host-pill">HOST: <b class="host-name">conectando</b></span><div class="watchers"></div><button class="btn btn-ghost request-control hidden">Solicitar controle</button>
      </header><div class="player-stage"><div class="engine-mount">${!this.source ? `<div class="player-empty"><span class="brand-mark">!</span><h2>Nenhuma fonte disponível</h2><p>${escapeHTML(this.unavailable[0]?.message || "Este título está disponível no catálogo, mas nenhuma fonte compatível foi encontrada.")}</p></div>` : this.source.type === "embed" ? `<iframe src="${escapeHTML(this.source.url)}" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>` : ""}</div>
      <span class="sync-status">● preparando player</span><div class="control-request hidden"></div>${playable ? this.controlsTemplate() : ""}</div></section>`;
    this.layer = this.mount.querySelector(".player-layer");
    this.mount.querySelector(".close-player").onclick = () => this.destroy();
    this.mount.querySelector(".request-control").onclick = () => this.roomSync.send("REQUEST_CONTROL");
    this.mount.querySelector(".server-select")?.addEventListener("change", (event) => this.switchSource(Number(event.target.value)));
    if (!playable) { this.showStatus(this.source ? "fonte externa sem sincronização" : "nenhuma fonte encontrada", !this.source); return; }
    try {
      this.controller = new PlayerController(this.mount.querySelector(".engine-mount"));
      await this.controller.load(this.source); this.bindControls(); this.showStatus("● player pronto");
    } catch (error) { this.showStatus(`fonte indisponível: ${error.message}`, true); }
  }

  switchSource(index) { if (this.sources[index] && index !== this.sourceIndex) { this.sourceIndex = index; this.source = this.sources[index]; this.render(); } }

  bindControls() {
    const $ = (selector) => this.mount.querySelector(selector), play = $(".play"), seek = $(".seek"), volume = $(".volume"), mute = $(".mute");
    play.onclick = () => this.control(this.controller.getState() === "playing" ? "PLAYER_PAUSE" : "PLAYER_PLAY", () => this.controller.getState() === "playing" ? this.controller.pause() : this.controller.play());
    this.controller.addEventListener("play", async () => { play.textContent = "❚❚"; if (!this.remoteUpdate) this.roomSync.send("PLAYER_PLAY", { position: await this.controller.getCurrentTime() }); });
    this.controller.addEventListener("pause", async () => { play.textContent = "▶"; if (!this.remoteUpdate) this.roomSync.send("PLAYER_PAUSE", { position: await this.controller.getCurrentTime() }); });
    seek.onchange = () => this.control("PLAYER_SEEK", () => this.controller.seek(Number(seek.value)), { position: Number(seek.value) });
    volume.oninput = () => { this.controller.setVolume(Number(volume.value)); mute.textContent = Number(volume.value) ? "🔊" : "🔇"; };
    mute.onclick = () => { const next = Number(volume.value) ? 0 : 1; volume.value = next; this.controller.setVolume(next); mute.textContent = next ? "🔊" : "🔇"; };
    $(".speed-select").onchange = async (event) => this.control("PLAYER_SYNC", () => this.controller.setPlaybackRate(Number(event.target.value)), { position: await this.controller.getCurrentTime(), playback_rate: Number(event.target.value) });
    $(".subtitle-select").onchange = async (event) => this.control("PLAYER_SYNC", () => {}, { position: await this.controller.getCurrentTime(), subtitle: event.target.value });
    $(".audio-select").onchange = async (event) => this.control("PLAYER_SYNC", () => {}, { position: await this.controller.getCurrentTime(), audio_track: event.target.value });
    $(".fullscreen").onclick = () => this.layer.requestFullscreen?.();
    $(".episode-select")?.addEventListener("change", (event) => { const [season, episode] = event.target.value.split(":").map(Number); this.control("EPISODE_CHANGE", () => this.onEpisode?.(season, episode), { season, episode }); });
    $(".previous").onclick = () => this.moveEpisode(-1); $(".next").onclick = () => this.moveEpisode(1);
    this.uiTimer = setInterval(async () => { const position = await this.controller?.getCurrentTime() || 0, duration = await this.controller?.getDuration() || 0; seek.max = duration || 100; seek.value = position; $(".timecode").textContent = `${formatTime(position)} / ${formatTime(duration)}`; if (Date.now() - this.lastProgressSave > 15000) { this.saveProgress(); this.lastProgressSave = Date.now(); } }, 500);
    this.syncTimer = setInterval(async () => { if (this.roomSync.canControl() && this.controller?.getState() === "playing") this.roomSync.send("PLAYER_SYNC", { position: await this.controller.getCurrentTime(), playback_rate: Number($(".speed-select").value) }); }, 5000);
  }

  moveEpisode(delta) { const select = this.mount.querySelector(".episode-select"); if (!select) return; select.selectedIndex = Math.max(0, Math.min(select.options.length - 1, select.selectedIndex + delta)); select.dispatchEvent(new Event("change")); }
  async control(event, action, extra = {}) { if (!this.roomSync.canControl()) return this.roomSync.send("REQUEST_CONTROL"); await action(); if (!["PLAYER_PLAY", "PLAYER_PAUSE"].includes(event)) this.roomSync.send(event, { position: await this.controller?.getCurrentTime() || 0, ...extra }); }

  bindRoom() {
    this.roomHandler = async ({ detail }) => {
      if (detail.event === "REQUEST_CONTROL" && this.roomSync.isHost()) return this.showControlRequest(detail);
      if (detail.event === "ERROR") return this.showStatus(detail.message, true);
      this.updateParticipants(detail); const canControl = this.roomSync.canControl(); this.mount.querySelector(".request-control")?.classList.toggle("hidden", canControl);
      if (!this.controller || !detail.event?.startsWith("PLAYER_")) return;
      this.remoteUpdate = true; const current = await this.controller.getCurrentTime(), target = Number(detail.position || 0), drift = Math.abs(current - target);
      if (detail.event === "PLAYER_SEEK" || drift > 2.5) await this.controller.seek(target);
      await this.controller.setPlaybackRate(Number(detail.playback_rate || 1));
      if (detail.state === "playing" && this.controller.getState() !== "playing") await this.controller.play().catch(() => this.showStatus("clique em reproduzir para liberar o áudio"));
      if (detail.state === "paused" && this.controller.getState() === "playing") await this.controller.pause();
      queueMicrotask(() => { this.remoteUpdate = false; }); this.showStatus(drift > 2.5 ? "● ressincronizado" : "● sala sincronizada");
    };
    this.roomSync.addEventListener("message", this.roomHandler);
  }

  updateParticipants(state) {
    const watchers = this.mount.querySelector(".watchers"); if (!watchers) return;
    watchers.innerHTML = (state.participants || []).slice(0, 6).map((user) => `<button class="watcher" data-user-id="${escapeHTML(user.discord_id)}" title="${escapeHTML(user.username)}">${user.avatar ? `<img class="avatar" src="${escapeHTML(user.avatar)}" alt="${escapeHTML(user.username)}">` : `<span class="avatar avatar-fallback">${escapeHTML(user.username?.[0] || "?")}</span>`}${user.discord_id === state.host_user_id ? `<i>host</i>` : ""}</button>`).join("");
    watchers.querySelectorAll(".watcher").forEach((button) => button.onclick = () => { if (this.roomSync.isHost() && button.dataset.userId !== this.roomSync.user.discord_id && confirm("Transferir o controle de host para este participante?")) this.roomSync.send("HOST_CHANGE", { target_user_id: button.dataset.userId }); });
    const host = (state.participants || []).find((user) => user.discord_id === state.host_user_id); const label = this.mount.querySelector(".host-name"); if (label) label.textContent = host?.username || "ativo";
  }
  showControlRequest(request) { const panel = this.mount.querySelector(".control-request"); panel.classList.remove("hidden"); panel.innerHTML = `<p><b>${escapeHTML(request.username || "Participante")}</b> deseja controlar a reprodução.</p><div class="action-row"><button class="btn btn-primary allow">Permitir</button><button class="btn btn-ghost deny">Negar</button></div>`; panel.querySelector(".allow").onclick = () => { this.roomSync.send("GRANT_CONTROL", { target_user_id: request.user_id }); panel.classList.add("hidden"); }; panel.querySelector(".deny").onclick = () => panel.classList.add("hidden"); }
  showStatus(message, error = false) { const status = this.mount.querySelector(".sync-status"); if (status) { status.textContent = message; status.style.color = error ? "var(--danger)" : "var(--green)"; } }
  async saveProgress() { const duration = await this.controller?.getDuration() || 0; if (!duration) return; this.api.saveProgress({ media_id: this.media.id, media_type: this.media.media_type, season: this.season, episode: this.episode, position: await this.controller.getCurrentTime(), duration }).catch(() => {}); }
  async destroy() { await this.saveProgress(); clearInterval(this.uiTimer); clearInterval(this.syncTimer); this.roomSync.removeEventListener("message", this.roomHandler); await this.controller?.destroy(); this.mount.innerHTML = ""; this.onClose?.(); }
}
