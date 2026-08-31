export function normalizePointer(clientX, clientY, box) {
  return {
    x: Math.min(1, Math.max(0, (clientX - box.left) / box.width)),
    y: Math.min(1, Math.max(0, (clientY - box.top) / box.height)),
  };
}

export function shouldUseLiveKit(status) {
  return status?.livekit?.status === "healthy" && status?.sfu === "healthy" && status?.publisher === "healthy" && status?.webrtc === "healthy";
}

export class RemoteBrowserViewer extends EventTarget {
  constructor({ mount, roomSync, api, roomId, user, canControl = false }) {
    super();
    this.mount = mount;
    this.roomSync = roomSync;
    this.api = api;
    this.roomId = roomId;
    this.user = user;
    this.canControl = canControl;
    this.livekit = null;
    this.fallbackImage = null;
    this.frameObjectUrl = null;
    this.httpPollTimer = null;
    this.streamAbort = null;
    this.streamReconnectTimer = null;
    this.lastWebSocketFrameAt = 0;
    this.destroyed = false;
    this.lastMove = 0;
    this.lastScroll = 0;
    this.boundMessage = (event) => this.onRoomMessage(event.detail);
  }

  async connect() {
    this.roomSync.addEventListener("message", this.boundMessage);
    const status = await this.api.browserStatus().catch(() => null);
    if (shouldUseLiveKit(status)) {
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
        console.warn("LiveKit indisponível; mantendo screencast WebSocket.", error);
        this.setStatus("Conectando screencast do navegador...");
      }
    } else {
      this.setStatus("Conectando screencast do navegador...");
    }
    // Static pages may emit their only frame while the start API is returning.
    // Replay the buffered frame after the viewer has mounted.
    if (this.roomSync.lastBrowserFrame) {
      this.onRoomMessage(this.roomSync.lastBrowserFrame);
    } else {
      const requestFrame = () => this.roomSync.send("BROWSER_FRAME_REQUEST");
      if (!requestFrame()) this.roomSync.addEventListener("open", requestFrame, { once: true });
    }
    this.startHttpStream();
    this.startHttpFallback();
    this.bindInput();
  }

  ensureFallbackImage() {
    if (!this.fallbackImage) {
      this.fallbackImage = document.createElement("img");
      this.fallbackImage.className = "remote-frame";
      this.fallbackImage.alt = "Navegador remoto";
      this.mount.querySelector(".remote-media")?.append(this.fallbackImage);
    }
    return this.fallbackImage;
  }

  startHttpStream() {
    const connect = async () => {
      if (this.destroyed || !this.roomSync.ticket) return;
      this.streamAbort?.abort();
      this.streamAbort = new AbortController();
      try {
        await this.api.browserFrameStream(
          this.roomId,
          this.roomSync.ticket,
          this.streamAbort.signal,
          (frame) => this.onRoomMessage({ event: "BROWSER_FRAME", ...frame, transport: "http-stream" }),
        );
      } catch (error) {
        if (!this.destroyed && error.name !== "AbortError") this.setStatus("Reconectando transmissão...");
      }
      if (!this.destroyed) this.streamReconnectTimer = setTimeout(connect, 1000);
    };
    connect();
  }

  startHttpFallback() {
    const poll = async () => {
      if (this.destroyed) return;
      if (!this.lastWebSocketFrameAt || Date.now() - this.lastWebSocketFrameAt > 2000) {
        try {
          const blob = await this.api.browserFrame(this.roomId);
          const nextUrl = URL.createObjectURL(blob);
          const previousUrl = this.frameObjectUrl;
          this.frameObjectUrl = nextUrl;
          const image = this.ensureFallbackImage();
          image.onload = () => { if (previousUrl) URL.revokeObjectURL(previousUrl); };
          image.src = nextUrl;
          this.setStatus("Screencast conectado por HTTP · áudio requer publisher");
        } catch (error) {
          this.setStatus(error.message || "Captura do navegador indisponível");
        }
      }
      if (!this.destroyed) this.httpPollTimer = setTimeout(poll, 500);
    };
    poll();
  }

  bindInput() {
    const surface = this.mount.querySelector(".remote-surface");
    const normalized = (event) => {
      const box = surface.getBoundingClientRect();
      return normalizePointer(event.clientX, event.clientY, box);
    };
    surface.addEventListener("pointermove", (event) => {
      // Avoid high-frequency HTTP input on small hosts when WebSocket is down.
      if (!this.canInteract() || !this.websocketReady() || performance.now() - this.lastMove < 33) return;
      this.lastMove = performance.now();
      this.sendCommand("MOUSE_MOVE", normalized(event));
    });
    surface.addEventListener("click", (event) => {
      if (this.canInteract()) this.sendCommand("MOUSE_CLICK", { ...normalized(event), count: event.detail > 1 ? 2 : 1 });
    });
    surface.addEventListener("wheel", (event) => {
      if (!this.canInteract() || performance.now() - this.lastScroll < 100) return;
      this.lastScroll = performance.now();
      event.preventDefault();
      this.sendCommand("MOUSE_SCROLL", { delta_x: event.deltaX, delta_y: event.deltaY });
    }, { passive: false });
    surface.addEventListener("keydown", (event) => {
      if (!this.canInteract()) return;
      event.preventDefault();
      if (event.key.length === 1) this.sendCommand("TEXT_INPUT", { text: event.key });
      else { this.sendCommand("KEY_DOWN", { key: event.key }); this.sendCommand("KEY_UP", { key: event.key }); }
    });
  }

  websocketReady() {
    return this.roomSync.socket?.readyState === WebSocket.OPEN && Boolean(this.roomSync.state);
  }

  canInteract() {
    return this.canControl || this.roomSync.canControlBrowser();
  }

  sendCommand(event, data = {}) {
    if (this.websocketReady() && this.roomSync.send(event, data)) return;
    this.api.browserAction({ room_id: this.roomId, event, ...data }).then((session) => {
      const field = this.mount.querySelector("[data-browser-url]");
      if (field && session.current_url) field.value = session.current_url;
    }).catch((error) => this.setStatus(error.message));
  }

  async navigate(url) {
    try {
      const session = await this.api.navigateBrowser({ room_id: this.roomId, url });
      const field = this.mount.querySelector("[data-browser-url]");
      if (field) field.value = session.current_url;
    } catch (error) {
      this.setStatus(error.message);
    }
  }

  onRoomMessage(message) {
    if (message.event === "BROWSER_FRAME" && message.data) {
      this.lastWebSocketFrameAt = Date.now();
      this.ensureFallbackImage();
      if (this.frameObjectUrl) {
        URL.revokeObjectURL(this.frameObjectUrl);
        this.frameObjectUrl = null;
      }
      this.fallbackImage.src = `data:${message.mime || "image/jpeg"};base64,${message.data}`;
      this.setStatus(message.transport === "http-stream" ? "Transmissão HTTP até 30 FPS · áudio requer publisher" : "Screencast conectado · áudio requer publisher");
    }
    if (message.event === "BROWSER_ERROR") {
      this.setStatus(message.message || "Screencast do navegador indisponível");
    }
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
    this.destroyed = true;
    clearTimeout(this.httpPollTimer);
    clearTimeout(this.streamReconnectTimer);
    this.streamAbort?.abort();
    if (this.frameObjectUrl) URL.revokeObjectURL(this.frameObjectUrl);
    this.roomSync.removeEventListener("message", this.boundMessage);
    this.livekit?.disconnect();
    this.livekit = null;
    this.fallbackImage = null;
  }
}
