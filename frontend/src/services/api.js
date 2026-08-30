export class ApiClient {
  constructor() {
    this.proxyPrefix = location.hostname.endsWith(".discordsays.com") ? "/.proxy" : "";
    this.token = sessionStorage.getItem("craftplay_token") || "";
    this.localUser = JSON.parse(localStorage.getItem("craftplay_local_user") || "null") || {
      discord_id: `local-${crypto.randomUUID()}`,
      username: "Visitante local",
      avatar: null,
    };
    localStorage.setItem("craftplay_local_user", JSON.stringify(this.localUser));
  }

  setSession(token, user) {
    this.token = token;
    this.localUser = user;
    sessionStorage.setItem("craftplay_token", token);
  }

  async request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    else {
      headers.set("X-Discord-User-Id", this.localUser.discord_id);
      headers.set("X-Discord-Username", this.localUser.username);
    }
    const target = path.startsWith("/") ? `${this.proxyPrefix}${path}` : path;
    const response = await fetch(target, { ...options, headers });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail || `Falha na API (${response.status})`);
    }
    return response.status === 204 ? null : response.json();
  }

  config() { return this.request("/api/config"); }
  home() { return this.request("/api/home"); }
  search(params) { return this.request(`/api/search?${new URLSearchParams(params)}`); }
  media(id) { return this.request(`/api/media/${encodeURIComponent(id)}`); }
  recommendations(id) { return this.request(`/api/media/${encodeURIComponent(id)}/recommendations`); }
  sources(id, season = 0, episode = 0) { return this.request(`/api/media/${encodeURIComponent(id)}/sources?season=${season}&episode=${episode}`); }
  history() { return this.request("/api/user/history"); }
  favorites() { return this.request("/api/user/favorites"); }
  addFavorite(media) { return this.request("/api/user/favorites", { method: "POST", body: JSON.stringify({ media_id: media.id, media_type: media.media_type }) }); }
  removeFavorite(id) { return this.request(`/api/user/favorites/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  saveProgress(payload) { return this.request("/api/playback/progress", { method: "POST", body: JSON.stringify(payload) }); }
  createRoom(instanceId) { return this.request("/api/rooms", { method: "POST", body: JSON.stringify({ discord_instance_id: instanceId }) }); }
  discordAuth(code) { return this.request("/api/auth/discord", { method: "POST", body: JSON.stringify({ code }) }); }
}
