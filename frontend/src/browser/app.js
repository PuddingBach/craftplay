import { RoomSync } from "../services/room.js";
import { RemoteBrowserViewer } from "./remote-viewer.js";

const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const fallback = "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="360"><rect width="100%" height="100%" fill="#12182a"/><text x="50%" y="50%" text-anchor="middle" fill="#7289da" font-size="70">CP</text></svg>`);

export async function initBrowserMode({ app, api, discord }) {
  if (location.pathname === "/dashboard") return initDashboard(app, api);
  if (location.pathname === "/debug/browser") return initBrowserDebug(app, api);
  const activity = await discord.initialize();
  let home;
  try {
    home = await api.home();
  } catch (error) {
    if (!activity.embedded && error.status === 401) {
      const next = `${location.pathname}${location.search}`;
      location.assign(`/auth/discord/user/login?next=${encodeURIComponent(next)}`);
      return;
    }
    throw error;
  }
  const user = home.user || activity.user;
  const room = await api.createRoom(activity.instanceId);
  const capabilities = await api.browserCapabilities(room.id);
  const { ticket } = await api.roomTicket(room.id);
  const roomSync = new RoomSync(room, user, ticket);
  roomSync.connect();
  const state = { activity, user, room, roomSync, capabilities, entries: [], favorites: new Set(), viewer: null, query: "" };
  await loadEntries(api, state);
  renderBrowserHome(app, api, state);
}

async function loadEntries(api, state) {
  const [entries, favorites] = await Promise.all([api.browserEntries(state.query ? { q: state.query } : {}), api.browserFavorites().catch(() => [])]);
  state.entries = entries;
  state.favorites = new Set(favorites.map((item) => item.id));
}

function renderBrowserHome(app, api, state) {
  const groups = [
    ["Destaques", state.entries.filter((item) => item.featured)],
    ["Filmes", state.entries.filter((item) => item.category === "filmes" || item.entry_type === "movie")],
    ["Séries", state.entries.filter((item) => item.category === "series" || item.entry_type === "series")],
    ["Animes", state.entries.filter((item) => item.category === "animes" || item.entry_type === "anime")],
    ["Desenhos", state.entries.filter((item) => item.category === "desenhos" || item.entry_type === "cartoon")],
    ["Sites", state.entries.filter((item) => item.entry_type === "website")],
    ["Favoritos", state.entries.filter((item) => state.favorites.has(item.id))],
  ].filter(([, items]) => items.length);
  app.innerHTML = `<main class="browser-home">
    <header class="browser-home-header"><button class="logo browser-logo"><span class="logo-ring">CP</span><span class="logo-name">craft<em>play</em></span></button><div class="browser-search"><input type="search" placeholder="Pesquisar sites e conteúdos" value="${escapeHTML(state.query)}"><button class="btn btn-primary" data-search>Pesquisar</button></div><a class="btn btn-ghost" href="/invite" target="_blank" rel="noopener">Adicionar bot</a><a class="btn btn-ghost" href="/dashboard">Dashboard</a></header>
    <section class="browser-hero"><span class="eyebrow">NAVEGADOR COMPARTILHADO</span><h1>Uma tela. Uma sessão.<br>Todo mundo junto.</h1><p>Abra sites no Chromium remoto e compartilhe a navegação com sua sala do Discord.</p>${state.capabilities.can_open_manual_url ? `<form class="quick-launch"><input type="url" required placeholder="https://..." aria-label="Abrir endereço"><button class="btn btn-primary">Abrir endereço</button></form>` : `<p class="control-notice">Solicite o controle ao host para escolher o próximo conteúdo.</p>`}</section>
    <div class="browser-sections">${groups.length ? groups.map(([label, items]) => `<section><div class="row-header"><h2>${label}</h2><span>${items.length} itens</span></div><div class="entry-grid">${items.map((item) => entryCard(item, state.favorites.has(item.id))).join("")}</div></section>`).join("") : `<div class="empty-state"><h2>Nenhuma entrada publicada</h2><p>Use o Dashboard para adicionar sites e conteúdos.</p></div>`}</div>
    <footer class="mode-switch">BrowserMode ativo · <a href="/?mode=direct">abrir DirectPlaybackMode</a></footer>
  </main><div id="browser-toast" class="toast-region"></div>`;
  app.querySelector("[data-search]").onclick = async () => { state.query = app.querySelector(".browser-search input").value.trim(); await loadEntries(api, state); renderBrowserHome(app, api, state); };
  app.querySelector(".quick-launch")?.addEventListener("submit", async (event) => { event.preventDefault(); await openBrowser(app, api, state, { url: event.currentTarget.querySelector("input").value }); });
  app.querySelectorAll("[data-open-entry]").forEach((button) => button.onclick = async () => {
    const entry = state.entries.find((item) => item.id === Number(button.dataset.openEntry));
    if (entry.open_mode === "external") return window.open(entry.url, "_blank", "noopener");
    if (entry.open_mode === "direct") return location.assign(`/?mode=direct&entry=${entry.id}`);
    if (!state.capabilities.can_navigate) return alert("Solicite controle ao host para abrir este conteúdo.");
    await openBrowser(app, api, state, { entry_id: entry.id });
  });
  app.querySelectorAll("[data-favorite-entry]").forEach((button) => button.onclick = async (event) => {
    event.stopPropagation(); const id = Number(button.dataset.favoriteEntry);
    if (state.favorites.has(id)) { await api.removeBrowserFavorite(id); state.favorites.delete(id); }
    else { await api.addBrowserFavorite(id); state.favorites.add(id); }
    renderBrowserHome(app, api, state);
  });
  app.querySelectorAll(".entry-card img").forEach((image) => image.addEventListener("error", () => { image.src = fallback; }, { once: true }));
}

function entryCard(item, favorite) {
  return `<article class="entry-card"><button data-open-entry="${item.id}"><img src="${escapeHTML(item.poster_url || item.banner_url || item.icon_url || fallback)}" alt=""><span class="entry-copy"><b>${escapeHTML(item.name)}</b><small>${escapeHTML(item.category)} · ${escapeHTML(item.shield_mode)}</small><p>${escapeHTML(item.description || new URL(item.url).hostname)}</p></span></button><button class="entry-favorite" data-favorite-entry="${item.id}" aria-label="Favoritar">${favorite ? "★" : "☆"}</button></article>`;
}

async function openBrowser(app, api, state, target) {
  renderLoading(app, "Preparando navegador...");
  try {
    setLoading(app, "Iniciando sessão...");
    const session = await api.startBrowserSession({ room_id: state.room.id, ...target });
    setLoading(app, "Conectando transmissão...");
    renderBrowserView(app, api, state, session);
    state.viewer = new RemoteBrowserViewer({ mount: app, roomSync: state.roomSync, api, roomId: state.room.id, user: state.user, canControl: state.capabilities.can_navigate });
    await state.viewer.connect();
  } catch (error) {
    renderFriendlyError(app, error.message, () => renderBrowserHome(app, api, state));
  }
}

function renderLoading(app, message) {
  app.innerHTML = `<div class="browser-loading"><div class="browser-spinner"></div><h2 data-loading>${escapeHTML(message)}</h2><ol><li>Preparando navegador</li><li>Iniciando sessão</li><li>Conectando transmissão</li><li>Abrindo site</li></ol></div>`;
}
function setLoading(app, message) { const node = app.querySelector("[data-loading]"); if (node) node.textContent = message; }
function renderFriendlyError(app, message, back) {
  app.innerHTML = `<div class="browser-loading"><span class="brand-mark">!</span><h2>Não foi possível abrir este site.</h2><p>${escapeHTML(message || "O navegador remoto ficou indisponível.")}</p><button class="btn btn-primary">Voltar à Home</button></div>`;
  app.querySelector("button").onclick = back;
}

function renderBrowserView(app, api, state, session) {
  const host = session.host_user_id === state.user.discord_id;
  app.innerHTML = `<main class="browser-view"><header class="browser-toolbar"><button class="tool" data-command="BACK">←</button><button class="tool" data-command="FORWARD">→</button><button class="tool" data-command="RELOAD">⟳</button><button class="tool" data-command="HOME">⌂</button><form class="address-bar"><span>🔒</span><input data-browser-url value="${escapeHTML(session.current_url)}" ${host ? "" : "readonly"}><button>Ir</button></form><span class="shield-pill">🛡 ${escapeHTML(session.shield_mode)}</span><span class="people-pill">👥 ${session.participants}/${session.max_participants}</span><span class="host-pill">♛ ${host ? "Host" : "Sala"}</span></header>
    <section class="remote-surface" tabindex="0"><div class="remote-media"></div><div class="stream-state">Abrindo site...</div><div class="remote-cursor">Controller</div><div class="privacy-curtain hidden"><span>🔒</span><h2>O host está realizando uma ação privada.</h2></div></section>
    <footer class="browser-controls"><button class="btn btn-ghost" data-home>🏠 CraftPlay</button>${host ? `<button class="btn btn-ghost" data-privacy>🔒 Modo privado</button><button class="btn btn-ghost" data-lock>Bloquear sessão</button><button class="btn btn-danger" data-close>Encerrar sessão</button>` : `<button class="btn btn-primary" data-control>Solicitar controle</button>`}<span class="control-status">${host ? "Você controla o navegador" : "Modo: " + session.control_mode}</span><div class="control-queue"></div></footer>
  </main>`;
  app.querySelectorAll("[data-command]").forEach((button) => button.onclick = () => state.viewer?.sendCommand(button.dataset.command));
  app.querySelector(".address-bar").onsubmit = (event) => { event.preventDefault(); if (host || state.roomSync.canControlBrowser()) state.viewer?.navigate(event.currentTarget.querySelector("input").value); };
  app.querySelector("[data-home]").onclick = () => { state.viewer?.destroy(); renderBrowserHome(app, api, state); };
  app.querySelector("[data-control]")?.addEventListener("click", () => state.roomSync.send("CONTROL_REQUEST"));
  app.querySelector("[data-privacy]")?.addEventListener("click", (event) => { const enabled = event.currentTarget.dataset.enabled !== "true"; event.currentTarget.dataset.enabled = String(enabled); state.roomSync.send(enabled ? "PRIVACY_ON" : "PRIVACY_OFF"); });
  app.querySelector("[data-lock]")?.addEventListener("click", (event) => { const locked = event.currentTarget.dataset.locked !== "true"; event.currentTarget.dataset.locked = String(locked); state.roomSync.send("SESSION_LOCK", { locked }); });
  app.querySelector("[data-close]")?.addEventListener("click", async () => { if (confirm("Encerrar o navegador desta sala?")) { await api.closeBrowserSession(state.room.id); state.viewer?.destroy(); renderBrowserHome(app, api, state); } });
  state.roomSync.addEventListener("message", (event) => renderControlQueue(app, state, event.detail));
}

function renderControlQueue(app, state, message) {
  const queue = message.control_queue || message.browser?.control_queue;
  if (!queue || !state.roomSync.isHost()) return;
  const target = app.querySelector(".control-queue");
  if (!target) return;
  target.innerHTML = queue.map((item) => `<span>${escapeHTML(item.username)} <button data-grant="${escapeHTML(item.user_id)}">Aceitar</button></span>`).join("");
  target.querySelectorAll("[data-grant]").forEach((button) => button.onclick = () => state.roomSync.send("CONTROL_GRANTED", { target_user_id: button.dataset.grant }));
}

async function initDashboard(app, api, allowClaim = true) {
  try {
    // Validate the administrative cookie first, avoiding four simultaneous
    // forbidden requests when the regular Activity token is still active.
    const overview = await api.dashboardOverview();
    const [entries, rooms, browserSettings] = await Promise.all([api.dashboardEntries(), api.dashboardRooms(), api.dashboardBrowserSettings()]);
    app.innerHTML = `<main class="dashboard"><header><div><span class="eyebrow">CRAFTPLAY ADMIN</span><h1>Dashboard do navegador</h1></div><a class="btn btn-ghost" href="/">Abrir Activity</a></header>
      <section class="dashboard-stats"><article><b>${overview.entries}</b><span>Entradas</span></article><article><b>${overview.active_rooms}</b><span>Salas ativas</span></article><article><b>${overview.browser.active_sessions}</b><span>Chromiums</span></article><article><b>${overview.connected_users}</b><span>Conectados</span></article><article><b>${overview.webrtc}</b><span>WebRTC</span></article></section>
      <section class="dashboard-panel"><h2>Buscar metadados no TMDB</h2><form class="tmdb-search"><input required placeholder="Nome do filme ou série"><button class="btn btn-ghost">Buscar</button></form><div class="tmdb-results"></div></section>
      <section class="dashboard-panel"><h2>Links e conteúdo</h2><form class="entry-form"><input name="entry_id" type="hidden"><input name="name" required placeholder="Nome"><input name="url" type="url" required placeholder="https://..."><select name="entry_type"><option>website</option><option>movie</option><option>series</option><option>anime</option><option>cartoon</option><option>custom</option></select><input name="category" value="sites" placeholder="Categoria"><input name="poster_url" type="url" placeholder="Poster"><input name="banner_url" type="url" placeholder="Banner"><input name="icon_url" type="url" placeholder="Ícone"><textarea name="description" placeholder="Descrição"></textarea><select name="shield_mode"><option>STANDARD</option><option>STRICT</option><option>OFF</option></select><select name="open_mode"><option value="browser">Abrir no navegador</option><option value="direct">Player direto</option><option value="external">Externo</option></select><select name="trust_level"><option value="unknown">Trust: desconhecido</option><option value="official">Oficial</option><option value="custom">Customizado</option></select><input name="sort_order" type="number" value="0" placeholder="Ordem"><input name="expires_at" type="datetime-local" title="Expiração"><label><input name="featured" type="checkbox"> Destaque</label><label><input name="pinned" type="checkbox"> Fixado</label><label><input name="enabled" type="checkbox" checked> Ativo</label><button class="btn btn-primary"><span data-submit-label>Publicar</span></button><button type="button" class="btn btn-ghost" data-test>Testar link</button><button type="button" class="btn btn-ghost hidden" data-cancel-edit>Cancelar edição</button><div class="entry-preview"><img src="${fallback}" alt="Preview"><div><b>Preview do card</b><small>sites · STANDARD</small><p>Descrição</p></div></div></form><pre class="test-result hidden"></pre>
      <div class="dashboard-table">${entries.map((entry) => `<article><div><b>${escapeHTML(entry.name)}</b><small>${escapeHTML(entry.entry_type)} · ${escapeHTML(entry.category)} · ${escapeHTML(entry.shield_mode)}</small><span>${escapeHTML(entry.url)}</span></div><button data-edit="${entry.id}">Editar</button><button data-duplicate="${entry.id}">Duplicar</button><button data-toggle="${entry.id}" data-enabled="${entry.enabled}">${entry.enabled ? "Desativar" : "Ativar"}</button><button data-delete="${entry.id}">Excluir</button></article>`).join("")}</div></section>
      <section class="dashboard-panel"><h2>Abrir agora</h2>${rooms.length ? `<form class="open-now"><input name="url" type="url" required placeholder="https://..."><select name="room_id">${rooms.map((room) => `<option value="${escapeHTML(room.room_id)}">${escapeHTML(room.room_id)} · ${room.participants}/${room.max_participants}</option>`).join("")}</select><button class="btn btn-primary">Abrir na sala</button><button type="button" class="btn btn-ghost" data-save-home>Salvar na Home</button></form>` : `<p>Inicie uma sala na Activity para usar esta ferramenta.</p>`}</section>
      <section class="dashboard-panel"><h2>Configurações do Browser</h2><form class="browser-settings"><select name="control_mode"><option ${browserSettings.control_mode === "HOST_ONLY" ? "selected" : ""}>HOST_ONLY</option><option ${browserSettings.control_mode === "REQUEST_CONTROL" ? "selected" : ""}>REQUEST_CONTROL</option><option ${browserSettings.control_mode === "SHARED" ? "selected" : ""}>SHARED</option></select><select name="shield_mode"><option ${browserSettings.shield_mode === "OFF" ? "selected" : ""}>OFF</option><option ${browserSettings.shield_mode === "STANDARD" ? "selected" : ""}>STANDARD</option><option ${browserSettings.shield_mode === "STRICT" ? "selected" : ""}>STRICT</option></select><input name="idle_timeout" type="number" min="60" value="${browserSettings.idle_timeout}"><input name="max_participants" type="number" min="1" max="50" value="${browserSettings.max_participants}"><input name="homepage" value="${escapeHTML(browserSettings.homepage)}"><label><input name="manual_url" type="checkbox" ${browserSettings.manual_url ? "checked" : ""}> URL manual</label><label><input name="privacy_on_password" type="checkbox"> Sugerir privacidade em senhas</label><button class="btn btn-primary">Salvar configurações</button></form></section>
      <section class="dashboard-panel"><h2>Salas</h2>${rooms.length ? rooms.map((room) => `<article class="room-row"><div><b>${escapeHTML(room.room_id)}</b><small>${room.participants}/${room.max_participants} · ${escapeHTML(room.browser_status)}</small><span>${escapeHTML(room.current_url)}</span></div><button data-room-home="${escapeHTML(room.room_id)}">Home</button><button data-room-revoke="${escapeHTML(room.room_id)}">Revogar controle</button><button data-room-close="${escapeHTML(room.room_id)}">Encerrar</button></article>`).join("") : "<p>Nenhuma sala ativa.</p>"}</section></main>`;
    const form = app.querySelector(".entry-form");
    app.querySelector(".tmdb-search").onsubmit = async (event) => { event.preventDefault(); const result = await api.dashboardTmdbSearch(event.currentTarget.querySelector("input").value); const target = app.querySelector(".tmdb-results"); target.innerHTML = result.items.slice(0,8).map((item, index) => `<button data-tmdb-result="${index}"><img src="${escapeHTML(item.poster || fallback)}" alt=""><span><b>${escapeHTML(item.title)}</b><small>${item.year || "—"} · ${escapeHTML(item.media_type)}</small></span></button>`).join("") || "Nenhum resultado."; target.querySelectorAll("[data-tmdb-result]").forEach((button) => button.onclick = () => { const item = result.items[Number(button.dataset.tmdbResult)]; form.name.value = item.title; form.entry_type.value = item.media_type === "movie" ? "movie" : "series"; form.category.value = item.media_type === "movie" ? "filmes" : "series"; form.poster_url.value = item.poster || ""; form.banner_url.value = item.backdrop || ""; form.description.value = item.overview || ""; updatePreview(); form.scrollIntoView({ behavior: "smooth" }); }); };
    const payloadFromForm = () => { const data = Object.fromEntries(new FormData(form)); delete data.entry_id; for (const field of ["poster_url", "banner_url", "icon_url", "expires_at"]) if (!data[field]) data[field] = null; data.sort_order = Number(data.sort_order || 0); data.featured = form.featured.checked; data.pinned = form.pinned.checked; data.enabled = form.enabled.checked; return data; };
    const updatePreview = () => { const preview = form.querySelector(".entry-preview"); preview.querySelector("img").src = form.poster_url.value || form.banner_url.value || form.icon_url.value || fallback; preview.querySelector("b").textContent = form.name.value || "Preview do card"; preview.querySelector("small").textContent = `${form.category.value || "sites"} · ${form.shield_mode.value}`; preview.querySelector("p").textContent = form.description.value || "Descrição"; };
    form.addEventListener("input", updatePreview);
    form.onsubmit = async (event) => { event.preventDefault(); const data = payloadFromForm(); if (form.entry_id.value) await api.updateBrowserEntry(form.entry_id.value, data); else await api.createBrowserEntry(data); location.reload(); };
    app.querySelector("[data-test]").onclick = async () => { const result = await api.testBrowserLink({ url: form.url.value, shield_mode: form.shield_mode.value }); const pre = app.querySelector(".test-result"); pre.textContent = JSON.stringify(result, null, 2); pre.classList.remove("hidden"); };
    app.querySelectorAll("[data-duplicate]").forEach((button) => button.onclick = async () => { await api.duplicateBrowserEntry(button.dataset.duplicate); location.reload(); });
    app.querySelectorAll("[data-edit]").forEach((button) => button.onclick = () => { const entry = entries.find((item) => item.id === Number(button.dataset.edit)); for (const field of ["name", "url", "entry_type", "category", "poster_url", "banner_url", "icon_url", "description", "shield_mode", "open_mode", "trust_level", "sort_order"]) if (form[field]) form[field].value = entry[field] ?? ""; form.entry_id.value = entry.id; form.featured.checked = entry.featured; form.pinned.checked = entry.pinned; form.enabled.checked = entry.enabled; form.expires_at.value = entry.expires_at ? entry.expires_at.slice(0,16) : ""; form.querySelector("[data-submit-label]").textContent = "Salvar alterações"; form.querySelector("[data-cancel-edit]").classList.remove("hidden"); updatePreview(); form.scrollIntoView({ behavior: "smooth" }); });
    form.querySelector("[data-cancel-edit]").onclick = () => { form.reset(); form.entry_id.value = ""; form.category.value = "sites"; form.enabled.checked = true; form.querySelector("[data-submit-label]").textContent = "Publicar"; form.querySelector("[data-cancel-edit]").classList.add("hidden"); updatePreview(); };
    app.querySelectorAll("[data-toggle]").forEach((button) => button.onclick = async () => { await api.updateBrowserEntry(button.dataset.toggle, { enabled: button.dataset.enabled !== "true" }); location.reload(); });
    app.querySelectorAll("[data-delete]").forEach((button) => button.onclick = async () => { if (confirm("Excluir esta entrada?")) { await api.deleteBrowserEntry(button.dataset.delete); location.reload(); } });
    app.querySelector(".open-now")?.addEventListener("submit", async (event) => { event.preventDefault(); await api.dashboardOpenNow(Object.fromEntries(new FormData(event.currentTarget))); alert("URL enviada para a sala."); });
    app.querySelector(".browser-settings").onsubmit = async (event) => { event.preventDefault(); const settingsForm = event.currentTarget; await api.updateDashboardBrowserSettings({ control_mode: settingsForm.control_mode.value, shield_mode: settingsForm.shield_mode.value, idle_timeout: Number(settingsForm.idle_timeout.value), max_participants: Number(settingsForm.max_participants.value), homepage: settingsForm.homepage.value, manual_url: settingsForm.manual_url.checked, privacy_on_password: settingsForm.privacy_on_password.checked }); alert("Configurações salvas."); };
    app.querySelector("[data-save-home]")?.addEventListener("click", () => { form.url.value = app.querySelector(".open-now [name=url]").value; updatePreview(); form.scrollIntoView({ behavior: "smooth" }); });
    app.querySelectorAll("[data-room-home]").forEach((button) => button.onclick = async () => { await api.dashboardRoomHome(button.dataset.roomHome); location.reload(); });
    app.querySelectorAll("[data-room-revoke]").forEach((button) => button.onclick = async () => { await api.dashboardRevokeControl(button.dataset.roomRevoke); location.reload(); });
    app.querySelectorAll("[data-room-close]").forEach((button) => button.onclick = async () => { if (confirm("Encerrar esta sessão?")) { await api.dashboardCloseRoom(button.dataset.roomClose); location.reload(); } });
  } catch (error) {
    if (error.status === 403 && allowClaim) {
      try {
        const session = await api.claimDashboardAccess();
        api.setSession(session.access_token, session.user);
        return initDashboard(app, api, false);
      } catch (claimError) {
        error = claimError;
      }
    }
    app.innerHTML = `<div class="browser-loading"><h1>Dashboard CraftPlay</h1><p>${escapeHTML(error.message)}</p><a class="btn btn-primary" href="/auth/discord/login">Entrar com Discord</a></div>`;
  }
}

async function initBrowserDebug(app, api) {
  app.innerHTML = `<main class="dashboard"><header><h1>Debug do navegador</h1><a href="/dashboard">Dashboard</a></header><section class="dashboard-panel"><form class="debug-form"><input required placeholder="Room ID"><button class="btn btn-primary">Carregar</button></form><pre class="debug-output">Sem dados.</pre></section></main>`;
  app.querySelector("form").onsubmit = async (event) => { event.preventDefault(); const output = app.querySelector("pre"); try { output.textContent = JSON.stringify(await api.debugBrowser(event.currentTarget.querySelector("input").value), null, 2); } catch (error) { output.textContent = error.message; } };
}
