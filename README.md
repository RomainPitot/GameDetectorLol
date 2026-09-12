# GameDetectorLol

Surveille ta partie League of Legends en cours et affiche ça **en direct sur CLIMB.EUW**
(page Sélection de champion, ou Paramètres) : recherche de partie, ready check, sélection
des champions, chargement en cours, puis en jeu — plus besoin d'une notification Discord
séparée, il suffit de regarder l'app.

Le programme tourne sur ton PC et surveille l'API locale du client League of Legends (pour
la phase de jeu) et l'API locale du jeu lui-même (pour distinguer "chargement en cours" de
"en jeu réellement" — elle ne répond qu'une fois ton chargement terminé).

## Installer

1. Télécharge `GameDetectorLol-Setup.exe` depuis la [dernière release
   GitHub](../../releases/latest).
2. Double-clique. Windows affichera probablement **"Éditeur inconnu"** (SmartScreen) —
   c'est normal pour un petit outil non signé par un éditeur commercial : clique **"Plus
   d'infos"** puis **"Exécuter quand même"**.
3. L'installeur ne demande pas les droits administrateur (installation dans ton dossier
   utilisateur). Coche "Lancer au démarrage de Windows" si tu veux ne plus y penser.
4. Au premier lancement, un fichier `config.json` est créé automatiquement à côté du
   programme, avec un token de sécurité généré une seule fois (voir plus bas) — rien à
   configurer pour un usage standard.

Une icône apparaît dans la zone de notification Windows (bouton des apps, en bas à droite
de la barre des tâches, à côté de l'heure — parfois repliée sous le chevron `^`) tant que
le programme tourne. Clic droit dessus pour ouvrir CLIMB.EUW ou quitter proprement (arrête
aussi le serveur local).

Le site affiche la phase de jeu en direct quand tu es sur ce même PC — il interroge un
petit statut local exposé par le programme (port 37653).

### Configuration avancée (facultatif)

Le programme trouve tout seul League of Legends dans l'immense majorité des installations
standard. Si le tien est ailleurs, édite `config.json` (situé dans le dossier
d'installation) :

```json
{
  "lockfile_path": null,
  "riot_client_path": null
}
```

- `lockfile_path` : chemin du fichier `lockfile` du client, si League of Legends est
  installé à un endroit inhabituel — ex : `C:\Riot Games\League of Legends\lockfile`.
- `riot_client_path` : chemin de `RiotClientServices.exe`, si le Riot Client est installé
  ailleurs que `C:\Riot Games\Riot Client\` — sert uniquement à lancer le client depuis le
  téléphone (voir plus bas).

## Piloter la sélection de champion depuis ton téléphone

La page "Sélection de champion" de CLIMB.EUW peut piloter en direct le champ select
(picks, bans) et changer tes pages de runes, **depuis ton téléphone, tant qu'il est sur
le même Wi-Fi que ce PC** — le programme expose ça sur le même port 37653, mais désormais
sur tout le réseau local (pas seulement ce PC), pour que le téléphone puisse l'atteindre.

**Configuration, une seule fois : rien à recopier à la main** — sur ce PC, ouvre
CLIMB.EUW → Paramètres → section "Connecter ton téléphone", et scanne le QR code affiché
avec l'appareil photo de ton téléphone (même Wi-Fi que ce PC). Ça configure l'adresse et
le token automatiquement, et t'amène directement sur la page **Sélection de champion** —
mémorisé une fois pour toutes sur ce téléphone, tu n'as plus rien à refaire tant que ton
adresse locale ne change pas.

Le token est généré automatiquement une seule fois (voir `remote_token` dans
`config.json`, jamais régénéré ensuite) et sert à empêcher qu'un inconnu sur le même
Wi-Fi (café, LAN party) puisse piloter ton champ select à ta place — sans lui, seul
`/status` (juste "es-tu en game ?", rien de plus) reste accessible. Si le QR code n'est
pas pratique à scanner (site pas ouvert sur ce PC en ce moment, par exemple), l'adresse et
le token restent aussi affichés dans la fenêtre du programme au démarrage, à saisir à la
main sur la page Sélection de champion.

⚠️ **Ça reste toi qui choisis** — le téléphone ne fait qu'un relais vers les actions du
client, exactement comme si tu cliquais dedans directement (aucune automatisation de
gameplay, aucune décision prise à ta place). Si ton adresse IP locale change (redémarrage
du routeur, reconnexion Wi-Fi), le programme affiche la nouvelle adresse à son prochain
démarrage.

## Lancer LoL et lancer une recherche de partie depuis ton téléphone

Toujours depuis la page "Sélection de champion" (même pairing que ci-dessus), deux
actions en plus :

- **Lancer LoL** — démarre le Riot Client s'il est fermé (`riot_client_path`, voir la
  configuration avancée), *et* déclenche "Jouer" à ta place (via l'API locale du Riot
  Client) qu'il soit déjà ouvert ou pas — plus besoin de cliquer "Jouer" toi-même une fois
  la fenêtre apparue.
- **Rechercher une partie** — choisis la queue (Solo/Duo classée, Flexible classée ou
  Normale Draft) et, pour ces trois-là, ton rôle principal et secondaire ; le programme
  crée le lobby, règle tes préférences de rôle puis lance la recherche, exactement comme
  si tu cliquais toi-même dans le client. Un bouton "Annuler" apparaît pendant que la
  recherche est en cours.

## Suivre la partie en direct depuis ton téléphone

Une fois en jeu (chargement terminé), la page "Sélection de champion" affiche : le
chrono, les deux équipes (champion, niveau, KDA, CS, objets, mort/respawn), ton or actuel,
et l'historique des objectifs pris (dragon, héraut, baron, tourelles, inhibiteurs) avec
l'heure et l'équipe. Uniquement des faits confirmés par le jeu — **pas** de compte à
rebours de prochain objectif ni de cooldown de sort adverse : Riot ne fournit ni l'un ni
l'autre de façon fiable par cette API, les deviner reviendrait à afficher un chiffre faux
présenté comme sûr.

Comme pour le champ select, c'est protégé par le même token — sans lui, personne
d'autre sur le Wi-Fi ne peut lancer une recherche de partie ou le client à ta place.

## Lien "Lancer" depuis le site CLIMB.EUW

Le bouton "Lancer GameDetectorLol" de la page Paramètres de CLIMB.EUW utilise un lien
`gamedetectorlol://...` — un mécanisme standard de Windows (comme ceux qui ouvrent Spotify
ou Discord depuis un navigateur), enregistré automatiquement par l'installeur. Ton
navigateur demande une confirmation la première fois (comportement normal, pas
modifiable). Si le programme tourne déjà, il ne se relance pas en double (garde-fou
anti-doublon dans `notifier.py`) — la fenêtre l'indique et reste ouverte pour que tu
puisses le lire.

## Désinstaller

Comme n'importe quel programme Windows : Paramètres → Applications → GameDetectorLol →
Désinstaller. `config.json` (et donc ton token) n'est volontairement pas supprimé — une
réinstallation ultérieure retrouve la même configuration sans que ton téléphone ait besoin
de rescanner un QR code.

---

## Développement — reconstruire depuis les sources

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python notifier.py
```

### Reconstruire l'exécutable et l'installeur

```bash
pip install pyinstaller
pyinstaller --onefile --name GameDetectorLol --distpath dist --workpath build --specpath . notifier.py
```

Puis compiler `installer.iss` avec [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(gratuit) :

```bash
ISCC installer.iss
```

Produit `installer_output\GameDetectorLol-Setup.exe`.

### Endpoints exposés (voir `notifier.py` pour le détail)

- `GET /status` — phase de jeu actuelle + chargement terminé ou pas, jamais protégé par
  token.
- `GET /pairing` — adresse + token, réservé à ce PC (127.0.0.1), jamais accessible depuis
  le reste du Wi-Fi — voir le QR code de pairing.
- `GET /champselect`, `POST /champselect/action`, `POST /champselect/spells` — état et
  pilotage de la sélection de champion.
- `GET /runes`, `POST /runes/activate`, `POST /runes/update` — pages de runes.
- `POST /client/launch`, `GET /lobby`, `POST /lobby/search`, `POST /lobby/cancel` —
  lancement du client et recherche de partie.
- `POST /readycheck/accept`, `POST /readycheck/decline` — ready check.
- `GET /livegame` — état de la partie en cours (joueurs, items, niveau, KDA, CS,
  événements objectifs) une fois en jeu et le chargement terminé.

Tous sauf `/status` et `/pairing` exigent soit le token partagé (`remote_token`), soit
d'être appelés depuis ce PC.

## Licence

Ce projet n'est ni approuvé ni affilié à Riot Games. League of Legends © Riot Games, Inc.
