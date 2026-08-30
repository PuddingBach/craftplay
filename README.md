# CraftPlay

CraftPlay é uma Discord Activity de navegação remota compartilhada. Uma sala mantém uma única instância visual do Chromium, controlada pelo Playwright; vídeo e áudio são publicados uma vez no LiveKit Ingress e distribuídos pelo SFU para até dez participantes. O player MP4/HLS/DASH/JW anterior continua disponível como `DirectPlaybackMode` opcional em `/?mode=direct`.

O projeto preserva a identidade do HTML original `craft-play.html`: tema escuro, tipografia Rajdhani/Manrope/JetBrains Mono, gradientes azul–roxo, linguagem visual inspirada em código e microanimações. O arquivo original foi mantido intacto como referência.

## Arquitetura principal

```text
Discord Activity (Home / Browser View / Dashboard)
        │ REST + WebSocket                    │ WebRTC subscribe
        ▼                                     ▼
FastAPI ── Discord OAuth + VIEW_CHANNEL     LiveKit SFU
        ├─ BrowserEntry CRUD                   ▲
        ├─ RoomState + ControlLease             │ RTMP Ingress
        ├─ Navigation Guard + SSRF              │
        └─ BrowserService ─ Playwright ─ Chromium visual
                              │ X11 + PulseAudio
                              └─ GStreamer (captura única por sala)
```

`BrowserMode` é o padrão. BrowserEntries são cadastradas pelo dashboard e apontam diretamente para páginas permitidas; o TMDB é usado somente para metadados. O sistema não faz scraping nem contorna DRM, paywall, CAPTCHA, anti-bot, CORS, X-Frame-Options ou proteção de credenciais. Serviços com DRM podem abrir e aceitar login, mas a captura pode resultar em tela protegida.

### Componentes

- `backend/browser/service.py`: uma sessão Chromium por sala, perfil isolado, navegação e recuperação única após crash.
- `backend/browser/security.py`: valida esquema, credenciais na URL, DNS e todos os IPs resolvidos; bloqueia loopback, RFC1918, link-local, metadata e redes reservadas.
- `backend/browser/shield.py`: interceptação de anúncios/trackers, popups, downloads e redirects externos nos modos `OFF`, `STANDARD` e `STRICT`.
- `backend/browser/publisher.py`: cria um LiveKit RTMP Ingress e captura o display X11 + monitor PulseAudio com GStreamer. Não usa screenshots periódicos.
- `backend/room_manager.py`: presença, limite da sala, controle `HOST_ONLY`, `REQUEST_CONTROL` ou `SHARED`, fila, lease exclusivo, rate limit, privacidade e limpeza automática.
- `frontend/src/browser/`: Home dinâmica, controles normalizados, cursor remoto, tela de privacidade e cliente LiveKit com adaptive stream.
- `frontend/src/player/`: `DirectPlaybackMode` preservado para mídia direta autorizada.

## Dashboard e Discord OAuth

O dashboard fica em `/dashboard`. Usuários não autenticados são enviados a `/auth/discord/login`; o callback exato é:

```text
https://craftplay.shardweb.app/auth/discord/callback
```

Após `identify`, o backend consulta o Discord com o token do bot, confirma que o membro pertence a `DISCORD_GUILD_ID` e calcula a permissão efetiva `VIEW_CHANNEL` de `DASHBOARD_CHANNEL_ID`, aplicando permissões base, overwrite de `@everyone`, cargos e usuário na ordem do Discord. `DASHBOARD_ALLOWED_ROLE_IDS` permite liberar explicitamente cargos administrativos. IDs de canal e usuário nunca são tratados como equivalentes. A sessão administrativa fica em cookie `HttpOnly`, `Secure` e `SameSite=Lax`; secrets não são enviados ao frontend.

O dashboard possui visão geral, BrowserEntry CRUD, ativar/desativar, fixar, destacar, duplicar, testar link, salas ativas e `/debug/browser`. A ferramenta “Abrir Agora” usa `/api/dashboard/browser/open-now` e não publica a URL na Home.

## BrowserEntry e banco

As tabelas são adicionadas sem remover as anteriores: `browser_entries`, `browser_history`, `browser_favorites`, `browser_sessions`, `browser_session_members`, `blocked_domains`, `allowed_domains`, `browser_settings`, `admin_audit_logs` e `schema_migrations`. `Base.metadata.create_all()` cria apenas o que falta e `backend/migrations.py` registra a migration aditiva `20260830_01_shared_browser`, incluindo entradas iniciais oficiais somente quando a tabela está vazia.

Campos principais de BrowserEntry: tipo, categoria, URL, poster/banner/ícone, descrição, modo de abertura, shield, trust level, destaque, fixação, ordenação e expiração. Entradas expiradas ou desativadas não aparecem em `GET /api/browser/entries`.

## Controle e privacidade

O padrão é `REQUEST_CONTROL`. Solicitações entram em fila; o host concede um lease exclusivo que expira após `CONTROL_IDLE_TIMEOUT` sem atividade e então retorna ao host. Coordenadas usam o intervalo `0.0..1.0` e são convertidas para a resolução real do Chromium. Mouse move, scroll e teclado têm rate limit por usuário/sala. Em Modo Privado, tokens WebRTC de espectadores são recusados e inputs não-host são bloqueados até `PRIVACY_OFF`.

## WebRTC e infraestrutura

O frontend recebe somente tokens LiveKit com `canSubscribe=true` e `canPublish=false`. O BrowserPublisher cria o Ingress com identidade própria e publica uma captura X11/PulseAudio; o LiveKit distribui a mesma captura para todos, sem criar um Chromium por participante. Para LiveKit Cloud, Ingress já faz parte do serviço. Em self-host, LiveKit Server, Redis e LiveKit Ingress são processos separados.

O container do projeto instala Chromium, Xvfb, PulseAudio e plugins GStreamer necessários. Para produção, reserve aproximadamente 1–2 GB por Chromium no browser worker; o LiveKit recomenda infraestrutura separada para Ingress com transcodificação. A aplicação web comum da ShardCloud não documenta Docker Compose/processos auxiliares, portanto use uma VPS/worker separado ou LiveKit Cloud para a camada de captura/SFU. Sem esses componentes, `/api/browser/status` informa `unavailable` em vez de simular saúde.

## Recursos implementados

- Home responsiva com destaque, carrosséis, skeletons, imagens lazy-loaded e navegação mobile.
- Pesquisa com debounce e filtros por tipo, ano, gênero, nota e ordenação.
- Detalhes, elenco, direção, temporadas, episódios e recomendações.
- Minha Lista e Continuar Assistindo vinculados ao Discord ID.
- Player adaptado ao design original com MP4, HLS.js, Shaka/DASH e embeds.
- Sala automática por instância da Activity, participantes, host, transferência automática/manual e solicitação de controle.
- Sincronização de play, pause, seek, mídia, episódio, velocidade, áudio e legenda; ressincronização por drift acima de 2,5 s.
- API REST documentada automaticamente em `/docs` e WebSocket em `/ws/room/{room_id}`.
- Bot/interactions endpoint com `/iniciar-player`, que abre a Activity diretamente.
- Integração opcional e isolada com o embed oficial PlenoFlu.
- Catálogo local funcional com Blender Open Movies quando o TMDB não estiver configurado.

## 1. Instalação

Requisitos: Python 3.12+, Node.js 22+ e, em produção, PostgreSQL.

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
npm install
cp .env.example .env
```

No PowerShell, use `Copy-Item .env.example .env` no lugar de `cp`.

## 2. Configuração

Edite `.env`:

```dotenv
DISCORD_CLIENT_ID=123456789012345678
DISCORD_CLIENT_SECRET=segredo_oauth2
DISCORD_BOT_TOKEN=token_do_bot
DISCORD_PUBLIC_KEY=chave_publica_da_aplicacao
DISCORD_GUILD_ID=servidor_de_teste_opcional
DISCORD_ACTIVITY_URL=https://craftplay.shardweb.app
DISCORD_REDIRECT_URI=https://craftplay.shardweb.app/auth/discord/callback
DASHBOARD_CHANNEL_ID=canal_visivel_por_administradores
DASHBOARD_ALLOWED_ROLE_IDS=id_cargo_1,id_cargo_2
TMDB_API_KEY=chave_tmdb_opcional
TMDB_READ_ACCESS_TOKEN=token_de_leitura_tmdb_opcional
YOUTUBE_API_KEY=chave_youtube_opcional
VIMEO_ACCESS_TOKEN=token_vimeo_opcional
ADMIN_API_KEY=gere_uma_chave_administrativa_longa
ROOM_MAX_PARTICIPANTS=10
MAX_BROWSER_SESSIONS=5
BROWSER_WIDTH=1920
BROWSER_HEIGHT=1080
BROWSER_FPS=30
BROWSER_IDLE_TIMEOUT=1800
BROWSER_START_TIMEOUT=30
EMPTY_ROOM_GRACE_PERIOD=120
CONTROL_IDLE_TIMEOUT=120
BROWSER_ALLOW_DOWNLOADS=false
BROWSER_HEADLESS=false
BROWSER_HOMEPAGE=about:blank
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
PLAYBACK_CACHE_TTL_SECONDS=21600
PLAYBACK_VALIDATION_TIMEOUT=10
REDECANAIS_PROVIDER_ENABLED=false
JW_PLAYER_ENABLED=false
JW_PLAYER_LIBRARY_URL=https://cdn.jwplayer.com/libraries/SEU_PLAYER_ID.js
JW_PLAYER_LICENSE_KEY=
PLENOFLU_ENABLED=false
DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/craftplay
SECRET_KEY=gere-um-valor-aleatorio-longo
ALLOWED_ORIGINS=https://craftplay.shardweb.app
ENVIRONMENT=production
PORT=8000
```

`DISCORD_GUILD_ID` torna o registro de `/iniciar-player` imediato no servidor de testes. Sem ele, o comando é global. Adicione `DISCORD_REDIRECT_URI` na seção OAuth2 do Discord Developer Portal. Nunca envie `.env`, tokens LiveKit ou tokens Discord ao Git; o arquivo já está ignorado.

### Playback e disponibilidade

TMDB, AniList, Jikan e TVMaze fornecem somente metadados. As fontes reproduziveis vem exclusivamente dos Playback Providers e passam por validacao antes de chegar ao player.

- `/admin/sources`: cadastro de fontes licenciadas manuais.
- `/debug/providers`: diagnostico dos providers e teste das cinco engines.
- `GET /api/media/{id}/availability`: lojas disponiveis; esse resultado nunca alimenta o player.
- `GET /api/playback/providers/status`: healthcheck dos providers.

### Provider Registry e RedeCanais

O `ProviderRegistry` registra providers dinamicamente, ordena pela prioridade e mantem metricas de requisicoes, sucessos, falhas, restricoes e tempo medio. O fallback atual segue Custom (100), RedeCanais (80), Archive (60), YouTube (40), Vimeo (30), Wikimedia (20) e PlenoFlu (10).

O `RedeCanaisProvider` e experimental e permanece desativado por padrao. Os projetos Kodi citados foram usados somente como referencia da separacao pagina -> resolver -> player. Como nao foi encontrada uma API publica documentada com sinal verificavel de autorizacao/licenca, a CraftPlay nao extrai streams, tokens ou URLs internas dessas paginas. Quando ativado sem uma integracao oficialmente autorizada, o provider informa `NO_AUTHORIZED_PUBLIC_API` e o resolver continua no proximo provider.

Para adicionar um provider futuro, implemente `PlaybackProvider`, atribua `name` e `priority`, retorne apenas `PlaybackSource` validado e registre a instancia no `ProviderRegistry`. URLs diretas autorizadas podem usar `MediaResolver`; embeds permitidos podem usar `EmbedResolver`. `HtmlResolver` deliberadamente nao extrai streams de paginas arbitrarias.

### JW/JWX Player

Quando `JW_PLAYER_ENABLED=true` e `JW_PLAYER_LIBRARY_URL` aponta para a biblioteca HTTPS copiada do painel JWX, o `PlayerController` usa `JWPlayerAdapter` como engine principal para HLS, DASH, MP4 e WebM. YouTube, Vimeo e embeds continuam em adapters proprios. Se a biblioteca ou o setup JW falhar, a mesma fonte volta automaticamente para HLS.js, Shaka ou video nativo sem recarregar a pagina.

A biblioteca cloud-hosted ja inclui a licenca e normalmente nao exige `JW_PLAYER_LICENSE_KEY`. Essa segunda variavel existe apenas para uma distribuicao self-hosted licenciada. A chave de player precisa chegar ao navegador e, portanto, nao deve ser confundida com API secret; nunca coloque Management API secrets nessa variavel. Dentro da Discord Activity, adicione no Developer Portal um URL Mapping para o dominio da biblioteca JWX se o console indicar `blocked:csp`.

O player visual da CraftPlay permanece sobre a engine. Botoes, Watch Party e WebSocket falam somente com `PlayerController`, que normaliza play, pause, seek, volume, mute, duracao, estado, buffering, erros e cleanup. Use `/debug/player` para validar uma URL autorizada e conferir engine, tipo, posicao, duracao e buffer.

## 3. Como obter as chaves

- **TMDB:** crie uma conta em [The Movie Database](https://www.themoviedb.org/), abra Configurações → API e copie o **Token de Leitura da API** para `TMDB_READ_ACCESS_TOKEN`. Alternativamente, a chave v3 pode ser colocada em `TMDB_API_KEY`. Sem uma das duas credenciais, somente o catálogo aberto local é exibido.
- **Discord:** no [Discord Developer Portal](https://discord.com/developers/applications), crie ou abra a aplicação. O Application ID é `DISCORD_CLIENT_ID`; a Public Key fica em General Information; o Client Secret em OAuth2; o token é gerado na seção Bot.
- **PostgreSQL:** use a URL fornecida pelo serviço da ShardCloud. URLs iniciadas com `postgres://` e `postgresql://` são normalizadas automaticamente para o driver Psycopg.
- **SECRET_KEY:** gere localmente com `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## 4. Discord Developer Portal

1. Em **OAuth2**, adicione os redirects exigidos pelo fluxo da sua aplicação.
2. Em **Installation**, habilite os contextos desejados e os escopos `applications.commands` e `bot` quando usar o bot.
3. Em **Bot**, gere o token. O bot não precisa de permissões administrativas.
4. Em **General Information**, copie a Public Key para validar as interações.
5. Em **Interactions Endpoint URL**, informe `https://craftplay.shardweb.app/api/discord/interactions`.

O endpoint valida toda requisição com Ed25519 antes de responder. Requisições sem assinatura válida recebem HTTP 401.

## 5. Configurar e iniciar a Discord Activity

1. Abra **Activities → Settings** e habilite Activities.
2. Em **URL Mappings**, crie o prefixo `/` apontando para `craftplay.shardweb.app`. O target não pode conter `https://` nem uma rota de arquivo.
3. Configure os domínios externos usados pelas imagens/fontes nas regras de rede da Activity. Se ativar PlenoFlu, permita `plenoflu.com` como destino de frame; o próprio serviço também precisa autorizar incorporação.
4. O Discord cria automaticamente o Entry Point **Launch**. Ele pode ser renomeado no portal.
5. Registre o comando adicional:

```bash
python -m backend.bot.register_commands
```

Na chamada ou canal, execute `/iniciar-player`. O FastAPI responde com o callback oficial `LAUNCH_ACTIVITY` (tipo 12), e o Discord abre a CraftPlay. A aplicação web e o bot usam a mesma Application no portal.

## 6. Executar localmente

Em dois terminais:

```bash
uvicorn backend.main:app --reload --port 8000
npm run dev
```

Abra `http://localhost:5173`. Fora do iframe do Discord, a aplicação entra no modo visitante local. Para testar a Activity real, exponha a porta por HTTPS e aponte um URL Mapping de desenvolvimento do Discord para esse endereço.

Para simular o pacote de produção:

```bash
npm run build
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Ou execute `docker compose up --build`.

## 7. Publicar na ShardCloud

1. Crie um serviço web conectado a este repositório.
2. O arquivo `.shardcloud` identifica o `main.py` da raiz como entrypoint Python, mesmo com o `package.json` do frontend presente.
3. O comando de início instala o `requirements.txt` de modo defensivo e executa `python main.py`. O entrypoint lê a porta fornecida pela variável `PORT`. Essa configuração já está definida em `.shardcloud` e no `Procfile`.
4. Adicione um PostgreSQL e copie a URL para `DATABASE_URL`.
5. Cadastre todas as variáveis de `.env.example` no painel; não faça upload do `.env`.
6. Verifique `https://seu-dominio/api/health` e `https://seu-dominio/docs`.

Se o log disser `uvicorn: not found` ou `No module named uvicorn`, faça um redeploy limpando o cache de dependências. Isso força a plataforma a reler o novo entrypoint Python e o `requirements.txt`.

As tabelas são criadas de forma idempotente na inicialização. Para evolução de schema em uma operação maior, recomenda-se adicionar Alembic antes da primeira migração que altere dados existentes.

## 8. Domínio craftplay.shardweb.app

No painel da ShardCloud, associe `craftplay.shardweb.app` ao serviço web e aguarde o certificado HTTPS ficar ativo. Depois:

- defina `DISCORD_ACTIVITY_URL=https://craftplay.shardweb.app`;
- defina `ALLOWED_ORIGINS=https://craftplay.shardweb.app`;
- atualize o URL Mapping e a Interactions Endpoint URL no Discord;
- confirme que o proxy encaminha upgrade de conexão para `/ws/*`.

A porta nunca é fixa: Uvicorn lê `PORT` fornecida pelo ambiente.

### Diagnóstico da implantação

Abra `https://craftplay.shardweb.app/api/health`. Em `configuration`, os valores `discord_client`, `discord_oauth` e `tmdb` devem ser `true`, e `environment` deve ser `production`. A rota `/api/config` também informa apenas se as integrações estão configuradas, sem revelar seus segredos.

Se a Activity abrir em branco, confirme no Discord Developer Portal:

```text
Activities → URL Mappings
PREFIX: /
TARGET: craftplay.shardweb.app
```

O frontend detecta `discordsays.com` e usa automaticamente o caminho compatível `/.proxy` para API, assets locais e WebSocket.

## 9. Adicionar metadata providers

1. Implemente `MetadataProvider` em `backend/providers/`.
2. Normalize todas as respostas para `MediaItem`, `Season` e `Episode` de `backend/schemas.py`.
3. Registre o provider em `CatalogService` e decida como mesclar/deduplicar seções.
4. Trate indisponibilidade e limites do serviço: o catálogo não deve cair por causa de um provider.

Os arquivos `anilist.py`, `jikan.py` e `tvmaze.py` reservam integrações futuras sem acoplar seus formatos ao restante da aplicação.

## 10. Adicionar playback providers

1. Implemente `PlaybackProvider.resolve()` em `backend/playback/providers/`.
2. Retorne `PlaybackSource` com `source_type` igual a `MP4`, `HLS`, `DASH` ou `EMBED`.
3. Registre o provider no `PlaybackResolver`.
4. Registre apenas fontes cuja incorporação/reprodução esteja autorizada. Não presuma que um item do TMDB possui stream.

O player principal não conhece a forma como cada provider descobre sua fonte.

## Integração opcional PlenoFlu

Ative com `PLENOFLU_ENABLED=true`. O provider só aparece quando:

- o TMDB retornou IMDb ID no formato `tt` + dígitos;
- filmes têm IMDb ID válido;
- séries têm IMDb ID, temporada e episódio maiores que zero.

O backend constrói somente os endpoints oficiais `/movie/{IMDb}` ou `/tvshow/{IMDb}/{temporada}/{episódio}`. O frontend replica a validação em `frontend/src/services/plenoflu.js`, onde `PlenoFluPlayer` cria o iframe de modo seguro. O seletor **Servidor** alterna entre Principal e PlenoFlu sem recarregar a página. O iframe é removido ao voltar para o servidor principal. Nenhum `.m3u8`, MP4 interno, token ou endpoint privado é extraído.

Se o iframe não abrir, confirme que o serviço permite `frame-ancestors`/incorporação dentro do Discord. O erro de política do domínio externo não pode ser contornado pela CraftPlay; mantenha o servidor principal disponível.

Antes de listar o PlenoFlu, o backend verifica `X-Frame-Options`, `Content-Security-Policy` e o status HTTP do endpoint. Se o serviço responder com `SAMEORIGIN`, `DENY`, `frame-ancestors 'self'` ou erro HTTP, a fonte não é oferecida e o player exibe um fallback. Para ocultar completamente a integração, defina `PLENOFLU_ENABLED=false`.

## API principal

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/home` | seções da Home |
| GET | `/api/search` | pesquisa, filtros e paginação |
| GET | `/api/media/{id}` | detalhes normalizados |
| GET | `/api/media/{id}/sources` | fontes autorizadas |
| GET/POST/DELETE | `/api/user/favorites` | Minha Lista |
| GET | `/api/user/history` | Continuar Assistindo |
| POST | `/api/playback/progress` | progresso do player |
| POST/GET | `/api/rooms` | salas por instância |
| WS | `/ws/room/{room_id}` | sincronização em tempo real |
| POST | `/api/discord/interactions` | comando `/iniciar-player` |

### API BrowserMode

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/browser/entries` | Home e pesquisa local de BrowserEntries |
| GET | `/api/browser/entries/{id}` | detalhes da entrada |
| GET | `/api/browser/status` | Chromium, Playwright, publisher, WebRTC e capacidade |
| POST | `/api/browser/session/start` | cria/reutiliza o Chromium da sala |
| POST | `/api/browser/session/navigate` | navegação autorizada com SSRF guard |
| POST | `/api/browser/session/close` | encerra e limpa o perfil temporário |
| GET | `/api/browser/session/token` | token LiveKit somente-assinante |
| GET/POST/DELETE | `/api/browser/favorites` | favoritos locais |
| GET/POST/PATCH/DELETE | `/api/dashboard/browser/entries` | CRUD administrativo |
| POST | `/api/dashboard/browser/test` | teste HTTP seguro de um link |
| POST | `/api/dashboard/browser/open-now` | abre URL em uma sala ativa |
| GET | `/api/dashboard/browser/rooms` | supervisão de salas |
| GET | `/api/dashboard/browser/debug/{room}` | console sanitizado e métricas do shield |

## Eventos WebSocket

BrowserMode: `ROOM_JOIN`, `ROOM_LEAVE`, `CONTROL_REQUEST`, `CONTROL_GRANTED`, `CONTROL_REVOKED`, `MOUSE_MOVE`, `MOUSE_CLICK`, `MOUSE_SCROLL`, `KEY_DOWN`, `KEY_UP`, `TEXT_INPUT`, `NAVIGATE`, `BACK`, `FORWARD`, `RELOAD`, `HOME`, `FOCUS`, `PRIVACY_ON`, `PRIVACY_OFF`, `SESSION_LOCK`, `BROWSER_ERROR` e `BROWSER_CLOSED`.

DirectPlaybackMode preserva `PLAYER_PLAY`, `PLAYER_PAUSE`, `PLAYER_SEEK`, `PLAYER_SYNC`, `MEDIA_CHANGE`, `EPISODE_CHANGE`, `HOST_CHANGE`, `REQUEST_CONTROL` e `GRANT_CONTROL`.

O servidor grava a posição e o instante da última mudança. Ao enviar um snapshot, calcula a posição corrente com timestamp e velocidade. Clientes corrigem divergências maiores que 2,5 segundos. Eventos de controle são rejeitados para participantes sem permissão.

## Testes e build

```bash
pytest
npm test
npm run build
```

O teste real do Chromium requer `python -m playwright install chromium`. Em Linux visual, também são necessários Xvfb e PulseAudio; para transmissão, GStreamer com `ximagesrc`, `pulsesrc`, H.264, AAC e sink RTMP. `/debug/browser` nunca mostra cookies, senhas, tokens, headers `Authorization` ou valores de formulários.

## Segurança e conteúdo

- Segredos permanecem apenas no backend e em variáveis de ambiente.
- O OAuth do Discord gera uma sessão própria assinada; o token OAuth não é persistido no navegador além da autenticação da Activity.
- Interações do bot exigem assinatura Ed25519 válida.
- URLs do PlenoFlu são construídas internamente a partir de parâmetros estritamente validados.
- O catálogo local usa Blender Open Movies; consulte os créditos/licenças dos projetos antes de redistribuir qualquer arquivo.
