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
    const response = await fetch(target, { credentials: "same-origin", ...options, headers });
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
  sources(id, season = 0, episode = 0, excluded = []) { const params = new URLSearchParams({ season, episode }); excluded.forEach((provider) => params.append("exclude_provider", provider)); return this.request(`/api/media/${encodeURIComponent(id)}/sources?${params}`); }
  availability(id) { return this.request(`/api/media/${encodeURIComponent(id)}/availability`); }
  providerStatus() { return this.request("/api/playback/providers/status"); }
  debugProviders(payload, adminKey) { return this.request("/api/playback/debug", { method: "POST", headers: { "X-Admin-Key": adminKey }, body: JSON.stringify(payload) }); }
  testSources(adminKey) { return this.request("/api/playback/test-sources", { headers: { "X-Admin-Key": adminKey } }); }
  validateSource(payload, adminKey) { return this.request("/api/playback/validate-source", { method: "POST", headers: { "X-Admin-Key": adminKey }, body: JSON.stringify(payload) }); }
  customSources(adminKey) { return this.request("/api/admin/sources", { headers: { "X-Admin-Key": adminKey } }); }
  addCustomSource(payload, adminKey) { return this.request("/api/admin/sources", { method: "POST", headers: { "X-Admin-Key": adminKey }, body: JSON.stringify(payload) }); }
  toggleCustomSource(id, enabled, adminKey) { return this.request(`/api/admin/sources/${id}?enabled=${enabled}`, { method: "PATCH", headers: { "X-Admin-Key": adminKey } }); }
  deleteCustomSource(id, adminKey) { return this.request(`/api/admin/sources/${id}`, { method: "DELETE", headers: { "X-Admin-Key": adminKey } }); }
  history() { return this.request("/api/user/history"); }
  favorites() { return this.request("/api/user/favorites"); }
  addFavorite(media) { return this.request("/api/user/favorites", { method: "POST", body: JSON.stringify({ media_id: media.id, media_type: media.media_type }) }); }
  removeFavorite(id) { return this.request(`/api/user/favorites/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  saveProgress(payload) { return this.request("/api/playback/progress", { method: "POST", body: JSON.stringify(payload) }); }
  reportSourceFailure(payload) { return this.request("/api/playback/source-failure", { method: "POST", body: JSON.stringify(payload) }); }
  createRoom(instanceId) { return this.request("/api/rooms", { method: "POST", body: JSON.stringify({ discord_instance_id: instanceId }) }); }
  roomTicket(roomId) { return this.request(`/api/rooms/${encodeURIComponent(roomId)}/ticket`, { method: "POST" }); }
  discordAuth(code) { return this.request("/api/auth/discord", { method: "POST", body: JSON.stringify({ code }) }); }
  browserEntries(params = {}) { return this.request(`/api/browser/entries?${new URLSearchParams(params)}`); }
  browserEntry(id) { return this.request(`/api/browser/entries/${id}`); }
  browserStatus() { return this.request("/api/browser/status"); }
  browserCapabilities(roomId) { return this.request(`/api/browser/capabilities?room_id=${encodeURIComponent(roomId)}`); }
  browserSession(roomId) { return this.request(`/api/browser/session?room_id=${encodeURIComponent(roomId)}`); }
  startBrowserSession(payload) { return this.request("/api/browser/session/start", { method: "POST", body: JSON.stringify(payload) }); }
  navigateBrowser(payload) { return this.request("/api/browser/session/navigate", { method: "POST", body: JSON.stringify(payload) }); }
  closeBrowserSession(roomId) { return this.request("/api/browser/session/close", { method: "POST", body: JSON.stringify({ room_id: roomId }) }); }
  browserStreamToken(roomId) { return this.request(`/api/browser/session/token?room_id=${encodeURIComponent(roomId)}`); }
  browserFavorites() { return this.request("/api/browser/favorites"); }
  addBrowserFavorite(id) { return this.request(`/api/browser/favorites/${id}`, { method: "POST" }); }
  removeBrowserFavorite(id) { return this.request(`/api/browser/favorites/${id}`, { method: "DELETE" }); }
  dashboardOverview() { return this.request("/api/dashboard/browser/overview"); }
  dashboardEntries() { return this.request("/api/dashboard/browser/entries"); }
  dashboardRooms() { return this.request("/api/dashboard/browser/rooms"); }
  dashboardOpenNow(payload) { return this.request("/api/dashboard/browser/open-now", { method: "POST", body: JSON.stringify(payload) }); }
  dashboardCloseRoom(roomId) { return this.request(`/api/dashboard/browser/rooms/${encodeURIComponent(roomId)}/close`, { method: "POST" }); }
  dashboardRevokeControl(roomId) { return this.request(`/api/dashboard/browser/rooms/${encodeURIComponent(roomId)}/revoke-control`, { method: "POST" }); }
  dashboardRoomHome(roomId) { return this.request(`/api/dashboard/browser/rooms/${encodeURIComponent(roomId)}/home`, { method: "POST" }); }
  dashboardTmdbSearch(q) { return this.request(`/api/dashboard/browser/tmdb/search?q=${encodeURIComponent(q)}`); }
  dashboardBrowserSettings() { return this.request("/api/dashboard/browser/settings"); }
  updateDashboardBrowserSettings(payload) { return this.request("/api/dashboard/browser/settings", { method: "PATCH", body: JSON.stringify(payload) }); }
  createBrowserEntry(payload) { return this.request("/api/dashboard/browser/entries", { method: "POST", body: JSON.stringify(payload) }); }
  updateBrowserEntry(id, payload) { return this.request(`/api/dashboard/browser/entries/${id}`, { method: "PATCH", body: JSON.stringify(payload) }); }
  deleteBrowserEntry(id) { return this.request(`/api/dashboard/browser/entries/${id}`, { method: "DELETE" }); }
  duplicateBrowserEntry(id) { return this.request(`/api/dashboard/browser/entries/${id}/duplicate`, { method: "POST" }); }
  testBrowserLink(payload) { return this.request("/api/dashboard/browser/test", { method: "POST", body: JSON.stringify(payload) }); }
  debugBrowser(roomId) { return this.request(`/api/dashboard/browser/debug/${encodeURIComponent(roomId)}`); }
}
