import { DiscordSDK } from "@discord/embedded-app-sdk";

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
    const proxyClientId = location.hostname.endsWith(".discordsays.com") ? location.hostname.split(".")[0] : "";
    const clientId = config.discord_client_id || proxyClientId;
    if (!clientId) return this.snapshot(false);
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
      const session = await this.api.discordAuth(code);
      this.api.setSession(session.access_token, session.user);
      this.user = session.user;
      await this.sdk.commands.authenticate({ access_token: session.discord_access_token });
      this.instanceId = this.sdk.instanceId || this.sdk.channelId || this.instanceId;
      await this.sdk.subscribe("ACTIVITY_INSTANCE_PARTICIPANTS_UPDATE", ({ participants }) => {
        this.participants = participants || [];
        window.dispatchEvent(new CustomEvent("craftplay:participants", { detail: this.participants }));
      });
      return this.snapshot(true);
    } catch (error) {
      console.warn("Discord Activity indisponível; usando modo navegador.", error);
      return this.snapshot(false);
    }
  }

  snapshot(embedded) {
    return { embedded, user: this.user, instanceId: this.instanceId, participants: this.participants, config: this.config };
  }
}
