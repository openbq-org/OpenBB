# OpenBB Trading Desk : démarrage

## 1. Lancer

- **Windows** : double-clic sur `OpenBB-Desk.bat`
- **macOS** : double-clic sur `OpenBB-Desk.command`
  (si macOS bloque : clic droit > Ouvrir, une seule fois)
- **Linux** : `./OpenBB-Desk.command`

La première fois, le lanceur installe `uv`, Python 3.12 et OpenBB dans `.venv`
(10-20 min). Ensuite le menu :

| choix | action |
| --- | --- |
| 1 | API OpenBB + serveur MCP, ouvre OpenBB Workspace (widgets « Day Trader » et « IBKR ») |
| 2 | Claude Code dans le projet : tapez `/trading-desk` |
| 3 | Statut : horloge NYSE, plan, ordres, journal |
| 4 | Test de connexion Interactive Brokers |
| 5 | Installer / mettre à jour |
| 6 | Tests |

Raccourcis : `OpenBB-Desk.bat start` (ou `claude`, `status`, `ibkr`, `install`, `test`).

Dans OpenBB Workspace (https://pro.openbb.co) : Apps > Connect backend >
`http://127.0.0.1:6900`.

## 2. Broker : Interactive Brokers (IBKR Ireland)

Pourquoi IBKR : ouvert aux résidents français (entité irlandaise, régulée UE),
compte **paper gratuit** et compte **réel** avec la même API, actions US à
partir de 0,0035-0,005 $/action, pas de restriction d'API.

1. Ouvrez un compte sur interactivebrokers.ie, puis créez le compte paper
   (Client Portal > Settings > Paper Trading Account). Il a ses propres
   identifiants.
2. Installez **IB Gateway** (version stable) et connectez-vous avec les
   identifiants **paper**.
3. IB Gateway > Configure > Settings > API > Settings : décochez
   **Read-Only API**, port **4002**, ajoutez `127.0.0.1` aux IP de confiance.
4. Menu **4** du lanceur : il doit afficher votre compte `DU...` et `"paper": true`.

Passer en réel (argent réel) : connectez IB Gateway au compte réel (port
**4001**), mettez `"paper": false` dans `trader/config.json`, puis tapez
`REEL` quand le lanceur le demande. Sans ces trois étapes, tout ordre sur un
compte réel est refusé.

Claude Code (menu 2) demande au premier lancement d'approuver les serveurs
MCP du projet `openbb` et `ibkr` : acceptez-les.

Le connecteur officiel IBKR pour Claude (annuaire claude.ai) existe aussi,
mais il ne fait que préparer des ordres à valider dans IBKR et ne fonctionne
pas avec le compte paper : le desk utilise donc IB Gateway.

Chaque ordre passe par trois vérifications : contrôle de risque PASS, votre
« yes » tapé pour ce ticket précis, puis le bouton Allow once de Claude.

À savoir en France :
- Compte titres IBKR (CTO) : pas d'IFU, déclaration vous-même (relevés IBKR,
  formulaire 2074) et déclaration du compte étranger (formulaire 3916-bis).
- PRIIPs : les ETF domiciliés aux US (SPY, QQQ...) ne sont pas achetables
  par un particulier européen ; les actions US le sont.
- Données temps réel : abonnements payants chez IBKR ; sinon données différées.

## 3. Réglages

`trader/config.json` (créé au premier lancement) : budget, perte max par
trade et par jour, nombre de trades, fenêtre d'entrée, `flat_by`, et
`sec_user_agent` (« Nom email », exigé par la SEC).

Ceci est un outil, pas un conseil financier. La majorité des day traders
perdent de l'argent : commencez en paper.
