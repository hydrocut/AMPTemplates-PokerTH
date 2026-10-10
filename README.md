# AMPTemplates-PokerTH — PokerTH dedicated server for AMP

**AMP Generic Module** template for **`pokerth_dedicated_server`**, the dedicated server of
**PokerTH**, a free (AGPL-3.0) Texas Hold'em poker game — virtual chips only, no real money.
Written for TeamKit, a free French game host, on 10 Oct 2026. CubeCoders ships no PokerTH
template (checked in `CubeCoders/AMPTemplates`, 10 Oct 2026).

> Résumé en français à la fin du fichier.

## Why it is compiled at each Update

None of the published PokerTH packages contains the dedicated server: the 2.1.10 `.deb`
(`pokerth_2.1.10_amd64.deb`, 155 MB) and the Linux `.zip` only ship the two game clients
(checked by listing both archives, 10 Oct 2026; the `.deb` is built by
`.github/workflows/deb.yml`, which only builds the client targets). So the server is built from
source, like the upstream documentation describes (`docs/server_setup_howto.txt`, chapter 2).

The server must also follow the game releases: it only accepts the current and the previous
release of each client (`MIN_BUILD_ID_*` in `src/game_defs.h`), and PokerTH releases every one to
three weeks (2.1.6 on 5 Aug 2026 … 2.1.10 on 5 Oct 2026). So **each Update builds the latest
GitHub release** (`releases/latest`), and does nothing if that version is already installed.

## How it is built (`scripts/installer-pokerth.sh`)

1. asks `api.github.com` for the latest release tag (`v2.1.10` today); if GitHub does not answer
   and a server is already installed, it keeps it;
2. downloads the source archive of that tag from `codeload.github.com`, extracts it without the
   game assets (images, sounds, fonts, translations, client code) and checks that
   `src/game_defs.h` really says that version;
3. reduces the Qt modules requested by `CMakeLists.txt` to the four the server links
   (Core, Network, Xml, Sql) and skips the two client sub-directories: the top-level CMake file
   otherwise requires every client module (Quick, Multimedia, Svg…) even for a server-only build.
   The edit is checked; if a future release changes those lines the Update stops with a clear
   message. **The game code itself is not modified** (AGPL-3.0, section 13);
4. `cmake --build build --target pokerth_dedicated_server` with Debian 13 packages
   (Qt 6.8, Boost 1.83, Protobuf 3.21, GCC 14), 2 jobs, or 1 job when the container has less
   than 2 GB of memory;
5. builds `sans-daemon.so`, a two-line `daemon()` that does nothing (see below);
6. installs to `pokerth-serveur/` (3.9 MB: binary, `sans-daemon.so`, default avatars, licence).

Measured in disposable `cubecoders/ampbase:debian` containers (10 Oct 2026), as a non-root user:

| Container | Result |
|---|---|
| 2 GB, 2 CPU | 2 min 13 s |
| 1.5 GB, 1 CPU, no swap | 4 min 09 s |
| 1 GB, 1 CPU, no swap | **fails**: the compiler is OOM-killed (one file needs ~1.2 GB) |

**The instance needs 1.5 GB of memory during the Update.** In game the server uses about 25 MB.

## How the server is started (`scripts/lancer-pokerth.sh`)

`/bin/bash lancer-pokerth.sh <port>`:

1. reads `reglages-pokerth.txt` (rendered by AMP from `scripts/AMP_reglages-pokerth.txt`, one
   `key=value` per line) and writes a **reduced** `donnees/.pokerth/config.xml` (XML-escaped values,
   `ConfigRevision` 1). On start the server treats it as an old file: it keeps these values and
   appends every other option with its default (`ConfigFile::updateConfig`). The file is rewritten
   at each start, so AMP's Configuration tab is the only source of truth.
   `--readonly-config` is **not** usable: with it, the 2.1.10 server does not read `config.xml` at
   all and runs on defaults (`src/config/configfile.cpp`, `if (!noWriteAccess)`).
2. starts the server with `XDG_CONFIG_HOME=donnees` (so `~/.pokerth` is inside the instance) and
   `LD_PRELOAD=sans-daemon.so`: a Release build calls `daemon(0, 0)` and would detach from AMP;
   with the preloaded no-op it stays in the foreground, a child of the script
   (`setpriv --pdeathsig TERM`: it also stops if the script is killed);
3. the server only writes to `donnees/journaux/server_messages.log`: the script copies that file to
   AMP's console (`tail -F`), masking the passwords the server writes on a failed login
   (it logs both the typed and the expected server password). The previous log is kept as `.1`;
4. prints `TeamKit : serveur PokerTH <version> pret, il ecoute sur le port <port>.` when the port
   listens (the server prints no ready line);
5. on SIGTERM from AMP, stops the server cleanly (≈ 0.6 s, exit code 0).

**One port: 7234/TCP.** TLS is off (a direct connection by address never uses TLS), the WebSocket
port (7233, browser client) is off: see *Browser client* below.

## Settings (AMP → Configuration)

| Setting | Default | Server option |
|---|---|---|
| Mot de passe du serveur | empty (open) | `ServerPassword`: the only access control of a dedicated server |
| Adresses IP sans limite de connexions | empty | `ServerBruteForceProtectionExempt`: the login rate limit is 5 attempts per IP, then one every 30 s; only invalid entries are dropped |
| Webhook Discord du salon | empty | `DiscordChatWebhookUrl`: lobby chat mirrored to a Discord channel; only `https://discord.com/api/webhooks/…` addresses are accepted |
| Journal du serveur | Normal | `--log-level` 1 or 2. Level 0 is not offered: it also hides the join lines AMP's user list needs |

There is **no server name or welcome message** in PokerTH's server options, so nothing in French
or about TeamKit can be shown to players by the server itself.

## Player side

Players need PokerTH **2.1.x** (Windows, macOS, Linux, Android — github.com/pokerth/pokerth/releases),
the current or the previous release. In the QML client (French labels of 2.1.10):

1. *Paramètres → Pseudos/Avatars → Mon pseudo*: the nickname used on this server (there are no
   accounts: names are not reserved).
2. *Paramètres → Jeu Internet → Configuration manuelle du serveur*: *Adresse du serveur* = server
   IP, *Port du serveur* = the instance port, *Mot de passe du serveur* if one is set; **untick**
   *Utiliser TLS/SSL (connexion chiffrée)*.
3. Home screen → *Jeu Internet* → *Continuer en tant qu'invité*: the lobby opens; create a table
   (2 to 10 players) or join one.
4. To play on pokerth.net again: *Configuration automatique du serveur*.

The upstream guide also mentions *Rejoindre un jeu en réseau* (direct connection by address).
**Not tested with a real game client**: the tests used `pokerth_bot`, the headless client of the
same source tree.

### Browser client

A browser client exists: **PokerTH Web Client** (github.com/narmod/pokerth-web-client, AGPL-3.0,
played at webclient.pokerth.net). It reaches self-hosted servers only through its own Node.js
proxy, which dials an allowlist of servers; the public instance will not dial this one. Using it
would mean hosting that proxy (with HTTPS) ourselves: not part of this template.

## Tested (disposable `cubecoders/ampbase:debian` containers, 10 Oct 2026)

Build as non-root at 2 GB/2 CPU, 1.5 GB/1 CPU (OK) and 1 GB/1 CPU (OOM); second Update does
nothing; start with AMP's exact command line; `config.xml` completed by the server with our values
kept (port, password with `& < > " '` and accents, IP list, webhook, directories); wrong password
refused and masked in the console; 10 headless clients (`pokerth_bot`, unauthenticated login like
the real client on a no-auth server) connected and played hands; join/leave lines against the
regexes; SIGTERM (clean, 0.6 s) and SIGKILL of the script (server and log copy stop too); invalid
settings. RAM: server 25–27 MB with 10 players.

**Not tested**: a real PokerTH client, AMP itself (Update, settings rendering, user list), the
Discord webhook, long uptimes, the next PokerTH release.

## Files

| File | Role |
|---|---|
| `pokerth.kvp`, `pokerth*.json`, `manifest.json` | the AMP template |
| `scripts/installer-pokerth.sh` | download, check, build (Update) |
| `scripts/lancer-pokerth.sh` | start script |
| `scripts/AMP_reglages-pokerth.txt` | settings model rendered by AMP |
| `verifier.py` | pre-push checks, must print `Tout est bon.` |

The three `scripts/` files are fetched from this repository (raw.githubusercontent.com, branch
`main`) at each Update, so **the repository must be public**.

## Credits

PokerTH © the PokerTH team (Lothar May and contributors), AGPL-3.0. This repository only contains
the template; the source is downloaded from github.com/pokerth/pokerth and built unmodified.

---

## Résumé en français

Template AMP du **serveur dédié de PokerTH** (poker Texas Hold'em libre, jetons virtuels).
Aucun paquet publié ne contient le serveur : il est **compilé à chaque Update depuis la dernière
version publiée** (2.1.10 aujourd'hui), ce qui suit les nouvelles versions du jeu (le serveur
refuse les jeux plus vieux que la version précédente). Le code du jeu n'est pas modifié.
Conteneur obligatoire, **1,5 Go de mémoire pendant l'Update** (4 min sur un cœur), environ
25 Mo en jeu. Un seul port, **7234 en TCP**.

- **Réglages en français** : mot de passe du serveur, adresses IP sans limite de connexions,
  webhook Discord du salon, journal normal ou détaillé. Le serveur n'a ni nom ni message
  d'accueil : rien ne peut afficher « TeamKit » aux joueurs.
- **Joueurs** : jeu PokerTH 2.1.x → Paramètres → Jeu Internet → Configuration manuelle du
  serveur (adresse, port, mot de passe, TLS décoché) → Jeu Internet → Continuer en tant qu'invité.
  Pas de comptes ni de classement (réservés au serveur officiel).
- **Navigateur** : le client web existe (webclient.pokerth.net) mais passe par un relais qui ne
  joint que les serveurs de sa liste : pas utilisable tel quel.
- **Testé en vrai** le 10 oct. 2026 dans des conteneurs jetables avec 10 clients automatiques ;
  pas encore avec le vrai jeu ni dans AMP.
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
