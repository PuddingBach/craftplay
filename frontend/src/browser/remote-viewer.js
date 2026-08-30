export function normalizePointer(clientX, clientY, box) {
  return {
    x: Math.min(1, Math.max(0, (clientX - box.left) / box.width)),
    y: Math.min(1, Math.max(0, (clientY - box.top) / box.height)),
  };
}

export class RemoteBrowserViewer extends EventTarget {
  constructor({ mount, roomSync, api, roomId, user }) {
    super();
    this.mount = mount;
    this.roomSync = roomSync;
    this.api = api;
    this.roomId = roomId;
    this.user = user;
    this.livekit = null;
    this.lastMove = 0;
    this.boundMessage = (event) => this.onRoomMessage(event.detail);
  }

  async connect() {
    this.roomSync.addEventListener("message", this.boundMessage);
    try {
      const { Room, RoomEvent, Track } = await import("livekit-client");
      const credentials = await this.api.browserStreamToken(this.roomId);
      this.livekit = new Room({ adaptiveStream: true, dynacast: true });
      this.livekit.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Video || track.kind === Track.Kind.Audio) {
          const element = track.attach();
          element.autoplay = true;
          if (track.kind === Track.Kind.Video) element.className = "remote-video";
          this.mount.querySelector(".remote-media").append(element);
          this.mount.querySelector(".stream-state").textContent = "Transmissão conectada";
        }
      });
      this.livekit.on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((element) => element.remove()));
      this.livekit.on(RoomEvent.Disconnected, () => this.setStatus("Transmissão desconectada"));
      await this.livekit.connect(credentials.url, credentials.token, { autoSubscribe: true });
      this.setStatus("Aguardando transmissão do navegador...");
    } catch (error) {
      this.setStatus(error.message || "WebRTC indisponível");
    }
    this.bindInput();
  }

  bindInput() {
    const surface = this.mount.querySelector(".remote-surface");
    const normalized = (event) => {
      const box = surface.getBoundingClientRect();
      return normalizePointer(event.clientX, event.clientY, box);
    };
    surface.addEventListener("pointermove", (event) => {
      if (!this.roomSync.canControlBrowser() || performance.now() - this.lastMove < 33) return;
      this.lastMove = performance.now();
      this.roomSync.send("MOUSE_MOVE", normalized(event));
    });
    surface.addEventListener("click", (event) => {
      if (this.roomSync.canControlBrowser()) this.roomSync.send("MOUSE_CLICK", { ...normalized(event), count: event.detail > 1 ? 2 : 1 });
    });
    surface.addEventListener("wheel", (event) => {
      if (!this.roomSync.canControlBrowser()) return;
      event.preventDefault();
      this.roomSync.send("MOUSE_SCROLL", { delta_x: event.deltaX, delta_y: event.deltaY });
    }, { passive: false });
    surface.addEventListener("keydown", (event) => {
      if (!this.roomSync.canControlBrowser()) return;
      event.preventDefault();
      if (event.key.length === 1) this.roomSync.send("TEXT_INPUT", { text: event.key });
      else { this.roomSync.send("KEY_DOWN", { key: event.key }); this.roomSync.send("KEY_UP", { key: event.key }); }
    });
  }

  onRoomMessage(message) {
    if (message.current_url) {
      const field = this.mount.querySelector("[data-browser-url]");
      if (field) field.value = message.current_url;
    }
    if (["PRIVACY_ON", "PRIVACY_OFF", "ROOM_JOIN", "HOST_CHANGE"].includes(message.event)) {
      const privacy = message.privacy_mode ?? message.browser?.privacy_mode;
      const isHost = this.roomSync.isHost();
      this.mount.querySelector(".privacy-curtain")?.classList.toggle("hidden", !privacy || isHost);
      if (!isHost) this.mount.querySelectorAll(".remote-media video,.remote-media audio").forEach((element) => {
        element.muted = Boolean(privacy);
        element.style.visibility = privacy ? "hidden" : "visible";
      });
    }
    if (message.event === "MOUSE_MOVE") this.showCursor(message);
    this.dispatchEvent(new CustomEvent("message", { detail: message }));
  }

  showCursor(message) {
    const cursor = this.mount.querySelector(".remote-cursor");
    if (!cursor || message.x == null || message.y == null) return;
    const name = this.roomSync.state?.participants?.find((item) => item.discord_id === message.user_id)?.username || "Controller";
    cursor.style.left = `${message.x * 100}%`;
    cursor.style.top = `${message.y * 100}%`;
    cursor.textContent = name;
  }

  setStatus(message) {
    const status = this.mount.querySelector(".stream-state");
    if (status) status.textContent = message;
  }

  destroy() {
    this.roomSync.removeEventListener("message", this.boundMessage);
    this.livekit?.disconnect();
    this.livekit = null;
  }
}
