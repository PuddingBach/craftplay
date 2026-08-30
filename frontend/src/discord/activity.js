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
    if (!config.discord_client_id || window.self === window.top) return this.snapshot(false);
    try {
      this.sdk = new DiscordSDK(config.discord_client_id);
      await this.sdk.ready();
      const { code } = await this.sdk.commands.authorize({
        client_id: config.discord_client_id,
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
    return { embedded, user: this.user, instanceId: this.instanceId, participants: this.participants };
  }
}
