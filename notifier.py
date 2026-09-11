"""
GameDetectorLol - Surveille ta partie League of Legends en cours et expose une petite API
locale (STATUS_PORT) que le site CLIMB.EUW interroge pour afficher, EN DIRECT dans l'app
(page Sélection de champion ou Paramètres), la phase de jeu actuelle et si le chargement
est terminé — plus besoin de notification Discord, il suffit de regarder l'app.

Endpoints, aussi pilotables depuis le même réseau Wi-Fi (pas besoin d'être sur ce PC) :
- GET  /status                — phase de jeu actuelle + chargement terminé ou pas (voir
                                 STATUS ci-dessous), jamais protégé par token.
- GET  /pairing                — adresse + token, pour que le site les récupère lui-même et
                                 affiche un QR code/lien à scanner (voir README) — réservé à
                                 ce PC (127.0.0.1), jamais accessible depuis le reste du Wi-Fi.
- GET  /champselect           — état de la sélection de champion en cours (picks, bans, timer).
- POST /champselect/action     — effectuer un pick/ban (hover ou confirmer).
- POST /champselect/spells      — changer ses deux sorts d'invocateur.
- GET  /runes                 — liste des pages de runes sauvegardées.
- POST /runes/activate         — activer une page de runes existante, sans la modifier.
- POST /runes/update           — modifier l'arbre primaire/secondaire d'une page (et
                                 l'activer) ; les statistiques bonus (3e ligne) sont conservées.
- POST /client/launch          — lance le Riot Client (League of Legends) si fermé.
- GET  /lobby                 — file d'attente/rôles en cours (queueId, préférences, recherche).
- POST /lobby/queue            — crée le lobby, règle les rôles, lance la recherche de partie.
- POST /lobby/cancel           — annule la recherche de partie en cours.
- POST /readycheck/accept      — accepte la partie trouvée (ready check).
- POST /readycheck/decline      — refuse la partie trouvée (ready check).
Tous sauf /status et /pairing exigent soit le token partagé (REMOTE_TOKEN), soit d'être
appelés depuis ce PC — pour qu'un inconnu sur le même Wi-Fi (café, LAN party) ne puisse
pas te faire ban/pick, lancer une recherche de partie, etc. à ta place.

Fonctionnement :
- Lit le fichier "lockfile" créé par le client League of Legends quand il tourne
  (contient le port et le mot de passe de son API locale).
- Interroge régulièrement l'API locale du CLIENT (LCU) pour connaître la phase
  de jeu actuelle (gameflow-phase). Cette phase passe à "InProgress" dès que le
  PROCESSUS de la partie démarre — c'est-à-dire au tout DÉBUT de l'écran de
  chargement, pas à sa fin. Riot n'a pas de phase LCU distincte pour "chargement
  terminé" : de son point de vue c'est "InProgress" du début du chargement jusqu'à
  la fin de la game.
- Pour détecter la fin du chargement précisément, on interroge en plus l'API locale
  du JEU lui-même (port 2999, Live Client Data) une fois "InProgress" détecté :
  contrairement au LCU, ce port ne répond qu'une fois que TON client a fini de
  charger et est réellement connecté à la partie — avant ça, la requête échoue
  simplement (connexion refusée). Le premier succès marque la fin du chargement
  (STATUS["gameLoaded"] = True), lu par le site pour afficher "en jeu" plutôt que
  "chargement en cours".

Affiche aussi une icône dans la zone de notification Windows (bouton des apps, en bas
à droite de la barre des tâches) tant que le script tourne — sans elle, la seule façon
de savoir s'il est actif était de retrouver sa fenêtre de console parmi toutes les
autres. Clic droit sur l'icône pour ouvrir CLIMB.EUW ou quitter proprement.

Voir README.md pour la configuration (config.json, accès réseau local).
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlparse

import pystray
import requests
import urllib3
from PIL import Image, ImageDraw

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Une fois figé en .exe par PyInstaller (--onefile), __file__ pointe vers le dossier
# d'extraction temporaire (sys._MEIPASS), recréé à chaque lancement — y lire/écrire
# config.json ferait perdre le token stable à chaque redémarrage (voir sa persistance
# plus bas, load_config). sys.executable, lui, reste le vrai .exe installé.
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH = APP_DIR / "config.json"

# Adresse du site — utilisée par le menu de l'icône de la zone de notification
# ("Ouvrir CLIMB.EUW").
SITE_URL = "https://romainpitot.github.io/lol-climb-tracker/"

# Emplacements standards du lockfile selon le lanceur utilisé.
DEFAULT_LOCKFILE_CANDIDATES = [
    Path("C:/Riot Games/League of Legends/lockfile"),
    Path(Path.home(), "AppData/Local/Riot Games/League of Legends/lockfile"),
]

# Emplacement standard de RiotClientServices.exe — c'est lui qui lance le jeu (pas
# league_of_legends.exe directement), pour tout ce qu'il gère avant (mises à jour,
# connexion...). Le lockfile ci-dessus n'existe qu'une fois le client déjà ouvert : ça ne
# sert à rien pour LE démarrer, d'où ce chemin séparé.
DEFAULT_RIOT_CLIENT_CANDIDATES = [
    Path("C:/Riot Games/Riot Client/RiotClientServices.exe"),
]

# Lockfile du Riot Client lui-même (différent de celui de League ci-dessus) — donne accès à
# sa propre API locale, seule façon fiable de déclencher "Jouer" par programme : lancer
# RiotClientServices.exe avec --launch-product/--launch-patchline ne fonctionne qu'au tout
# premier démarrage (le client à froid lit ces arguments) ; si le Riot Client tourne déjà
# (ouvert, mais resté au menu), le relancer ne fait que ramener sa fenêtre au premier plan
# sans jouer — c'est exactement le clic manuel sur "Jouer" que ça t'obligeait à faire.
RIOT_CLIENT_LOCKFILE = Path(os.environ.get("LOCALAPPDATA", ""), "Riot Games/Riot Client/Config/lockfile")

# Queues où League autorise à choisir des rôles (les autres — ARAM, blind pick... — n'ont
# pas cette notion, le client refuserait la requête de préférences de position).
ROLE_QUEUES = {
    420: "Solo/Duo classée",
    440: "Flexible classée",
    400: "Normale (Draft)",
}

# Intervalle rapide : utilisé dès qu'on est dans une phase où un des 3 signaux peut se
# déclencher d'un instant à l'autre (recherche de partie, ready check, champ select,
# chargement). Intervalle lent : le reste du temps (menu, lobby sans recherche active) —
# rien d'urgent ne peut s'y produire, pas la peine d'interroger le client aussi souvent.
FAST_POLL_SECONDS = 0.5
IDLE_POLL_SECONDS = 3
IDLE_PHASES = {"None", "Lobby"}

RETRY_INTERVAL_SECONDS = 10

# API locale du jeu (pas du client) — n'existe que pendant qu'une partie tourne, et ne
# répond qu'une fois le chargement du joueur local terminé.
LIVE_CLIENT_URL = "https://127.0.0.1:2999/liveclientdata/gamestats"

# Port du petit serveur de statut local (voir STATUS ci-dessous). Choisi au hasard dans
# la plage "user ports" pour limiter le risque de collision avec autre chose sur ta machine.
STATUS_PORT = 37653

# État partagé, lu par le serveur de statut et écrit par la boucle principale. Un simple
# dict suffit ici (pas besoin de verrou) : le GIL de Python rend chaque affectation d'une
# clé atomique, et on ne fait jamais de lecture-modification-écriture entre threads.
# gameLoaded distingue "chargement en cours" de "en jeu" au sein de la même phase LCU
# InProgress (voir is_game_loaded) — c'est ce que le site affiche à la place d'une
# notification Discord.
STATUS = {"phase": None, "gameLoaded": False, "last_update": None}

# Dernier appel à /status venu d'ailleurs que ce PC (voir do_GET) — sert uniquement à
# détecter qu'un téléphone a bien fini de scanner le QR code et interroge maintenant le
# script pour de vrai (voir REMOTE_CONNECTED_WINDOW_S), pour faire disparaître le QR côté
# site sans action manuelle. Jamais utilisé pour une décision de sécurité.
_last_remote_status_at: float | None = None
REMOTE_CONNECTED_WINDOW_S = 8

# Identifiants de l'API locale du CLIENT (LCU), mis à jour à chaque tour de boucle tant
# que le client tourne — c'est ce qui permet au thread du serveur HTTP (voir
# StatusHandler) d'appeler le LCU pour le champ select / les runes, indépendamment de la
# boucle principale qui ne fait qu'y lire la phase de jeu.
LCU = {"port": None, "password": None, "protocol": None}

# Adresse + token courants, pour que le site (depuis ce PC uniquement, voir /pairing et
# _is_loopback) puisse les récupérer lui-même plutôt que de les faire recopier à la main.
PAIRING = {"host": None, "token": None}

# Chemin explicite vers RiotClientServices.exe (config.json: "riot_client_path"), pour les
# installs hors du dossier par défaut — None tant que main() n'a pas chargé la config.
RIOT_CLIENT_PATH: str | None = None


def load_config() -> dict:
    # Valeurs par défaut auto-créées plutôt qu'une erreur bloquante : lockfile_path et
    # riot_client_path restant à null fonctionnent pour l'immense majorité des
    # installations standard (voir find_lockfile/RIOT_CLIENT_PATH) — pas besoin d'un
    # copier-coller manuel de config.example.json avant le tout premier lancement.
    if not CONFIG_PATH.exists():
        save_config({"lockfile_path": None, "riot_client_path": None})
        print("Premier lancement : config.json créé avec les valeurs par défaut.")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Le token de contrôle à distance (pick/ban/runes) est généré une fois puis persisté :
    # sans lui, n'importe qui sur le même Wi-Fi pourrait piloter ton champ select.
    if not config.get("remote_token"):
        config["remote_token"] = secrets.token_urlsafe(24)
        save_config(config)
        print("Nouveau token de contrôle à distance généré et enregistré dans config.json.")

    return config


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def build_tray_icon_image() -> Image.Image:
    """Icône ronde simple (couleurs du site CLIMB.EUW) — dessinée à la volée plutôt que
    chargée depuis un fichier .ico à maintenir séparément dans ce dossier."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(30, 20, 50, 255), outline=(212, 175, 55, 255), width=5)
    draw.ellipse((20, 20, size - 20, size - 20), fill=(212, 175, 55, 255))
    return img


def find_lockfile(explicit_path: str | None) -> Path | None:
    if explicit_path:
        p = Path(explicit_path)
        return p if p.exists() else None

    for candidate in DEFAULT_LOCKFILE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def find_riot_client(explicit_path: str | None) -> Path | None:
    if explicit_path:
        p = Path(explicit_path)
        return p if p.exists() else None

    for candidate in DEFAULT_RIOT_CLIENT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def read_riot_client_lockfile():
    """Port+mot de passe de l'API locale du Riot Client (différente de celle de League,
    voir RIOT_CLIENT_LOCKFILE) — None tant qu'il n'est pas (encore) ouvert."""
    if not RIOT_CLIENT_LOCKFILE.exists():
        return None
    port, password, protocol = read_lockfile(RIOT_CLIENT_LOCKFILE)
    return {"port": port, "password": password, "protocol": protocol}


def launch_riot_client(explicit_path: str | None) -> None:
    """Lance vraiment la partie — équivalent du clic sur "Jouer" dans le Riot Client, pas
    juste l'ouverture de sa fenêtre (voir RIOT_CLIENT_LOCKFILE ci-dessus pour le pourquoi).

    - Riot Client pas encore ouvert : le démarrer (Popen, on n'attend pas qu'il se ferme),
      puis attendre que son lockfile apparaisse pour pouvoir lui parler.
    - Riot Client déjà ouvert (ou qui vient de démarrer) : POST sur son API locale pour
      déclencher le lancement du jeu — un 423 "already_launched" est un succès, pas une
      erreur (le jeu est déjà en cours de lancement/lancé)."""
    rc = read_riot_client_lockfile()
    if rc is None:
        exe = find_riot_client(explicit_path)
        if exe is None:
            raise FileNotFoundError(
                "RiotClientServices.exe introuvable — configure riot_client_path dans "
                "config.json s'il est installé ailleurs que C:/Riot Games/Riot Client/."
            )
        subprocess.Popen(
            [str(exe), "--launch-product=league_of_legends", "--launch-patchline=live"],
            cwd=str(exe.parent),
        )
        deadline = time.time() + 20
        while time.time() < deadline and rc is None:
            time.sleep(0.5)
            rc = read_riot_client_lockfile()
        if rc is None:
            # Le client a mis trop de temps à écrire son lockfile — il reste ouvert (la
            # commande de démarrage l'a bien lancé), juste sans le "Jouer" automatique
            # cette fois. Pas une erreur bloquante : on abandonne juste l'étape en plus.
            return

    resp = requests.post(
        f"{rc['protocol']}://127.0.0.1:{rc['port']}/product-launcher/v1/products/league_of_legends/patchlines/live",
        auth=("riot", rc["password"]),
        verify=False,
        timeout=10,
    )
    if resp.status_code >= 300 and resp.status_code != 423:
        raise RuntimeError(resp.text or "Lancement du jeu refusé par le Riot Client.")


def read_lockfile(path: Path):
    # Format : name:pid:port:password:protocol
    content = path.read_text(encoding="utf-8").strip()
    parts = content.split(":")
    port, password, protocol = parts[2], parts[3], parts[4]
    return port, password, protocol


def get_gameflow_phase(port: str, password: str, protocol: str) -> str:
    url = f"{protocol}://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase"
    resp = requests.get(url, auth=("riot", password), verify=False, timeout=5)
    resp.raise_for_status()
    return resp.json()


def is_game_loaded() -> bool:
    """True dès que l'API du jeu (port 2999) répond — donc que le chargement local
    est terminé. Aucune erreur n'est levée pendant le chargement, c'est attendu :
    la connexion est simplement refusée tant que le jeu n'écoute pas encore."""
    try:
        resp = requests.get(LIVE_CLIENT_URL, verify=False, timeout=2)
        return resp.status_code == 200
    except requests.RequestException:
        return False


class LcuNotConnected(Exception):
    pass


def lcu_request(method: str, path: str, json_body=None, timeout: float = 5.0):
    """Appelle l'API locale du client (LCU) avec les identifiants captés depuis le
    lockfile. Lève LcuNotConnected si le client n'est pas détecté — les endpoints
    champ select/runes du serveur HTTP s'appuient là-dessus pour renvoyer une erreur
    claire plutôt qu'un plantage si on appelle ça alors que le client est fermé."""
    if not LCU["port"]:
        raise LcuNotConnected("Client League of Legends non détecté")
    url = f"{LCU['protocol']}://127.0.0.1:{LCU['port']}{path}"
    resp = requests.request(
        method, url, json=json_body, auth=("riot", LCU["password"]), verify=False, timeout=timeout
    )
    return resp


def get_champselect_session():
    """Session de champ select en cours, réduite aux champs utiles côté téléphone.
    Retourne None si on n'est pas (ou plus) en champ select — le 404 du LCU dans ce
    cas n'est pas une erreur, c'est l'état normal la majorité du temps."""
    resp = lcu_request("GET", "/lol-champ-select/v1/session")
    if resp.status_code != 200:
        return None
    s = resp.json()
    return {
        "localPlayerCellId": s.get("localPlayerCellId"),
        "timer": s.get("timer"),
        "myTeam": s.get("myTeam", []),
        "theirTeam": s.get("theirTeam", []),
        "bans": s.get("bans", {}),
        "actions": s.get("actions", []),
        "benchEnabled": s.get("benchEnabled", False),
        "benchChampions": s.get("benchChampions", []),
    }


def set_summoner_spells(spell1_id: int, spell2_id: int) -> None:
    """Change tes deux sorts d'invocateur pendant la sélection — mêmes ids que ceux déjà
    lus dans myTeam[].spell1Id/spell2Id (voir get_champselect_session), donc aucune donnée
    supplémentaire à charger côté site pour savoir ce qui est actuellement équipé."""
    resp = lcu_request(
        "PATCH",
        "/lol-champ-select/v1/session/my-selection",
        {"spell1Id": spell1_id, "spell2Id": spell2_id},
    )
    if resp.status_code >= 300:
        raise RuntimeError(resp.text or "Changement de sorts refusé par le client.")


def get_lobby_status():
    """Lobby courant (queue + rôles + recherche en cours), réduit aux champs utiles côté
    téléphone. Retourne None si aucun lobby (menu principal, déjà en champ select...) —
    le 404 du LCU dans ce cas n'est pas une erreur, c'est l'état normal la majorité du temps."""
    resp = lcu_request("GET", "/lol-lobby/v2/lobby")
    if resp.status_code != 200:
        return None
    lobby = resp.json()
    member = lobby.get("localMember", {})

    searching = False
    search_resp = lcu_request("GET", "/lol-lobby/v2/lobby/matchmaking/search-state")
    if search_resp.status_code == 200:
        searching = search_resp.json().get("searchState") == "Searching"

    return {
        "queueId": lobby.get("gameConfig", {}).get("queueId"),
        "firstPreference": member.get("firstPositionPreference"),
        "secondPreference": member.get("secondPositionPreference"),
        "searching": searching,
    }


def start_queue(queue_id: int, first_position: str | None, second_position: str | None) -> None:
    """Crée (ou remplace) le lobby pour cette queue, règle les préférences de rôle si la
    queue les supporte (voir ROLE_QUEUES), puis lance la recherche de partie — l'équivalent
    de cliquer la queue puis "Rechercher" dans le client, fait depuis le téléphone."""
    resp = lcu_request("POST", "/lol-lobby/v2/lobby", {"queueId": queue_id})
    if resp.status_code >= 300:
        raise RuntimeError(resp.text or "Impossible de créer le lobby.")

    if queue_id in ROLE_QUEUES and first_position:
        prefs = {"firstPreference": first_position, "secondPreference": second_position or "FILL"}
        resp = lcu_request("PUT", "/lol-lobby/v2/lobby/members/localMember/position-preferences", prefs)
        if resp.status_code >= 300:
            raise RuntimeError(resp.text or "Impossible de régler les rôles.")

    resp = lcu_request("POST", "/lol-lobby/v2/lobby/matchmaking/search")
    if resp.status_code >= 300:
        raise RuntimeError(resp.text or "Impossible de lancer la recherche de partie.")


def cancel_queue() -> None:
    resp = lcu_request("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")
    if resp.status_code >= 300 and resp.status_code != 404:
        raise RuntimeError(resp.text or "Impossible d'annuler la recherche de partie.")


def respond_ready_check(accept: bool) -> None:
    """Accepte ou refuse la partie trouvée (ready check) — mêmes conséquences que dans le
    client (refuser/laisser expirer donne une pénalité de dodge, comme d'habitude)."""
    action = "accept" if accept else "decline"
    resp = lcu_request("POST", f"/lol-matchmaking/v1/ready-check/{action}")
    if resp.status_code >= 300:
        raise RuntimeError(resp.text or "Impossible de répondre au ready check.")


class StatusHandler(BaseHTTPRequestHandler):
    """Statut (existant, ouvert) + champ select / runes (nouveaux, protégés par un token
    partagé) — CORS ouvert dans tous les cas : le site CLIMB.EUW (une origine différente,
    potentiellement sur un autre appareil du même Wi-Fi) doit pouvoir lire les réponses."""

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_loopback(self) -> bool:
        """True seulement si la requête vient de ce PC — jamais du reste du Wi-Fi. Sert de
        garde pour /pairing, qui renvoie le token en clair : ce serait sinon accessible à
        n'importe qui capable d'atteindre ce port sur le réseau local, sans même le connaître."""
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _check_token(self) -> bool:
        auth = self.headers.get("Authorization") or ""
        token = auth[7:] if auth.startswith("Bearer ") else ""
        expected = STATUS.get("remote_token")
        if not expected or token != expected:
            self._send_json(401, {"error": "Token invalide ou manquant."})
            return False
        return True

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/status":
            global _last_remote_status_at
            if not self._is_loopback():
                _last_remote_status_at = time.time()
            remote_connected = (
                _last_remote_status_at is not None
                and time.time() - _last_remote_status_at < REMOTE_CONNECTED_WINDOW_S
            )
            self._send_json(200, {"running": True, **STATUS, "remote_token": None, "remoteConnected": remote_connected})
            return

        if parsed.path == "/pairing":
            # Réservé à ce PC : l'adresse ET le token complets ne doivent jamais être
            # servis à qui que ce soit d'autre sur le Wi-Fi (voir _is_loopback).
            if not self._is_loopback():
                self._send_json(403, {"error": "Disponible uniquement depuis ce PC."})
                return
            self._send_json(200, {"host": PAIRING.get("host"), "token": PAIRING.get("token")})
            return

        if parsed.path == "/champselect":
            if not self._check_token():
                return
            try:
                session = get_champselect_session()
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"session": session})
            return

        if parsed.path == "/runes":
            if not self._check_token():
                return
            try:
                resp = lcu_request("GET", "/lol-perks/v1/pages")
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"pages": resp.json()})
            return

        if parsed.path == "/lobby":
            if not self._check_token():
                return
            try:
                lobby = get_lobby_status()
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"lobby": lobby, "roleQueues": ROLE_QUEUES})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._check_token():
            return

        try:
            body = self._read_json_body()
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "JSON invalide."})
            return

        if parsed.path == "/champselect/action":
            action_id = body.get("actionId")
            champion_id = body.get("championId")
            completed = bool(body.get("completed"))
            if action_id is None or champion_id is None:
                self._send_json(400, {"error": "actionId et championId requis."})
                return
            try:
                resp = lcu_request(
                    "PATCH",
                    f"/lol-champ-select/v1/session/actions/{action_id}",
                    {"championId": champion_id, "completed": completed},
                )
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            if resp.status_code >= 300:
                self._send_json(resp.status_code, {"error": resp.text or "Action refusée par le client."})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/champselect/spells":
            spell1_id = body.get("spell1Id")
            spell2_id = body.get("spell2Id")
            if spell1_id is None or spell2_id is None:
                self._send_json(400, {"error": "spell1Id et spell2Id requis."})
                return
            try:
                set_summoner_spells(spell1_id, spell2_id)
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            except RuntimeError as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/runes/activate":
            page_id = body.get("pageId")
            if page_id is None:
                self._send_json(400, {"error": "pageId requis."})
                return
            try:
                get_resp = lcu_request("GET", f"/lol-perks/v1/pages/{page_id}")
                if get_resp.status_code != 200:
                    self._send_json(404, {"error": "Page de runes introuvable."})
                    return
                page = get_resp.json()
                page["current"] = True
                resp = lcu_request("PUT", f"/lol-perks/v1/pages/{page_id}", page)
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            if resp.status_code >= 300:
                self._send_json(resp.status_code, {"error": resp.text or "Activation refusée par le client."})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/runes/update":
            page_id = body.get("pageId")
            primary_style_id = body.get("primaryStyleId")
            sub_style_id = body.get("subStyleId")
            primary_perk_ids = body.get("primaryPerkIds")
            secondary_perk_ids = body.get("secondaryPerkIds")
            if (
                page_id is None
                or not primary_style_id
                or not sub_style_id
                or not isinstance(primary_perk_ids, list)
                or len(primary_perk_ids) != 4
                or not isinstance(secondary_perk_ids, list)
                or len(secondary_perk_ids) != 2
            ):
                self._send_json(400, {"error": "pageId, primaryStyleId, subStyleId, primaryPerkIds (4) et secondaryPerkIds (2) requis."})
                return
            try:
                get_resp = lcu_request("GET", f"/lol-perks/v1/pages/{page_id}")
                if get_resp.status_code != 200:
                    self._send_json(404, {"error": "Page de runes introuvable."})
                    return
                page = get_resp.json()
                # Les 3 derniers ids de selectedPerkIds sont les statistiques bonus (3e ligne,
                # "stat shards") — on les garde tels quels : leur regroupement par ligne n'est
                # pas exposé par le LCU de façon fiable, donc on ne les propose pas à l'édition
                # pour éviter d'envoyer une combinaison invalide.
                stat_perk_ids = page.get("selectedPerkIds", [])[-3:]
                page["primaryStyleId"] = primary_style_id
                page["subStyleId"] = sub_style_id
                page["selectedPerkIds"] = [*primary_perk_ids, *secondary_perk_ids, *stat_perk_ids]
                page["current"] = True
                resp = lcu_request("PUT", f"/lol-perks/v1/pages/{page_id}", page)
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            if resp.status_code >= 300:
                self._send_json(resp.status_code, {"error": resp.text or "Modification refusée par le client."})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/client/launch":
            try:
                launch_riot_client(RIOT_CLIENT_PATH)
            except FileNotFoundError as e:
                self._send_json(404, {"error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/lobby/queue":
            queue_id = body.get("queueId")
            if queue_id is None:
                self._send_json(400, {"error": "queueId requis."})
                return
            try:
                start_queue(int(queue_id), body.get("firstPreference"), body.get("secondPreference"))
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            except RuntimeError as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/lobby/cancel":
            try:
                cancel_queue()
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            except RuntimeError as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return

        if parsed.path in ("/readycheck/accept", "/readycheck/decline"):
            try:
                respond_ready_check(parsed.path.endswith("accept"))
            except LcuNotConnected as e:
                self._send_json(409, {"error": str(e)})
                return
            except RuntimeError as e:
                self._send_json(409, {"error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # silencieux : sinon chaque poll du site spamme la console


class SingleInstanceHTTPServer(ThreadingMixIn, HTTPServer):
    # HTTPServer active allow_reuse_address par défaut — sur Windows, ça permet à un
    # second processus de se lier au même port MÊME SI le premier l'écoute encore
    # activement (contrairement à Linux, où ça ne sert qu'à éviter l'état TIME_WAIT).
    # Sans le désactiver ici, deux instances de ce script pourraient tourner en même
    # temps sans jamais se détecter l'une l'autre — bug constaté en testant ce garde-fou.
    allow_reuse_address = False
    # ThreadingMixIn : une requête lente (/client/launch attend jusqu'à 20s que le Riot
    # Client démarre, /lobby/queue attend le LCU...) ne doit jamais bloquer les autres —
    # sinon même le simple polling /status du téléphone se met en attente derrière elle et
    # peut finir en "failed to fetch" côté navigateur. daemon_threads : ces threads de
    # requête ne doivent pas empêcher le process de quitter (voir os._exit dans main()).
    daemon_threads = True


def get_lan_ip() -> str:
    """IP de ce PC sur le réseau local (celle à donner au téléphone) — trouvée sans
    dépendance externe en ouvrant un socket UDP vers une IP publique : aucun paquet
    n'est réellement envoyé, ça sert juste à demander au système quelle interface
    locale serait utilisée, donc quelle IP LAN elle porte."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def start_status_server() -> HTTPServer | None:
    """Démarre le serveur de statut dans un thread à part, accessible depuis tout le
    réseau local (0.0.0.0) — pas seulement ce PC — pour piloter le champ select depuis
    le téléphone. Si le port est déjà pris, c'est très probablement qu'une autre
    instance de ce script tourne déjà — on le signale et on renvoie None pour que
    main() s'arrête plutôt que de tourner en double (double envoi des mêmes
    notifications Discord sinon)."""
    try:
        server = SingleInstanceHTTPServer(("0.0.0.0", STATUS_PORT), StatusHandler)
    except OSError:
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def monitor_loop(lockfile_path: str | None) -> None:
    """Boucle de surveillance du client LoL (voir le docstring du module) — tourne sur un
    thread à part depuis que l'icône de la zone de notification occupe le thread principal
    (pystray l'exige sur Windows). Ne fait qu'écrire dans STATUS : c'est le site (via
    /status) qui affiche la phase et le chargement en direct, plus de notification Discord."""
    last_phase = None

    while True:
        lockfile = find_lockfile(lockfile_path)
        if lockfile is None:
            STATUS["phase"] = None
            STATUS["gameLoaded"] = False
            STATUS["last_update"] = time.time()
            LCU["port"] = None
            print(f"Client LoL non détecté. Nouvel essai dans {RETRY_INTERVAL_SECONDS}s...")
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue

        try:
            port, password, protocol = read_lockfile(lockfile)
            phase = get_gameflow_phase(port, password, protocol)
        except Exception as e:
            if last_phase is not None:
                print(f"Client fermé ou injoignable ({e}). Nouvel essai...")
            last_phase = None
            STATUS["phase"] = None
            STATUS["gameLoaded"] = False
            STATUS["last_update"] = time.time()
            LCU["port"] = None
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue

        LCU["port"], LCU["password"], LCU["protocol"] = port, password, protocol
        STATUS["phase"] = phase
        STATUS["last_update"] = time.time()

        if phase != last_phase:
            print(f"Phase : {last_phase} -> {phase}")
            # On repasse par le lobby/menu -> on réarme le flag pour la prochaine partie.
            if phase in ("None", "Lobby"):
                STATUS["gameLoaded"] = False
            last_phase = phase

        # Tant qu'on est en partie et que le chargement local n'est pas encore confirmé
        # terminé, on vérifie l'API du jeu à chaque tour de boucle.
        if phase == "InProgress" and not STATUS["gameLoaded"]:
            if is_game_loaded():
                STATUS["gameLoaded"] = True
                print("Chargement terminé, en jeu.")

        sleep_time = IDLE_POLL_SECONDS if phase in IDLE_PHASES else FAST_POLL_SECONDS
        time.sleep(sleep_time)


def build_tray_menu(icon: "pystray.Icon") -> "pystray.Menu":
    return pystray.Menu(
        pystray.MenuItem("GameDetectorLol — actif", None, enabled=False),
        pystray.MenuItem("Ouvrir CLIMB.EUW", lambda: webbrowser.open(SITE_URL)),
        pystray.MenuItem("Quitter", lambda: icon.stop()),
    )


def main() -> None:
    server = start_status_server()
    if server is None:
        print(
            f"Le port {STATUS_PORT} est déjà utilisé — une instance de GameDetectorLol "
            "tourne probablement déjà. Fermeture pour éviter des notifications en double."
        )
        sys.exit(1)

    config = load_config()
    lockfile_path = config.get("lockfile_path")
    STATUS["remote_token"] = config["remote_token"]

    global RIOT_CLIENT_PATH
    RIOT_CLIENT_PATH = config.get("riot_client_path")

    lan_ip = get_lan_ip()
    PAIRING["host"] = f"{lan_ip}:{STATUS_PORT}"
    PAIRING["token"] = config["remote_token"]

    print("GameDetectorLol démarré. En attente du client League of Legends...")
    print(
        f"Pilotage depuis le téléphone (même Wi-Fi) : adresse {lan_ip}:{STATUS_PORT}, "
        f"token {config['remote_token']} (au cas où — un QR code/lien de configuration "
        f"automatique est aussi affiché dans Paramètres sur CLIMB.EUW)."
    )
    print("Icône ajoutée dans la zone de notification (bouton des apps, en bas à droite).")

    # Thread à part : pystray a besoin du thread principal pour sa propre boucle
    # d'événements sur Windows (icon.run() ci-dessous, bloquant jusqu'à "Quitter").
    threading.Thread(target=monitor_loop, args=(lockfile_path,), daemon=True).start()

    icon = pystray.Icon("GameDetectorLol", build_tray_icon_image(), "GameDetectorLol — actif")
    icon.menu = build_tray_menu(icon)
    icon.run()
    # icon.run() ne rend la main qu'après "Quitter" (icon.stop()) — en théorie les threads
    # restants (serveur HTTP, surveillance) sont daemon=True et s'arrêtent avec le process.
    # En pratique, sur Windows, pystray peut laisser une fenêtre cachée ou un handle qui
    # empêche l'interpréteur de vraiment se terminer tout seul ici — le process reste alors
    # invisible (plus d'icône) mais toujours vivant, port 37653 toujours occupé, empêchant
    # tout relancement ("le port est déjà utilisé"). os._exit() ferme le process pour de bon,
    # sans dépendre du nettoyage de pystray — c'est justement fait pour ce cas.
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêt de GameDetectorLol.")
