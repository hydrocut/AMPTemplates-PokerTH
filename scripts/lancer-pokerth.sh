#!/bin/bash
# lancer-pokerth.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Argument : <port du jeu>
#
# 1. lit les reglages ecrits par AMP (reglages-pokerth.txt) et ecrit un config.xml
#    reduit dans donnees/.pokerth/ (valeurs echappees pour le XML) ; au demarrage, le
#    serveur le complete lui-meme avec toutes ses autres options par defaut ;
# 2. lance le serveur dedie PokerTH au premier plan (sans-daemon.so, voir l'installeur) ;
# 3. recopie son journal (il n'ecrit que dans un fichier) dans la console d'AMP ;
# 4. ecrit une ligne « pret » pour AMP des que le port ecoute (le serveur n'en ecrit pas) ;
# 5. a l'arret demande par AMP (SIGTERM), arrete proprement le serveur.
cd "$(dirname "$0")" || exit 1
INST="$PWD/pokerth-serveur"
SRV="$INST/pokerth_dedicated_server"
PORT="${1:-7234}"
REGLAGES=reglages-pokerth.txt
DONNEES="$PWD/donnees"
JOURNAUX="$DONNEES/journaux"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

if [ ! -x "$SRV" ] || [ ! -f "$INST/sans-daemon.so" ]; then
  echo "ERREUR : le serveur PokerTH n'est pas installe dans ce dossier. Lance Update dans AMP."
  exit 1
fi
VERSION=$(cut -d' ' -f1 "$INST/.version" 2>/dev/null)
VERSION="${VERSION#v}"
if ! [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "ERREUR : port du jeu invalide : $PORT"
  exit 1
fi

# --- Reglages (une ligne cle=valeur par reglage, rendue par AMP) ---
MOT_DE_PASSE=""
IP_SANS_LIMITE=""
NIVEAU_JOURNAL=1
WEBHOOK_DISCORD=""
if [ -f "$REGLAGES" ]; then
  while IFS= read -r ligne || [ -n "$ligne" ]; do
    ligne="${ligne%$'\r'}"
    case "$ligne" in
      mot_de_passe=*)    MOT_DE_PASSE="${ligne#*=}" ;;
      ip_sans_limite=*)  IP_SANS_LIMITE="${ligne#*=}" ;;
      niveau_journal=*)  NIVEAU_JOURNAL="${ligne#*=}" ;;
      webhook_discord=*) WEBHOOK_DISCORD="${ligne#*=}" ;;
    esac
  done < "$REGLAGES"
else
  echo "TeamKit : $REGLAGES absent (AMP l'ecrit au demarrage), reglages par defaut."
fi

# Niveau 0 du serveur : il n'ecrit plus rien, pas meme les arrivees et departs des
# joueurs dont AMP a besoin. Seuls 1 (normal) et 2 (detaille) sont proposes.
case "$NIVEAU_JOURNAL" in
  1|2) ;;
  *) echo "TeamKit : niveau de journal « $NIVEAU_JOURNAL » inconnu, niveau 1 (normal)."; NIVEAU_JOURNAL=1 ;;
esac
# Mot de passe : sans caracteres de controle ni espaces au debut et a la fin.
MOT_DE_PASSE=$(printf '%s' "$MOT_DE_PASSE" | tr -d '\000-\037\177' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
# Adresses IP sans limite de connexions : separees par des virgules (espaces et
# points-virgules acceptes aussi) ; tout ce qui n'est pas une adresse IP est ignore.
read -r -a LISTE_IP <<< "$(printf '%s' "$IP_SANS_LIMITE" | tr -d '\000-\010\012-\037\177' | tr ',;\t' '   ')"
IP_SANS_LIMITE=""
for ip in "${LISTE_IP[@]}"; do
  if [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { [[ "$ip" == *:* ]] && [[ "$ip" =~ ^[0-9A-Fa-f:.]{2,45}$ ]]; }; then
    IP_SANS_LIMITE="${IP_SANS_LIMITE:+$IP_SANS_LIMITE,}$ip"
  else
    echo "TeamKit : « $ip » n'est pas une adresse IP : ignoree (Adresses IP sans limite de connexions)."
  fi
done
# Webhook Discord : seule une adresse de webhook Discord est acceptee (jamais affichee).
WEBHOOK_DISCORD=$(printf '%s' "$WEBHOOK_DISCORD" | tr -d '\000-\040\177')
if [ -n "$WEBHOOK_DISCORD" ] && ! [[ "$WEBHOOK_DISCORD" =~ ^https://((ptb|canary)\.)?discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$ ]]; then
  echo "TeamKit : l'adresse du webhook Discord n'est pas une adresse https://discord.com/api/webhooks/... : ignoree."
  WEBHOOK_DISCORD=""
fi

# Echappement XML (valeur d'attribut entre guillemets droits).
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"; }

mkdir -p "$DONNEES/.pokerth" "$JOURNAUX" "$DONNEES/avatars"
CONFIG="$DONNEES/.pokerth/config.xml"
# Revision 1 : le serveur voit un fichier « ancien », garde nos valeurs et ajoute toutes
# les autres options avec leurs valeurs par defaut (ConfigFile::updateConfig). Le fichier
# est reecrit a chaque demarrage : l'onglet Configuration d'AMP fait foi.
# (--readonly-config n'est pas utilisable : avec lui, le serveur ne lit plus du tout le
# fichier et prend toutes les valeurs par defaut, voir src/config/configfile.cpp.)
umask 077
{
  printf '<?xml version="1.0" encoding="UTF-8"?>\n<PokerTH>\n <Configuration>\n'
  printf '  <ConfigRevision value="1"/>\n'
  printf '  <ServerPort value="%d"/>\n' "$PORT"
  printf '  <ServerPassword value="%s"/>\n' "$(xml "$MOT_DE_PASSE")"
  # Connexion directe par adresse IP depuis le jeu : jamais chiffree, donc pas de TLS.
  printf '  <ServerUseTls value="0"/>\n'
  # Pas de WebSocket : aucun client navigateur ne peut le joindre sans domaine + certificat.
  printf '  <ServerUseWebSocket value="0"/>\n'
  printf '  <ServerUseSctp value="0"/>\n'
  printf '  <ServerBruteForceProtection value="1"/>\n'
  printf '  <ServerBruteForceProtectionExempt value="%s"/>\n' "$(xml "$IP_SANS_LIMITE")"
  printf '  <DiscordChatWebhookUrl value="%s"/>\n' "$(xml "$WEBHOOK_DISCORD")"
  printf '  <LogDir value="%s/"/>\n' "$(xml "$JOURNAUX")"
  printf '  <CacheDir value="%s/"/>\n' "$(xml "$DONNEES/avatars")"
  printf ' </Configuration>\n</PokerTH>\n'
} > "$CONFIG"
umask 022
# Avatars envoyes par les joueurs : effaces apres 30 jours (le serveur oublie aussi les siens).
find "$DONNEES/avatars" -type f -mtime +30 -delete 2>/dev/null
# Journal du serveur : l'ancien est garde une fois (server_messages.log.1).
JOURNAL="$JOURNAUX/server_messages.log"
[ -s "$JOURNAL" ] && mv -f "$JOURNAL" "$JOURNAL.1"
: > "$JOURNAL"

if [ -n "$MOT_DE_PASSE" ]; then
  echo "TeamKit : serveur protege par un mot de passe."
else
  echo "TeamKit : serveur ouvert a tous (pas de mot de passe)."
fi
[ -n "$IP_SANS_LIMITE" ] && echo "TeamKit : pas de limite de connexions pour : $IP_SANS_LIMITE"
[ -n "$WEBHOOK_DISCORD" ] && echo "TeamKit : le salon de discussion est recopie dans Discord (webhook)."

# Un signal ignore l'est aussi par le serveur lance ensuite : un joueur qui ferme son jeu
# au mauvais moment ne doit pas le tuer (SIGPIPE).
trap '' PIPE
# LD_PRELOAD : daemon() ne detache plus le serveur, il reste l'enfant de ce script.
# --pdeathsig : si ce script est tue net (SIGKILL), le serveur s'arrete aussi.
XDG_CONFIG_HOME="$DONNEES" LD_PRELOAD="$INST/sans-daemon.so" \
  setpriv --pdeathsig TERM -- "$SRV" --log-level "$NIVEAU_JOURNAL" --pid-file "$JOURNAUX/pokerth.pid" &
PID=$!
# Le serveur n'ecrit que dans son fichier : on le recopie dans la console d'AMP.
# Sur un mauvais mot de passe, il ecrit le mot de passe tape ET le bon : masques ici
# (le fichier donnees/journaux/server_messages.log les garde, il n'est lisible que par AMP).
# --pdeathsig ici aussi : si ce script est tue net, la recopie s'arrete avec lui (sinon
# tail attendrait la fin d'un serveur reste a l'etat zombie).
setpriv --pdeathsig TERM -- tail -n +1 -F --pid="$PID" "$JOURNAL" 2>/dev/null \
  | setpriv --pdeathsig TERM -- sed -u -E 's/^(.* MSG: Invalid server password attempt from [^ ]+) .*$/\1 (mots de passe masques par TeamKit)./' &
TAIL=$!

ARRET=0
arreter() {
  trap - TERM INT
  ARRET=1
  echo "TeamKit : arret demande, fermeture du serveur."
  kill -TERM "$PID" 2>/dev/null
}
trap arreter TERM INT

# Port en ecoute (LISTEN = 0A dans /proc/net/tcp*) ?
motif=$(printf ':%04X$' "$PORT")
ecoute() {
  local t
  for t in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$t" ] && awk -v p="$motif" '$2 ~ p && $4 == "0A" { t = 1 } END { exit !t }' "$t" && return 0
  done
  return 1
}
PRET=0
for _ in $(seq 1 150); do
  kill -0 "$PID" 2>/dev/null || break
  if ecoute; then PRET=1; break; fi
  sleep 0.2
done
if [ "$PRET" = 1 ] && [ "$ARRET" = 0 ]; then
  echo "TeamKit : serveur PokerTH $VERSION pret, il ecoute sur le port $PORT."
elif [ "$ARRET" = 0 ] && kill -0 "$PID" 2>/dev/null; then
  echo "TeamKit : ATTENTION, le port $PORT n'ecoute toujours pas apres 30 secondes."
fi

# Le SIGTERM d'AMP interrompt ce « wait » : on attend une seconde fois le vrai code.
wait "$PID"
CODE=$?
if [ "$ARRET" = 1 ]; then
  wait "$PID"
  CODE=$?
fi
# tail (--pid) recopie les dernieres lignes et s'arrete de lui-meme dans la seconde.
wait "$TAIL" 2>/dev/null
if [ "$ARRET" = 1 ] && { [ "$CODE" = 143 ] || [ "$CODE" = 0 ]; }; then
  echo "TeamKit : serveur arrete."
  exit 0
fi
if [ "$ARRET" = 0 ]; then
  echo "TeamKit : le serveur s'est arrete tout seul (code $CODE). Journal : donnees/journaux/."
fi
exit "$CODE"
