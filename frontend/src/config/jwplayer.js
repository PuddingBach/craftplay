const jwConfig = {
  enabled: false,
  libraryUrl: "",
  licenseKey: "",
  setup: { width: "100%", height: "100%", autostart: false, controls: false, preload: "metadata" },
};
let libraryPromise;

export function configureJWPlayer(config = {}) {
  jwConfig.enabled = Boolean(config.enabled);
  jwConfig.libraryUrl = String(config.library_url || "");
  jwConfig.licenseKey = String(config.license_key || "");
}

export function isJWPlayerEnabled() { return jwConfig.enabled && Boolean(jwConfig.libraryUrl); }
export function getJWPlayerConfig() { return { ...jwConfig, setup: { ...jwConfig.setup } }; }

export async function loadJWPlayerLibrary() {
  if (!isJWPlayerEnabled()) throw new Error("JW Player não configurado");
  if (globalThis.jwplayer) return globalThis.jwplayer;
  if (!libraryPromise) libraryPromise = new Promise((resolve, reject) => {
    let parsed;
    try { parsed = new URL(jwConfig.libraryUrl); } catch { reject(new Error("JW_PLAYER_LIBRARY_URL inválida")); return; }
    if (parsed.protocol !== "https:") { reject(new Error("JW_PLAYER_LIBRARY_URL deve usar HTTPS")); return; }
    const script = document.createElement("script"); script.src = parsed.href; script.async = true;
    script.onload = () => { if (!globalThis.jwplayer) return reject(new Error("A biblioteca carregada não expôs jwplayer()")); if (jwConfig.licenseKey) globalThis.jwplayer.key = jwConfig.licenseKey; resolve(globalThis.jwplayer); };
    script.onerror = () => reject(new Error("Não foi possível carregar a biblioteca JW Player")); document.head.append(script);
  });
  return libraryPromise;
}
