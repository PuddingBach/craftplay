import "./styles.css";
import { ApiClient } from "./services/api.js";
import { DiscordActivity } from "./discord/activity.js";
import { RoomSync } from "./services/room.js";
import { CraftPlayer } from "./player/player.js";
import { initSpecialPage } from "./diagnostics.js";

const api = new ApiClient();
const discord = new DiscordActivity(api);
const app = document.querySelector("#app");
const playerMount = document.createElement("div");
document.body.append(playerMount);

const labels = { movie: "Filmes", series: "Séries", anime: "Animes", cartoon: "Desenhos" };
const sectionLabels = { trending: "Em alta", movies: "Filmes populares", series: "Séries populares", anime: "Animes", cartoons: "Desenhos", releases: "Lançamentos", continue: "Continuar assistindo", favorites: "Minha lista", recommended: "Recomendados para você" };
const state = { session: null, sections: {}, all: new Map(), category: "all", query: "", genre: "", year: "", rating: "", sort: "popularity", favorites: new Set(), history: new Map(), room: null, roomSync: null, currentPlayer: null, playerOpening: false };
const discordProxyPrefix = location.hostname.endsWith(".discordsays.com") ? "/.proxy" : "";

const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const fallbackImage = "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><defs><linearGradient id="g"><stop stop-color="#1c4fd8"/><stop offset="1" stop-color="#8a3ffc"/></linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/><text x="50%" y="50%" text-anchor="middle" fill="white" font-family="monospace" font-size="34">&lt;/&gt;</text></svg>`);
const debounce = (fn, delay = 260) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; };
const assetURL = (url) => url?.startsWith("/") ? `${discordProxyPrefix}${url}` : url;

function toast(message, error = false) {
  const item = document.createElement("div");
  item.className = `toast${error ? " error" : ""}`;
  item.textContent = message;
  document.querySelector("#toast-region").append(item);
  setTimeout(() => item.remove(), 4200);
}

function avatar(user, extra = "") {
  return user?.avatar
    ? `<img class="avatar ${extra}" src="${escapeHTML(user.avatar)}" alt="${escapeHTML(user.username)}">`
    : `<span class="avatar avatar-fallback ${extra}" aria-label="${escapeHTML(user?.username)}">${escapeHTML(user?.username?.[0] || "?")}</span>`;
}

function shell() {
  const user = state.session.user;
  const warnings = [];
  if (!state.session.config?.discord_configured) warnings.push("Discord OAuth não configurado: defina DISCORD_CLIENT_ID e DISCORD_CLIENT_SECRET na hospedagem.");
  if (!state.providers?.tmdb_configured) warnings.push("TMDB não configurado: defina TMDB_READ_ACCESS_TOKEN para importar o catálogo completo.");
  else if (!state.providers?.tmdb_available) warnings.push(`TMDB indisponível: ${state.providers.tmdb_error || "verifique a credencial"}.`);
  app.innerHTML = `
    <header class="app-header">
      <button class="logo" data-nav="all" aria-label="Início"><span class="logo-ring">&lt;/&gt;</span><span class="logo-copy"><span class="logo-name">craft<em>play</em></span><span class="logo-tag">criamos soluções · construímos o futuro</span></span></button>
      <nav class="main-nav" aria-label="Navegação principal">
        <button class="nav-link active" data-nav="all">Início</button>
        <button class="nav-link" data-nav="movie">Filmes</button>
        <button class="nav-link" data-nav="series">Séries</button>
        <button class="nav-link" data-nav="anime">Animes</button>
        <button class="nav-link" data-nav="cartoon">Desenhos</button>
        <button class="nav-link" data-nav="favorites">Minha Lista</button>
      </nav>
      <div class="header-actions">
        <label class="search-box"><span class="prompt mono">&gt;</span><input id="global-search" type="search" placeholder="buscar_título()" autocomplete="off" aria-label="Pesquisa global"><div class="search-results hidden"></div></label>
        ${avatar(user, "user-avatar")}
        <button class="icon-btn mobile-toggle" aria-label="Abrir menu">☰</button>
      </div>
    </header>
    ${warnings.length ? `<aside class="setup-warning"><b>Configuração incompleta</b>${warnings.map((warning) => `<span>${escapeHTML(warning)}</span>`).join("")}</aside>` : ""}
    <div id="hero"></div>
    <div class="filter-bar" aria-label="Filtros">
      <button class="chip active" data-filter-type="all">Todos</button>
      <button class="chip" data-filter-type="movie">Filmes</button>
      <button class="chip" data-filter-type="series">Séries</button>
      <button class="chip" data-filter-type="anime">Animes</button>
      <button class="chip" data-filter-type="cartoon">Desenhos</button>
      <select class="filter-select" id="genre-filter" aria-label="Gênero"><option value="">Gênero: todos</option></select>
      <select class="filter-select" id="year-filter" aria-label="Ano"><option value="">Ano: todos</option></select>
      <select class="filter-select" id="rating-filter" aria-label="Avaliação"><option value="">Nota: todas</option><option value="8">8+</option><option value="7">7+</option></select>
      <select class="filter-select" id="sort-filter" aria-label="Ordenação"><option value="popularity">Mais populares</option><option value="rating">Melhor avaliados</option><option value="year">Mais recentes</option></select>
      <span class="filter-count mono"></span>
    </div>
    <main class="catalog" id="catalog"></main>
    <footer class="app-footer"><span>craft play — um produto do ecossistema craft systems</span><span>conteúdo demonstrativo com fontes abertas e autorizadas</span></footer>
    <div id="modal-root"></div>`;
  bindShell();
}

function mediaCard(media, progress = null) {
  return `<article class="media-card">
    <button class="card-hit" data-media-id="${escapeHTML(media.id)}" aria-label="Ver ${escapeHTML(media.title)}">
      <div class="poster-wrap">
        <img src="${escapeHTML(assetURL(media.poster) || fallbackImage)}" alt="Capa de ${escapeHTML(media.title)}" loading="lazy" onerror="this.src='${fallbackImage}'">
        <span class="card-badge">&lt;${escapeHTML(media.media_type)}/&gt;</span><span class="card-badge card-rating">★ ${Number(media.rating || 0).toFixed(1)}</span>
      </div>
      ${progress ? `<div class="progress" title="${Math.round(progress * 100)}% assistido"><span style="width:${Math.min(100, progress * 100)}%"></span></div>` : ""}
      <div class="card-copy"><h3>${escapeHTML(media.title)}</h3><p>${media.year || "—"} · ${escapeHTML(labels[media.media_type] || media.media_type)}</p></div>
    </button>
  </article>`;
}

function renderHero() {
  const featured = state.sections.featured?.[0] || [...state.all.values()][0];
  const target = document.querySelector("#hero");
  if (!featured) { target.innerHTML = ""; return; }
  target.innerHTML = `<section class="hero">
    <img class="hero-bg" src="${escapeHTML(assetURL(featured.backdrop || featured.poster) || fallbackImage)}" alt="" onerror="this.src='${fallbackImage}'">
    <div class="hero-content"><span class="eyebrow"><span class="live-dot"></span>destaque_do_catálogo</span><h1>${escapeHTML(featured.title)}</h1>
      <div class="meta"><span class="tag gold">★ ${Number(featured.rating).toFixed(1)}</span><span class="tag purple">${featured.year || "Em breve"}</span>${featured.genres.slice(0,3).map((genre) => `<span class="tag">${escapeHTML(genre)}</span>`).join("")}</div>
      <p>${escapeHTML(featured.overview)}</p><div class="action-row"><button class="btn btn-primary" data-watch="${escapeHTML(featured.id)}">▶ Assistir <span class="mono">play()</span></button><button class="btn btn-ghost" data-detail="${escapeHTML(featured.id)}">Detalhes</button><button class="btn btn-ghost" data-favorite="${escapeHTML(featured.id)}">＋ Minha Lista</button></div>
    </div></section>`;
}

function filteredItems() {
  let items = [...state.all.values()];
  if (state.category !== "all") items = items.filter((item) => item.media_type === state.category);
  if (state.query) { const q = state.query.toLocaleLowerCase("pt-BR"); items = items.filter((item) => `${item.title} ${item.overview} ${item.genres.join(" ")}`.toLocaleLowerCase("pt-BR").includes(q)); }
  if (state.genre) items = items.filter((item) => item.genres.includes(state.genre));
  if (state.year) items = items.filter((item) => String(item.year) === state.year);
  if (state.rating) items = items.filter((item) => item.rating >= Number(state.rating));
  const property = state.sort === "rating" ? "rating" : state.sort === "year" ? "year" : "popularity";
  return items.sort((a, b) => (b[property] || 0) - (a[property] || 0));
}

function renderCatalog() {
  const catalog = document.querySelector("#catalog");
  const filtering = state.category !== "all" || state.query || state.genre || state.year || state.rating;
  if (filtering) {
    const items = filteredItems();
    document.querySelector(".filter-count").textContent = `${items.length} título(s) · consulta()`;
    catalog.innerHTML = items.length ? `<section class="media-row"><div class="row-header"><h2>Resultados</h2><span>${items.length} itens</span></div><div class="media-grid">${items.map((item) => mediaCard(item)).join("")}</div></section>` : empty("Nenhum resultado encontrado", `catálogo.buscar(\"${state.query}\") → []`);
    return;
  }
  const rows = [];
  if (state.sections.continue?.length) rows.push(["continue", state.sections.continue]);
  if (state.sections.favorites?.length) rows.push(["favorites", state.sections.favorites]);
  for (const key of ["trending", "movies", "series", "anime", "cartoons", "releases"]) if (state.sections[key]?.length) rows.push([key, state.sections[key]]);
  document.querySelector(".filter-count").textContent = `${state.all.size} título(s) · catálogo()`;
  catalog.innerHTML = rows.map(([key, items]) => `<section class="media-row"><div class="row-header"><h2>${sectionLabels[key]}</h2><span>${items.length} itens</span></div><div class="media-track">${items.map((item) => mediaCard(item, key === "continue" ? (state.history.get(item.id)?.position || 0) / (state.history.get(item.id)?.duration || 1) : null)).join("")}</div></section>`).join("");
}

function empty(title, detail) { return `<div class="empty-state"><span class="brand-mark">◌</span><strong>${escapeHTML(title)}</strong><span class="mono">&gt; ${escapeHTML(detail)}</span></div>`; }

function fillFilters() {
  const genres = [...new Set([...state.all.values()].flatMap((item) => item.genres))].sort();
  const years = [...new Set([...state.all.values()].map((item) => item.year).filter(Boolean))].sort((a,b) => b-a);
  document.querySelector("#genre-filter").insertAdjacentHTML("beforeend", genres.map((item) => `<option value="${escapeHTML(item)}">${escapeHTML(item)}</option>`).join(""));
  document.querySelector("#year-filter").insertAdjacentHTML("beforeend", years.map((item) => `<option value="${item}">${item}</option>`).join(""));
}

async function showDetails(id) {
  const root = document.querySelector("#modal-root");
  root.innerHTML = `<div class="modal-shell"><div class="detail-modal"><div class="detail-hero skeleton"></div><div class="detail-body">carregando_metadados()</div></div></div>`;
  document.body.classList.add("modal-open");
  try {
    const [media, recommended, availability] = await Promise.all([api.media(id), api.recommendations(id), api.availability(id).catch(() => ({ items: [] }))]);
    state.all.set(media.id, media);
    const favorite = state.favorites.has(media.id);
    root.innerHTML = `<div class="modal-shell"><article class="detail-modal" role="dialog" aria-modal="true" aria-label="${escapeHTML(media.title)}">
      <div class="detail-hero"><img src="${escapeHTML(assetURL(media.backdrop || media.poster) || fallbackImage)}" alt=""><button class="icon-btn modal-close" aria-label="Fechar">✕</button><div class="detail-title"><span class="eyebrow">&lt;${media.media_type}/&gt;</span><h2>${escapeHTML(media.title)}</h2><div class="meta"><span class="tag gold">★ ${Number(media.rating).toFixed(1)}</span><span class="tag purple">${media.year || "—"}</span>${media.genres.map((genre) => `<span class="tag">${escapeHTML(genre)}</span>`).join("")}</div></div></div>
      <div class="detail-body"><div class="detail-layout"><div><span class="mono prompt">&gt; sinopse</span><p>${escapeHTML(media.overview || "Sinopse não disponível.")}</p><div class="action-row"><button class="btn btn-primary" data-watch="${escapeHTML(media.id)}">▶ Assistir</button>${media.trailer ? `<a class="btn btn-ghost" href="${escapeHTML(media.trailer)}" target="_blank" rel="noopener">Trailer</a>` : ""}<button class="btn btn-ghost" data-favorite="${escapeHTML(media.id)}">${favorite ? "✓ Na Minha Lista" : "+ Minha Lista"}</button></div></div>
      <aside class="facts"><div><b>título_original:</b> ${escapeHTML(media.original_title || media.title)}</div><div><b>duração:</b> ${media.duration ? `${media.duration} min` : "não informada"}</div><div><b>status:</b> ${escapeHTML(media.status || "não informado")}</div><div><b>direção:</b> ${escapeHTML(media.director || "não informada")}</div><div><b>elenco:</b> ${escapeHTML(media.cast?.join(", ") || "não informado")}</div><div><b>classificação:</b> ${escapeHTML(media.certification || "não informada")}</div></aside></div>
      ${availability.items?.length ? `<section class="availability"><span class="mono prompt">&gt; disponível_em (informativo)</span><div>${availability.items.map((service) => `<span class="availability-item">${service.logo ? `<img src="${escapeHTML(service.logo)}" alt="">` : ""}${escapeHTML(service.name)} <small>${escapeHTML(service.offer_type)}</small></span>`).join("")}</div><small>Estas opções não são enviadas ao player.</small></section>` : ""}
      ${seasonsTemplate(media)}
      ${recommended.items?.length ? `<section class="season-picker"><span class="mono prompt">&gt; recomendações</span><div class="media-track" style="padding-inline:0">${recommended.items.map((item) => mediaCard(item)).join("")}</div></section>` : ""}
      </div></article></div>`;
    bindModal();
  } catch (error) { root.innerHTML = `<div class="modal-shell"><div class="detail-modal">${empty("Conteúdo indisponível", error.message)}<button class="btn btn-ghost modal-close" style="margin:20px">Fechar</button></div></div>`; bindModal(); }
}

function seasonsTemplate(media) {
  if (!media.seasons?.length) return "";
  return `<section class="season-picker"><span class="mono prompt">&gt; temporadas_e_episódios</span>${media.seasons.map((season) => `<h3>${escapeHTML(season.title)}</h3><div class="episodes">${season.episodes.map((episode) => `<button class="episode" data-episode="${episode.number}" data-season="${season.number}" data-watch="${escapeHTML(media.id)}"><span class="episode-number">${episode.number}</span><span><b>${escapeHTML(episode.title)}</b><br>${escapeHTML(episode.overview)}</span><span>${episode.duration || "—"} min</span></button>`).join("")}</div>`).join("")}</section>`;
}

function bindModal() {
  const root = document.querySelector("#modal-root");
  const close = () => { root.innerHTML = ""; document.body.classList.remove("modal-open"); };
  root.querySelector(".modal-close")?.addEventListener("click", close);
  root.querySelector(".modal-shell")?.addEventListener("click", (event) => { if (event.target.classList.contains("modal-shell")) close(); });
  root.querySelectorAll("[data-watch]").forEach((button) => button.addEventListener("click", () => { const season = Number(button.dataset.season || 0), episode = Number(button.dataset.episode || 0); close(); startWatching(button.dataset.watch, season, episode); }));
  root.querySelectorAll("[data-favorite]").forEach((button) => button.addEventListener("click", () => toggleFavorite(button.dataset.favorite, button)));
  root.querySelectorAll("[data-media-id]").forEach((button) => button.addEventListener("click", () => showDetails(button.dataset.mediaId)));
}

async function toggleFavorite(id, button) {
  const media = state.all.get(id) || await api.media(id);
  try {
    if (state.favorites.has(id)) { await api.removeFavorite(id); state.favorites.delete(id); button.textContent = "+ Minha Lista"; toast("Removido da Minha Lista"); }
    else { await api.addFavorite(media); state.favorites.add(id); button.textContent = "✓ Na Minha Lista"; toast("Adicionado à Minha Lista"); }
    await loadUserCollections(); renderCatalog();
  } catch (error) { toast(error.message, true); }
}

async function startWatching(id, season = 0, episode = 0) {
  if (state.playerOpening) return;
  state.playerOpening = true;
  playerMount.innerHTML = `<section class="player-layer"><div class="boot-screen"><span class="brand-mark">▶</span><h2>Procurando fonte...</h2><p class="mono">playback_resolver.search()</p></div></section>`;
  document.body.classList.add("modal-open");
  try {
    const [media, result] = await Promise.all([api.media(id), api.sources(id, season, episode)]);
    if (!state.room) state.room = await api.createRoom(state.session.instanceId);
    if (!state.roomSync) { state.roomSync = new RoomSync(state.room, state.session.user); state.roomSync.connect(); }
    const mediaChange = () => state.roomSync.send("MEDIA_CHANGE", { media_id: id, season, episode });
    if (state.roomSync.socket?.readyState === WebSocket.OPEN) mediaChange();
    else state.roomSync.addEventListener("open", mediaChange, { once: true });
    await state.currentPlayer?.destroy();
    state.currentPlayer = new CraftPlayer({
      mount: playerMount, media, sources: result.sources, unavailable: result.unavailable, roomSync: state.roomSync, api, season, episode,
      onClose: () => { state.currentPlayer = null; document.body.classList.remove("modal-open"); loadUserCollections().then(renderCatalog); },
      onEpisode: (nextSeason, nextEpisode) => { state.currentPlayer?.destroy(); startWatching(id, nextSeason, nextEpisode); },
    });
    document.body.classList.add("modal-open");
  } catch (error) { playerMount.innerHTML = ""; document.body.classList.remove("modal-open"); toast(`Não foi possível abrir o player: ${error.message}`, true); }
  finally { state.playerOpening = false; }
}

async function performSearch(query) {
  const panel = document.querySelector(".search-results");
  state.query = query.trim();
  if (!state.query) { panel.classList.add("hidden"); renderCatalog(); return; }
  try {
    const result = await api.search({ q: state.query, sort: state.sort });
    result.items.forEach((item) => state.all.set(item.id, item));
    panel.innerHTML = result.items.slice(0, 7).map((item) => `<button class="search-result" data-media-id="${escapeHTML(item.id)}"><img src="${escapeHTML(assetURL(item.poster) || fallbackImage)}" alt=""><span><b>${escapeHTML(item.title)}</b><small>${item.year || "—"} · ${labels[item.media_type]}</small></span><span>→</span></button>`).join("") || `<div class="empty-state">nenhum_resultado()</div>`;
    panel.classList.remove("hidden");
    panel.querySelectorAll("[data-media-id]").forEach((button) => button.onclick = () => { panel.classList.add("hidden"); showDetails(button.dataset.mediaId); });
    renderCatalog();
  } catch (error) { toast(error.message, true); }
}

function setCategory(category) {
  if (category === "favorites") {
    state.category = "all"; state.query = "";
    const favorites = state.sections.favorites || [];
    document.querySelector("#catalog").innerHTML = favorites.length ? `<section class="media-row"><div class="row-header"><h2>Minha Lista</h2><span>${favorites.length} itens</span></div><div class="media-grid">${favorites.map((item) => mediaCard(item)).join("")}</div></section>` : empty("Sua lista está vazia", "favoritos.listar() → []");
  } else { state.category = category; renderCatalog(); }
  document.querySelectorAll("[data-nav]").forEach((button) => button.classList.toggle("active", button.dataset.nav === category));
  document.querySelectorAll("[data-filter-type]").forEach((button) => button.classList.toggle("active", button.dataset.filterType === (category === "favorites" ? "all" : category)));
  document.querySelector(".main-nav").classList.remove("open");
}

function bindShell() {
  document.querySelectorAll("[data-nav]").forEach((button) => button.onclick = () => setCategory(button.dataset.nav));
  document.querySelectorAll("[data-filter-type]").forEach((button) => button.onclick = () => setCategory(button.dataset.filterType));
  document.querySelector(".mobile-toggle").onclick = () => document.querySelector(".main-nav").classList.toggle("open");
  document.querySelector("#global-search").addEventListener("input", debounce((event) => performSearch(event.target.value)));
  document.querySelector("#genre-filter").onchange = (event) => { state.genre = event.target.value; renderCatalog(); };
  document.querySelector("#year-filter").onchange = (event) => { state.year = event.target.value; renderCatalog(); };
  document.querySelector("#rating-filter").onchange = (event) => { state.rating = event.target.value; renderCatalog(); };
  document.querySelector("#sort-filter").onchange = (event) => { state.sort = event.target.value; renderCatalog(); };
  app.addEventListener("click", (event) => {
    if (event.target.closest("#modal-root")) return;
    const detail = event.target.closest("[data-detail], [data-media-id]"); if (detail) showDetails(detail.dataset.detail || detail.dataset.mediaId);
    const watch = event.target.closest("[data-watch]"); if (watch) startWatching(watch.dataset.watch);
    const favorite = event.target.closest("[data-favorite]"); if (favorite) toggleFavorite(favorite.dataset.favorite, favorite);
  });
}

async function loadUserCollections() {
  try {
    const [favorites, history] = await Promise.all([api.favorites(), api.history()]);
    state.favorites = new Set(favorites.items.map((item) => item.media_id));
    state.history = new Map(history.items.map((item) => [item.media_id, item]));
    const ids = [...new Set([...state.favorites, ...state.history.keys()])];
    const media = (await Promise.all(ids.map((id) => api.media(id).catch(() => null)))).filter(Boolean);
    media.forEach((item) => state.all.set(item.id, item));
    state.sections.favorites = media.filter((item) => state.favorites.has(item.id));
    state.sections.continue = media.filter((item) => { const entry = state.history.get(item.id); return entry && entry.duration > 0 && entry.position / entry.duration < .95; });
  } catch (error) { console.warn("Coleções pessoais indisponíveis", error); }
}

async function init() {
  if (initSpecialPage(api)) return;
  try {
    const activity = await discord.initialize();
    const home = await api.home();
    state.session = { ...activity, user: home.user || activity.user };
    state.sections = home.sections;
    state.providers = home.providers;
    Object.values(state.sections).flat().forEach((item) => state.all.set(item.id, item));
    await loadUserCollections();
    shell(); renderHero(); fillFilters(); renderCatalog();
  } catch (error) {
    app.innerHTML = `<div class="boot-screen"><span class="brand-mark">!</span><h1>Não foi possível iniciar a CraftPlay</h1><p>${escapeHTML(error.message)}</p><button class="btn btn-primary" onclick="location.reload()">Tentar novamente</button></div>`;
  }
}

window.addEventListener("keydown", (event) => { if (event.key === "Escape" && !state.currentPlayer) { document.querySelector("#modal-root").innerHTML = ""; document.body.classList.remove("modal-open"); } });
init();
