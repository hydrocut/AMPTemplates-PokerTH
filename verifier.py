# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de Wesnoth, TarotClub, Freeciv).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp ne référence que des fichiers présents, le port principal existe et arrive au
   lanceur, le bloc Console.* / Limits.* est complet, arrêt par SIGTERM ;
3. chaque réglage exposé dans AMP est écrit une fois dans scripts/AMP_reglages-pokerth.txt
   (rendu par AMP en reglages-pokerth.txt) ET lu par le lanceur, et inversement ;
4. aller-retour réel : on rend le modèle comme AMP (remplacement brut), on fait tourner le
   vrai lanceur (bash, serveur et setpriv factices qui notent leurs arguments), et on relit
   le config.xml produit avec un vrai lecteur XML : valeur vide, espaces, accents,
   guillemets, &, <, >, apostrophe, adresses IP invalides, webhook invalide, niveau inconnu ;
5. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest,
   fins de ligne LF, `bash -n` ;
6. l'installeur : dernière version publiée, contrôle de la version de la source, adaptation
   CMake vérifiée, code du jeu non modifié, sans-daemon.so, avatars, garde mémoire ;
7. les regex de console reconnaissent les vraies lignes du serveur (relevées le 10 oct. 2026
   dans un conteneur jetable cubecoders/ampbase:debian) et pas les autres.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'pokerth'
MODELE = 'scripts/AMP_reglages-pokerth.txt'
LANCEUR = 'scripts/lancer-pokerth.sh'
INSTALLEUR = 'scripts/installer-pokerth.sh'
soucis = []


def lire(nom, binaire=False):
    chemin = os.path.join(ICI, nom)
    if binaire:
        with open(chemin, 'rb') as f:
            return f.read()
    with io.open(chemin, encoding='utf-8') as f:
        return f.read()


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...). (?!...) est commun aux deux.
    return re.compile(re.sub(r'\(\?<(?=[A-Za-z])', '(?P<', motif))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        print('ok   %-26s JSON valide' % nom)
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
refs = {p['Ref'] for p in ports}
if cles.get('App.PrimaryApplicationPortRef') not in refs:
    soucis.append('PrimaryApplicationPortRef ne correspond à aucun port')
cmd = cles.get('App.CommandLineArgs', '')
if cmd != '"{{$FullBaseDir}}lancer-pokerth.sh" {{$%s}}' % cles.get('App.PrimaryApplicationPortRef'):
    soucis.append('ligne de commande inattendue : %s' % cmd)
if len(ports) != 1 or ports[0]['Protocol'] != 'TCP' or ports[0]['Port'] != 7234:
    soucis.append('un seul port attendu : 7234 en TCP')
print('ok   ports                      %s' % ', '.join('%s %s/%s' % (p['Ref'], p['Port'], p['Protocol']) for p in ports))
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex', 'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex', 'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex', 'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex', 'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart', 'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
else:
    print('ok   kvp complet                les %d clés Console/Limits sont là' % len(ATTENDUES))
if cles.get('App.ApplicationReadyMode') != 'RegexMatch' or not cles.get('Console.AppReadyRegex'):
    soucis.append('RegexMatch avec une AppReadyRegex attendue (sinon l’instance n’est jamais prête)')
if cles.get('App.ExitMethod') != 'SIGTERM':
    soucis.append('App.ExitMethod doit être SIGTERM : le serveur s’arrête proprement sur SIGTERM')
if cles.get('App.HasWriteableConsole') != 'False':
    soucis.append('le serveur dédié PokerTH n’a pas de commandes de console : HasWriteableConsole=False')
if cles.get('Meta.URL') != data['manifest.json']['url']:
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')
if cles.get('Meta.SpecificDockerImage') != 'cubecoders/ampbase:debian' or cles.get('Meta.ContainerPolicy') != 'Required':
    soucis.append('conteneur cubecoders/ampbase:debian obligatoire (compilation à l’Update)')
paquets = json.loads(cles.get('Meta.ExtraContainerPackages', '[]'))
for p in ('g++', 'gcc', 'make', 'cmake', 'qt6-base-dev', 'libboost-iostreams-dev', 'libboost-random-dev',
          'libboost-thread-dev', 'libboost-filesystem-dev', 'libboost-program-options-dev',
          'protobuf-compiler', 'libprotobuf-dev', 'libssl-dev', 'curl', 'ca-certificates'):
    if p not in paquets:
        soucis.append('paquet %s absent de ExtraContainerPackages' % p)
for p in paquets:
    if re.search(r'declarative|multimedia|svg|websockets|qt6-tools', p):
        soucis.append('paquet %s inutile au serveur (bibliothèque des jeux)' % p)

# ── 3. réglages ↔ modèle ↔ lanceur ───────────────────────────────────────────
modele = lire(MODELE)
lanceur = lire(LANCEUR)
dans_modele = re.findall(r'\{\{([A-Za-z0-9_]+)\}\}', modele)
params = {}
for c in config:
    p = c.get('ParamFieldName')
    if p in params:
        soucis.append('réglage en double : %s' % p)
    params[p] = c
    if c['FieldName'] != p:
        soucis.append('%s : FieldName et ParamFieldName différents' % p)
    if dans_modele.count(p) != 1:
        soucis.append('{{%s}} doit apparaître une fois dans %s' % (p, MODELE))
    if not re.search(r'^%s=\{\{%s\}\}$' % (p, p), modele, re.M):
        soucis.append('%s doit s’écrire %s={{%s}} seul sur sa ligne' % (p, p, p))
    if not re.search(r'^\s+%s=\*\)' % p, lanceur, re.M):
        soucis.append('le lanceur ne lit pas %s' % p)
    if c['InputType'] == 'enum' and str(c.get('DefaultValue')) not in c.get('EnumValues', {}):
        soucis.append('%s : valeur par défaut absente des choix' % p)
orphelins = set(dans_modele) - set(params)
if orphelins:
    soucis.append('{{...}} sans réglage dans AMP : %s' % ', '.join(sorted(orphelins)))
lus = set(re.findall(r'^\s+([a-z_]+)=\*\)', lanceur, re.M))
if lus - set(params):
    soucis.append('le lanceur lit des clés que AMP n’écrit pas : %s' % ', '.join(sorted(lus - set(params))))
for l in modele.splitlines():
    if l.startswith('#') and '{{' in l:
        soucis.append('{{ dans un commentaire du modèle : AMP le remplacerait')
meta = data[NOM + 'metaconfig.json'][0]
racine = cles['App.RootDir'].strip('./').strip('/')
if meta.get('ConfigType') != 'template' or meta.get('ConfigFileTemplate') != racine + '/AMP_reglages-pokerth.txt':
    soucis.append('metaconfig : ConfigFileTemplate devrait être %s/AMP_reglages-pokerth.txt' % racine)
if meta.get('ConfigFile') != 'reglages-pokerth.txt' or 'REGLAGES=reglages-pokerth.txt' not in lanceur:
    soucis.append('le fichier rendu par AMP (ConfigFile) n’est pas celui que lit le lanceur')
if set(params['niveau_journal']['EnumValues']) != {'1', '2'}:
    soucis.append('niveau du journal : 1 et 2 seulement (0 n’écrit plus les arrivées des joueurs)')
for p in ('mot_de_passe', 'webhook_discord'):
    if params[p]['InputType'] != 'password' or params[p]['DefaultValue'] != '':
        soucis.append('%s : champ masqué (password) et vide par défaut attendu' % p)
print('ok   correspondance             %d réglages : AMP -> %s -> lanceur' % (len(params), MODELE))


# ── 4. aller-retour réel avec le lanceur ─────────────────────────────────────
def rendre(valeurs):
    t = modele
    for p, v in valeurs.items():
        t = t.replace('{{%s}}' % p, v)
    return t


bash = shutil.which('bash')
defauts = {p: str(c.get('DefaultValue', '')) for p, c in params.items()}
WEBHOOK = 'https://discord.com/api/webhooks/1234567890/AbC_dEf-123'
ESSAIS = [
    # (valeurs changées, attendu dans config.xml, niveau de journal attendu)
    ({}, {'ServerPassword': '', 'ServerBruteForceProtectionExempt': '', 'DiscordChatWebhookUrl': ''}, '1'),
    (None, {'ServerPassword': '', 'ServerBruteForceProtectionExempt': '', 'DiscordChatWebhookUrl': ''}, '1'),
    ({'mot_de_passe': '  Pass & <é> "x" \'y\' 100 %  ', 'niveau_journal': '2'},
     {'ServerPassword': 'Pass & <é> "x" \'y\' 100 %'}, '2'),
    ({'mot_de_passe': 'a\\b;c,d=e{x}#1', 'niveau_journal': '0'}, {'ServerPassword': 'a\\b;c,d=e{x}#1'}, '1'),
    ({'ip_sans_limite': 'abc;10.0.0.1, ,;2001:db8::1 *  1.2.3.4.5\t192.168.1.20', 'niveau_journal': 'x'},
     {'ServerBruteForceProtectionExempt': '10.0.0.1,2001:db8::1,192.168.1.20'}, '1'),
    ({'webhook_discord': ' %s ' % WEBHOOK}, {'DiscordChatWebhookUrl': WEBHOOK}, '1'),
    ({'webhook_discord': 'https://exemple.com/api/webhooks/1/x'}, {'DiscordChatWebhookUrl': ''}, '1'),
    ({'webhook_discord': 'https://discord.com/api/webhooks/1/x"/><ServerPassword value="pirate'},
     {'DiscordChatWebhookUrl': '', 'ServerPassword': ''}, '1'),
]
FIXES = {'ConfigRevision': '1', 'ServerPort': '7234', 'ServerUseTls': '0', 'ServerUseWebSocket': '0',
         'ServerUseSctp': '0', 'ServerBruteForceProtection': '1'}
n = 0
if bash:
    for valeurs, attendu, niveau in ESSAIS:
        dossier = tempfile.mkdtemp(prefix='tk-pokerth-')
        try:
            inst = os.path.join(dossier, 'pokerth-serveur')
            outils = os.path.join(dossier, 'outils')
            os.makedirs(inst)
            os.makedirs(outils)
            # Serveur factice : note ses arguments et son environnement, puis s'arrête.
            with open(os.path.join(inst, 'pokerth_dedicated_server'), 'w', newline='\n') as f:
                f.write('#!/bin/bash\nprintf "%s\\n" "$@" > "$(dirname "$0")/args.txt"\n'
                        'printf "%s\\n%s\\n" "$XDG_CONFIG_HOME" "$TK_LD_PRELOAD" >"$(dirname "$0")/env.txt"\nexit 0\n')
            # setpriv factice (absent sous Windows) : exécute la commande qui suit « -- ».
            with open(os.path.join(outils, 'setpriv'), 'w', newline='\n') as f:
                f.write('#!/bin/bash\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
            for b in (os.path.join(inst, 'pokerth_dedicated_server'), os.path.join(outils, 'setpriv')):
                os.chmod(b, 0o755)
            open(os.path.join(inst, 'sans-daemon.so'), 'w').close()
            with open(os.path.join(inst, '.version'), 'w', newline='\n') as f:
                f.write('v2.1.10 teamkit-1\n')
            # Copie du lanceur où LD_PRELOAD devient TK_LD_PRELOAD : sous Windows (Git Bash),
            # précharger un faux sans-daemon.so ferait planter tous les programmes lancés.
            with io.open(os.path.join(dossier, 'lancer-pokerth.sh'), 'w', encoding='utf-8', newline='\n') as f:
                f.write(lanceur.replace(' LD_PRELOAD=', ' TK_LD_PRELOAD='))
            if valeurs is not None:
                vals = dict(defauts)
                vals.update(valeurs)
                with io.open(os.path.join(dossier, 'reglages-pokerth.txt'), 'w', encoding='utf-8', newline='\n') as f:
                    f.write(rendre(vals))
            env = dict(os.environ)
            env['PATH'] = outils + os.pathsep + env.get('PATH', '')
            r = subprocess.run([bash, os.path.join(dossier, 'lancer-pokerth.sh'), '7234'],
                               capture_output=True, timeout=60, env=env)
            sortie = r.stdout.decode('utf-8', 'replace')
            racine_xml = ET.parse(os.path.join(dossier, 'donnees', '.pokerth', 'config.xml')).getroot()
            conf = {e.tag: e.get('value') for e in racine_xml.find('Configuration')}
            n += 1
            for cle, v in list(FIXES.items()) + list(attendu.items()):
                if conf.get(cle) != v:
                    soucis.append('aller-retour %r : %s = %r au lieu de %r' % (valeurs, cle, conf.get(cle), v))
            if not conf.get('LogDir', '').endswith('/donnees/journaux/') or not conf.get('CacheDir', '').endswith('/donnees/avatars/'):
                soucis.append('aller-retour %r : LogDir/CacheDir inattendus : %r' % (valeurs, conf))
            args = io.open(os.path.join(inst, 'args.txt'), encoding='utf-8').read().split('\n')
            if args[:4] != ['--log-level', niveau, '--pid-file', args[3]] or not args[3].endswith('/donnees/journaux/pokerth.pid'):
                soucis.append('aller-retour %r : arguments du serveur %r' % (valeurs, args))
            if '--readonly-config' in args:
                soucis.append('--readonly-config : le serveur ne lirait plus du tout config.xml')
            env_srv = io.open(os.path.join(inst, 'env.txt'), encoding='utf-8').read().split('\n')
            if not env_srv[0].endswith('/donnees') or not env_srv[1].endswith('/pokerth-serveur/sans-daemon.so'):
                soucis.append('aller-retour %r : XDG_CONFIG_HOME / LD_PRELOAD inattendus : %r' % (valeurs, env_srv))
            if WEBHOOK in sortie or 'Pass &' in sortie:
                soucis.append('aller-retour %r : un secret apparaît dans la console' % (valeurs,))
        except Exception as e:
            soucis.append('aller-retour %r : %s' % (valeurs, e))
        finally:
            shutil.rmtree(dossier, ignore_errors=True)
    print('ok   aller-retour réel          %d rendus AMP -> lanceur -> config.xml relu par un lecteur XML' % n)
else:
    print('--   aller-retour réel          pas de bash ici, non vérifié')

# ── 5. fichiers téléchargés à l'Update, scripts ──────────────────────────────
depot = data['manifest.json']['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
for e in fetch:
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu:
        soucis.append('URL inattendue pour %s : %s' % (e['UpdateSourceArgs'], e['UpdateSourceData']))
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du dépôt' % e['UpdateSourceArgs'])
    else:
        print('ok   téléchargé à l’Update      scripts/%s' % e['UpdateSourceArgs'])
if {e['UpdateSourceArgs'] for e in fetch} != {'AMP_reglages-pokerth.txt', 'lancer-pokerth.sh', 'installer-pokerth.sh'}:
    soucis.append('l’Update doit déposer les deux scripts et le modèle des réglages')
dernier = updates[-1]
if dernier['UpdateSource'] != 'Executable' or 'installer-pokerth.sh' not in dernier['UpdateSourceArgs']:
    soucis.append('la dernière étape de l’Update doit lancer installer-pokerth.sh')
for nom in (LANCEUR, INSTALLEUR, MODELE):
    if b'\r' in lire(nom, binaire=True):
        soucis.append('%s : fins de ligne Windows (CRLF)' % nom)
for nom in (LANCEUR, INSTALLEUR):
    if '{{' in lire(nom):
        soucis.append('%s contient {{ : AMP pourrait le remplacer' % nom)
    if bash:
        r = subprocess.run([bash, '-n', os.path.join(ICI, nom)], capture_output=True, text=True)
        if r.returncode:
            soucis.append('bash -n %s : %s' % (nom, r.stderr.strip()))
        else:
            print('ok   bash -n                    %s' % nom)
for besoin, pourquoi in [
    ("trap '' PIPE", 'un joueur qui ferme son jeu ne doit pas tuer le serveur (SIGPIPE)'),
    ('LD_PRELOAD="$INST/sans-daemon.so"', 'le serveur doit rester au premier plan'),
    ('setpriv --pdeathsig TERM -- "$SRV"', 'le serveur ne doit pas survivre au lanceur'),
    ('setpriv --pdeathsig TERM -- tail -n +1 -F --pid="$PID"', 'recopie du journal dans la console'),
    ('mots de passe masques par TeamKit', 'le serveur écrit le bon mot de passe sur un mauvais essai'),
    ('XDG_CONFIG_HOME="$DONNEES"', 'config.xml dans le dossier de l’instance'),
    ('<ConfigRevision value="1"/>', 'le serveur complète le fichier en gardant nos valeurs'),
    ('echo "TeamKit : serveur PokerTH $VERSION pret, il ecoute sur le port $PORT."', 'ligne prêt'),
    ('-mtime +30 -delete', 'purge des avatars envoyés'),
]:
    if besoin not in lanceur:
        soucis.append('lanceur : %s (%s)' % (besoin, pourquoi))

# ── 6. installeur ────────────────────────────────────────────────────────────
inst = lire(INSTALLEUR)
for besoin, pourquoi in [
    ('https://api.github.com/repos/$DEPOT/releases/latest', 'dernière version publiée'),
    ('^v[0-9]+(\\.[0-9]+){1,3}$', 'format du tag contrôlé'),
    ('https://codeload.github.com/$DEPOT/tar.gz/refs/tags/$TAG', 'source du tag'),
    ('POKERTH_BETA_RELEASE_STRING[[:space:]]*\\"$VERSION\\"', 'la source est bien celle de la version'),
    ('COMPONENTS Core Sql Xml Network REQUIRED) # TeamKit', 'modules Qt du serveur seulement'),
    ("grep -c '^# TeamKit : jeu non compile' CMakeLists.txt", 'adaptation CMake vérifiée'),
    ('--target pokerth_dedicated_server', 'seule la cible serveur'),
    ('int daemon(int nochdir, int noclose)', 'sans-daemon.so'),
    ('cp -r data/gfx/avatars', 'avatars par défaut (sinon « Missing files »)'),
    ('/sys/fs/cgroup/memory.max', 'garde mémoire'),
    ('mv "$INST.nouveau" "$INST"', 'remplacement en une fois'),
]:
    if besoin not in inst:
        soucis.append('installeur : %s absent (%s)' % (besoin, pourquoi))
# Le code du jeu (AGPL-3.0) n'est jamais modifié : seul CMakeLists.txt l'est.
for m in re.finditer(r'sed -i[^\n]*?\s(\S+)$', inst, re.M):
    if m.group(1) != 'CMakeLists.txt':
        soucis.append('installeur : %s est modifié (seul CMakeLists.txt peut l’être)' % m.group(1))
if re.search(r'\bpatch\b|> *src/|\.cpp\.tk|awk .*src/', inst):
    soucis.append('installeur : le code du jeu ne doit pas être modifié (AGPL-3.0)')
print('ok   installeur                 dernière version, source contrôlée, code du jeu intact')

# ── 7. regex de console sur de vraies lignes (conteneur jetable, 10/10/2026) ──
ESSAIS = [
    ('Console.AppReadyRegex', 'TeamKit : serveur PokerTH 2.1.10 pret, il ecoute sur le port 7234.', {}),
    ('Console.UserJoinRegex', '2026-Oct-10 19:28:52 MSG: Player "test1" (id:3, dbId:0) connected from 127.0.0.1 - session #3 - client: QtWidget 2.1.9.', {'username': 'test1'}),
    ('Console.UserJoinRegex', '2026-Oct-10 19:28:52 MSG: Player "Kévin "le roi" du flop" (id:12, dbId:0) connected from 203.0.113.7 - session #40 - client: QML/Windows 2.1.10.', {'username': 'Kévin "le roi" du flop'}),
    ('Console.UserLeaveRegex', '2026-Oct-10 19:28:54 MSG: Closing session #3 player="test1" ip=127.0.0.1.', {'username': 'test1'}),
    ('Console.UserLeaveRegex', '2026-Oct-10 19:34:26 MSG: Closing session #8 player="test36" ip=127.0.0.1 game=1.', {'username': 'test36'}),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:28:54 ERR: Session 3 (127.0.0.1 player="test1") - Connection closed: system:104 (unsent: 0 bytes)', {}),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:34:26 ERR: Session 8 (127.0.0.1 player="test36") - Connection closed: asio.misc:2 (unsent: 120 bytes)', {}),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:28:54 ERR: Session 4 - HandleWrite error: Connection reset by peer (unsent: 12 bytes)', {}),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:34:00 ERR: DB create game failed for request 1', {}),
]
for cle, ligne, attendu in ESSAIS:
    m = py(cles.get(cle) or '^$').search(ligne)
    if not m or any(m.group(k) != v for k, v in attendu.items()):
        soucis.append('%s ne reconnaît pas : %r' % (cle, ligne))
PIEGES = [
    ('Console.UserLeaveRegex', '2026-Oct-10 19:28:53 MSG: Closing session #6 player="(unknown)" ip=127.0.0.1.'),
    ('Console.UserJoinRegex', '2026-Oct-10 19:28:54 MSG: Closing session #3 player="test1" ip=127.0.0.1.'),
    ('Console.UserLeaveRegex', '2026-Oct-10 19:28:52 MSG: Player "test1" (id:3, dbId:0) connected from 127.0.0.1 - session #3 - client: QtWidget 2.1.9.'),
    ('Console.UserJoinRegex', '2026-Oct-10 19:30:46 MSG: Invalid server password attempt from 127.0.0.1 (mots de passe masques par TeamKit).'),
    ('Console.AppReadyRegex', '2026-Oct-10 19:26:37 MSG: Starting PokerTH dedicated server. Availability: IPv6 1, SCTP 1, Dual Stack 1.'),
    ('Console.AppReadyRegex', "TeamKit : ATTENTION, le port 7234 n'ecoute toujours pas apres 30 secondes."),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:34:26 ERR: Game 1 - Engine exception in TimerLoop: bad things'),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:34:26 ERR: TLS (websocket) setup failed: no file'),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:34:26 ERR: Session 5 (127.0.0.1 player="x") - Connection closed: system:110 (unsent: 9000 bytes)'),
    ('Console.ThrowawayMessageRegex', '2026-Oct-10 19:28:53 MSG: Login rate limit reached by 127.0.0.1 - further inits blocked for now.'),
]
for cle, ligne in PIEGES:
    if py(cles[cle]).search(ligne):
        soucis.append('%s attrape une ligne qui n’est pas pour lui : %r' % (cle, ligne))
print('ok   console                    %d lignes réelles, %d pièges' % (len(ESSAIS), len(PIEGES)))

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
