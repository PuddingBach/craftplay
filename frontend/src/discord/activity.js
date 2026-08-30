import { DiscordSDK } from "@discord/embedded-app-sdk";

export function resolveDiscordClientId(configuredClientId, hostname = location.hostname) {
  const proxyClientId = hostname.endsWith(".discordsays.com") ? hostname.split(".")[0] : "";
  return proxyClientId || configuredClientId || "";
}

function readableDiscordError(error) {
  const message = error instanceof Error ? error.message : String(error || "erro desconhecido");
  return message.length > 180 ? `${message.slice(0, 177)}...` : message;
}

export class DiscordActivity {
  constructor(api) {
    this.api = api;
    this.sdk = null;
    this.user = api.localUser;
    this.instanceId = `browser-${location.hostname}`;
    this.participants = [];
  }

  async initialize() {
    const config = await this.api.config();
    this.config = config;
    if (window.self === window.top) return this.snapshot(false);
    const clientId = resolveDiscordClientId(config.discord_client_id);
    if (!clientId) throw new Error("Client ID da Discord Activity não configurado.");
    try {
      this.sdk = new DiscordSDK(clientId);
      await Promise.race([
        this.sdk.ready(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("Tempo limite ao conectar com o Discord")), 10000)),
      ]);
      const { code } = await this.sdk.commands.authorize({
        client_id: clientId,
        response_type: "code",
        state: crypto.randomUUID(),
        prompt: "none",
        scope: ["identify"],
      });
      if (!code) throw new Error("O Discord não retornou um código de autorização.");
      const session = await this.api.discordAuth(code);
      if (!session?.access_token || !session?.discord_access_token || !session?.user) {
        throw new Error("O servidor não concluiu a troca do código OAuth2.");
      }
      this.api.setSession(session.access_token, session.user);
      this.user = session.user;
      const authentication = await this.sdk.commands.authenticate({ access_token: session.discord_access_token });
      if (!authentication) throw new Error("O Discord não confirmou a sessão da Activity.");
      this.instanceId = this.sdk.instanceId || this.sdk.channelId || this.instanceId;
      await this.sdk.subscribe("ACTIVITY_INSTANCE_PARTICIPANTS_UPDATE", ({ participants }) => {
        this.participants = participants || [];
        window.dispatchEvent(new CustomEvent("craftplay:participants", { detail: this.participants }));
      });
      return this.snapshot(true);
    } catch (error) {
      console.error("Falha ao autenticar a Discord Activity.", error);
      throw new Error(`Falha na autenticação da Discord Activity: ${readableDiscordError(error)}`);
    }
  }

  snapshot(embedded) {
    return { embedded, user: this.user, instanceId: this.instanceId, participants: this.participants, config: this.config };
  }
}
