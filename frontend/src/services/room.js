export class RoomSync extends EventTarget {
  constructor(room, user) {
    super();
    this.room = room;
    this.user = user;
    this.socket = null;
    this.state = null;
    this.reconnectTimer = null;
    this.closed = false;
  }

  connect() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const params = new URLSearchParams({ user_id: this.user.discord_id, username: this.user.username });
    if (this.user.avatar) params.set("avatar", this.user.avatar);
    this.socket = new WebSocket(`${protocol}://${location.host}/ws/room/${this.room.id}?${params}`);
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.event !== "REQUEST_CONTROL" && message.event !== "ERROR") this.state = message;
      this.dispatchEvent(new CustomEvent("message", { detail: message }));
    });
    this.socket.addEventListener("open", () => this.dispatchEvent(new Event("open")));
    this.socket.addEventListener("close", () => {
      this.dispatchEvent(new Event("close"));
      if (!this.closed) this.reconnectTimer = setTimeout(() => this.connect(), 1800);
    });
  }

  send(event, data = {}) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({ event, room_id: this.room.id, timestamp: Date.now(), ...data }));
    return true;
  }

  isHost() { return this.state?.host_user_id === this.user.discord_id; }
  canControl() { return this.isHost() || this.state?.controllers?.includes(this.user.discord_id); }
  close() { this.closed = true; clearTimeout(this.reconnectTimer); this.socket?.close(); }
}

