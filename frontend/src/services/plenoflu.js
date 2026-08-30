const IMDB_PATTERN = /^tt\d{5,12}$/;

export function validateImdbId(imdbId) {
  return typeof imdbId === "string" && IMDB_PATTERN.test(imdbId);
}

export function buildPlenoFluMovieUrl(imdbId) {
  if (!validateImdbId(imdbId)) throw new TypeError("IMDb ID inválido");
  return `https://plenoflu.com/movie/${imdbId}`;
}

export function buildPlenoFluEpisodeUrl(imdbId, season, episode) {
  if (!validateImdbId(imdbId) || !Number.isInteger(season) || !Number.isInteger(episode) || season < 1 || episode < 1) {
    throw new TypeError("IMDb ID, temporada ou episódio inválido");
  }
  return `https://plenoflu.com/tvshow/${imdbId}/${season}/${episode}`;
}

export class PlenoFluPlayer {
  constructor({ container, imdbId, type, season = 0, episode = 0, onBack }) {
    this.container = container;
    this.onBack = onBack;
    this.url = type === "movie" ? buildPlenoFluMovieUrl(imdbId) : buildPlenoFluEpisodeUrl(imdbId, season, episode);
  }

  mount() {
    const wrapper = document.createElement("div");
    wrapper.className = "external-player";
    const loading = document.createElement("div");
    loading.className = "external-loading mono";
    loading.textContent = "Carregando servidor...";
    const iframe = document.createElement("iframe");
    iframe.src = this.url;
    iframe.title = "Player PlenoFlu";
    iframe.width = "100%";
    iframe.height = "100%";
    iframe.frameBorder = "0";
    iframe.allowFullscreen = true;
    iframe.allow = "autoplay; fullscreen; picture-in-picture";
    const failed = () => {
      loading.innerHTML = "Não foi possível carregar este servidor.<br>Use ‘Voltar ao servidor principal’.";
      loading.classList.add("error");
    };
    const timeout = setTimeout(failed, 15000);
    iframe.addEventListener("load", () => { clearTimeout(timeout); loading.remove(); }, { once: true });
    iframe.addEventListener("error", () => { clearTimeout(timeout); failed(); }, { once: true });
    const back = document.createElement("button");
    back.className = "btn btn-ghost external-back";
    back.textContent = "Voltar ao servidor principal";
    back.onclick = () => this.onBack?.();
    wrapper.append(loading, iframe, back);
    this.container.replaceChildren(wrapper);
    this.element = wrapper;
  }

  destroy() { this.element?.remove(); }
}
