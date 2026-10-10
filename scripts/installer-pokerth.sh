#!/bin/bash
# installer-pokerth.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Compile le serveur dedie PokerTH (pokerth_dedicated_server) de la DERNIERE version
# publiee sur github.com/pokerth/pokerth, depuis la source du tag de cette version.
# Argument : le dossier de l'instance (FullBaseDir cote AMP).
#
# Pourquoi compiler : aucun paquet publie (.deb, .zip, AppImage, Windows, macOS) ne
# contient le serveur dedie, seulement les jeux (verifie sur la 2.1.10, 10/10/2026).
# Pourquoi la derniere version : le serveur refuse les jeux plus anciens que la version
# precedente (MIN_BUILD_ID_* dans src/game_defs.h) ; PokerTH sort une version toutes
# les une a deux semaines. Un Update dans AMP suffit pour suivre.
#
# Le code du jeu n'est PAS modifie (licence AGPL-3.0, voir README) : seule la liste des
# modules Qt demandes par CMake est reduite a ceux du serveur, pour ne pas installer les
# bibliotheques graphiques des jeux dans le conteneur.
set -e
cd "$1"
DEPOT=pokerth/pokerth
# A changer si la facon de compiler change : force une recompilation au prochain Update.
CORRECTIF=1
ICI="$PWD"
INST="$ICI/pokerth-serveur"
TRAVAIL="$ICI/.compilation"

for outil in curl tar gzip cmake make g++ gcc strip nproc; do
  if ! command -v "$outil" >/dev/null 2>&1; then
    echo "ERREUR : l'outil $outil manque. Cette instance doit tourner en conteneur : les outils de compilation sont installes par ExtraContainerPackages."
    exit 1
  fi
done

# --- Quelle version ? La derniere publiee (releases/latest de GitHub) ---
TAG=$(curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$DEPOT/releases/latest" \
  | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/') || TAG=""
if ! [[ "$TAG" =~ ^v[0-9]+(\.[0-9]+){1,3}$ ]]; then
  if [ -x "$INST/pokerth_dedicated_server" ]; then
    echo "ATTENTION : GitHub ne repond pas (ou limite les demandes) : on garde la version installee ($(cut -d' ' -f1 "$INST/.version" 2>/dev/null)). Relance Update plus tard."
    exit 0
  fi
  echo "ERREUR : impossible de connaitre la derniere version de PokerTH (api.github.com). Relance Update dans quelques minutes."
  exit 1
fi
VERSION="${TAG#v}"
MARQUE="$TAG teamkit-$CORRECTIF"

if [ -x "$INST/pokerth_dedicated_server" ] && [ -x "$INST/sans-daemon.so" ] && [ "$(cat "$INST/.version" 2>/dev/null)" = "$MARQUE" ]; then
  echo "Le serveur PokerTH $VERSION est deja installe : rien a faire."
  exit 0
fi

rm -rf "$TRAVAIL"
mkdir -p "$TRAVAIL/source"
cd "$TRAVAIL"
echo "Telechargement de la source de PokerTH $VERSION (environ 130 Mo, github.com/$DEPOT)..."
curl -fsSL --retry 3 -o source.tar.gz "https://codeload.github.com/$DEPOT/tar.gz/refs/tags/$TAG"
# Les images, sons, polices, traductions et le code des jeux ne servent pas au serveur.
tar -xzf source.tar.gz -C source --strip-components=1 \
  --exclude='*/data/gfx/qml' --exclude='*/data/gfx/gui' --exclude='*/data/gfx/cards' \
  --exclude='*/data/sounds' --exclude='*/data/fonts' --exclude='*/data/translations' \
  --exclude='*/src/gui/qt6-qml' --exclude='*/ts' --exclude='*/preview' --exclude='*/tests' \
  --exclude='*/docker' --exclude='*/fdroid'
rm -f source.tar.gz
cd source
grep -q "POKERTH_BETA_RELEASE_STRING[[:space:]]*\"$VERSION\"" src/game_defs.h \
  || { echo "ERREUR : la source telechargee n'est pas celle de la version $VERSION (src/game_defs.h)."; exit 1; }
[ -d data/gfx/avatars/default/people ] && [ -d data/gfx/avatars/default/misc ] \
  || { echo "ERREUR : avatars par defaut absents de la source (data/gfx/avatars/default)."; exit 1; }

# --- Construction : seulement les modules Qt du serveur (Core, Network, Xml, Sql) ---
# Le CMakeLists.txt du projet demande tous les modules des jeux (Quick, Multimedia...),
# meme pour ne compiler que le serveur (docs/server_setup_howto.txt, 2.1). On retire
# ces modules et les deux dossiers des jeux ; le code compile est le meme.
sed -i -E 's/^(find_package\(Qt6 \$\{QT_MIN_VERSION\} REQUIRED COMPONENTS) .* REQUIRED\)$/\1 Core Sql Xml Network REQUIRED) # TeamKit : serveur seul/' CMakeLists.txt
sed -i -E 's|^add_subdirectory\(src/gui/(qt\|qt6-qml)\)$|# TeamKit : jeu non compile : &|' CMakeLists.txt
grep -q 'COMPONENTS Core Sql Xml Network REQUIRED) # TeamKit' CMakeLists.txt \
  && [ "$(grep -c '^# TeamKit : jeu non compile' CMakeLists.txt)" = 2 ] \
  || { echo "ERREUR : CMakeLists.txt de PokerTH $VERSION a change, adaptation TeamKit non appliquee."; exit 1; }

COEURS=$(nproc 2>/dev/null || echo 1)
[ "$COEURS" -gt 2 ] && COEURS=2
# Un fichier C++ du serveur demande jusqu'a ~700 Mo a la compilation : sous 2 Go de
# memoire pour le conteneur, un seul fichier a la fois.
LIMITE=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)
if [[ "$LIMITE" =~ ^[0-9]+$ ]] && [ "$LIMITE" -lt $((2048 * 1024 * 1024)) ]; then COEURS=1; fi
# Essais du 10/10/2026 : 1,5 Go suffit (un fichier a la fois), 1 Go non (compilateur tue,
# meme en -O1). Le serveur lui-meme n'utilise ensuite qu'environ 25 Mo.
if [[ "$LIMITE" =~ ^[0-9]+$ ]] && [ "$LIMITE" -lt $((1400 * 1024 * 1024)) ]; then
  echo "ATTENTION : ce conteneur a $((LIMITE / 1048576)) Mo de memoire ; la compilation en demande 1,5 Go et risque d'etre tuee. Monte la limite memoire de l'instance a 1,5 Go le temps de l'Update."
fi
echo "Configuration (CMake)..."
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -Wno-dev > ../cmake.log 2>&1 \
  || { tail -n 30 ../cmake.log; echo "ERREUR : la configuration CMake a echoue (journal ci-dessus)."; exit 1; }
echo "Compilation du serveur dedie PokerTH $VERSION ($COEURS a la fois, de 2 a 5 minutes)..."
cmake --build build --target pokerth_dedicated_server -j "$COEURS" -- --no-print-directory 2>&1 \
  | grep --line-buffered -E '^\[ *[0-9]+%\]|error|Error' | grep --line-buffered -v -E 'Wno-|^\[ *[0-9]+%\] (Automatic|Running|Generating)' || true
[ -x build/bin/pokerth_dedicated_server ] || { echo "ERREUR : la compilation a echoue (« Killed » ci-dessus = memoire insuffisante : 1,5 Go necessaires pendant l'Update)."; exit 1; }

# Le serveur se detache tout seul (daemon()) dans une compilation Release : AMP le perdrait.
# Plutot que de modifier son code, on lui fournit un daemon() qui ne fait rien
# (LD_PRELOAD au lancement) : il reste au premier plan, enfant du script de lancement.
cat > sans-daemon.c <<'C'
/* TeamKit : daemon() qui ne detache pas le processus (charge par LD_PRELOAD). */
int daemon(int nochdir, int noclose) { (void)nochdir; (void)noclose; return 0; }
C
gcc -O2 -shared -fPIC -o sans-daemon.so sans-daemon.c

rm -rf "$INST.nouveau"
mkdir -p "$INST.nouveau/data/gfx"
cp build/bin/pokerth_dedicated_server sans-daemon.so "$INST.nouveau/"
cp -r data/gfx/avatars "$INST.nouveau/data/gfx/"
cp COPYING "$INST.nouveau/COPYING-AGPL-3.0.txt" 2>/dev/null || true
strip "$INST.nouveau/pokerth_dedicated_server" 2>/dev/null || true
echo "$MARQUE" > "$INST.nouveau/.version"
cd "$ICI"
rm -rf "$INST"
mv "$INST.nouveau" "$INST"
rm -rf "$TRAVAIL"
echo "Serveur dedie PokerTH $VERSION installe."
