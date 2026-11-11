# « Mes candidatures » sur ton PC (Windows)

Une application avec une fenêtre, qui rassemble au même endroit :

- les offres **VIE** (VIE Watcher, GitHub) ;
- les offres **CDI HelloWork et France Travail** (CDI Watcher, GitHub) ;
- les offres **CDI LinkedIn et APEC**, cherchées depuis ton PC, car ces deux sites bloquent GitHub.

Pour chaque offre : lien, CV conseillé, statut de suivi (À regarder, Candidaté,
Relance à faire, Entretien, Refusé, Pas intéressé), notes et lettre de
motivation générée à la demande. Ton Google Sheets « Suivi candidatures » est
tenu à jour automatiquement.

## Installation

Guide complet pas à pas (copie du dépôt GitHub, clés, réglages) : [README](../README.md).

Dans PowerShell :

```powershell
winget install -e --id Python.Python.3.13
winget install -e --id Git.Git
```

Ferme et rouvre PowerShell, puis :

```powershell
git clone https://github.com/TON-PSEUDO/FindJob "$HOME\FindJob"
cd "$HOME\FindJob"
powershell -ExecutionPolicy Bypass -File windows\setup.ps1
```

Le script, en 7 étapes :

1. vérifie Python ;
2. installe les dépendances ;
3. te demande tes 3 clés (les mêmes que les secrets GitHub), gardées dans `.env`
   sur ton PC uniquement ;
4. ouvre le Bloc-notes pour ton profil (`profile_cdi.txt`) ;
5. relie ton Google Sheets (facultatif, voir plus bas) ;
6. crée la tâche planifiée LinkedIn ;
7. crée l'icône **Mes candidatures** sur le bureau, puis propose un premier test.

## Google Sheets

À l'étape 5, le script copie `google_sheets\apps_script.gs` dans ton
presse-papiers, ouvre ton Sheets et te guide :
Extensions > Apps Script > coller > remplacer le code secret affiché >
Déployer > Nouveau déploiement > Application Web (Exécuter en tant que : Moi,
Qui a accès : Tout le monde) > copier l'URL et la coller dans PowerShell.

Ensuite, dans l'application :

| Statut dans l'application | Dans le Google Sheets |
| --- | --- |
| Candidaté, Relance à faire | ligne ajoutée (N, Poste, Entreprise, Lien, Date), Retour = En attente |
| Entretien | Retour = Positif |
| Refusé | Retour = Negatif |
| Notes | colonne Commentaire |

Une offre dont le lien est déjà dans ton Sheets est marquée
« 📗 déjà dans ton Sheets », pour éviter de postuler deux fois.

## France Travail (facultatif mais conseillé)

France Travail a une API officielle et gratuite. Pour l'activer :

1. crée un compte sur https://francetravail.io, puis « Mes applications » > « Créer une application » ;
2. abonne l'application à **API Offres d'emploi** ;
3. sur GitHub (Settings > Secrets and variables > Actions), ajoute deux secrets :
   `FT_CLIENT_ID` (identifiant) et `FT_CLIENT_SECRET` (clé secrète) ;
4. ajoute aussi ces deux lignes dans le fichier `.env` du PC, pour les lettres et
   préparations d'entretien des offres France Travail :
   `FT_CLIENT_ID=...` et `FT_CLIENT_SECRET=...`

Sans ces clés, la recherche France Travail est simplement ignorée.

## Réseau (onglet 🤝 Réseau)

Pour contacter directement des gens du secteur (un responsable d'équipe dans une entreprise qui t'intéresse...), dans un
deuxième Google Sheets. La première fois, l'onglet affiche le script à coller dans
Extensions > Apps Script (code secret déjà rempli), puis tu colles l'URL du déploiement.
Le script crée les onglets « Entreprises » et « Contacts ».

- **Entreprises** : liste de départ (réglée dans cdi_search.yaml), suggestions tirées
  de tes offres les mieux notées. « 🔎 Trouver des contacts » ouvre une recherche LinkedIn toute
  prête dans ton navigateur : c'est toi qui choisis les personnes.
- **Contacts** : tu ajoutes les personnes toi-même. Gemini écrit la note d'invitation LinkedIn
  (300 caractères max) et un mail ; tu relis, tu copies ou tu ouvres Gmail, et tu envoies toi-même.
  Suivi : contacté le, relance à 7 jours, a répondu, entretien.

Rien n'est collecté ni envoyé automatiquement (comptes LinkedIn bloqués, RGPD).

## Au quotidien

- **Lettres en Word** : sous chaque lettre générée, « ⬇️ Télécharger en Word (.docx) ».
  Renseigne une fois tes coordonnées dans l'onglet 🔎 Réglages (gardées sur ce PC).

- **« Pas intéressé »** : une petite fenêtre te demande pourquoi (trop commercial,
  trop loin...). Tes refus sont envoyés sur GitHub (`data/feedback.json`) et les
  filtres VIE, HelloWork, France Travail, APEC et LinkedIn écartent ensuite les offres du même genre.
  La première fois, Git peut te demander de te connecter à GitHub dans le navigateur.
- **Notes sur 10** : chaque offre reçoit une note dès qu'elle est trouvée. Les offres
  arrivées sans note sont notées automatiquement en arrière-plan à l'ouverture de
  l'application (gardé dans `data/notes_offres.json`).
- **Offres non traitées** : une offre restée « À regarder » 14 jours après sa
  première apparition dans l'application est masquée de la liste (interrupteur
  « Plus de 14 jours » pour la revoir). Ton
  Google Sheets n'est jamais modifié par ce tri.

- **Application** : icône « Mes candidatures » sur le bureau. L'onglet Activité
  permet de lancer une recherche LinkedIn tout de suite, de voir l'historique
  de tous les passages (VIE, HelloWork, LinkedIn) et le journal.
- **Recherche LinkedIn + APEC planifiée** : lun-ven à 12h05 et 19h05 (horaires modifiables dans `windows\schedule_task.ps1`), dans une
  fenêtre visible qui se ferme 30 secondes après la fin (ou au démarrage du PC
  si l'heure est passée). Journal : `logs\linkedin.log`.
- **Réglages** : `cdi_search.yaml`, modifiable sur GitHub. Le PC récupère les
  changements à chaque passage.
- **Mises à jour** : bouton « ⬆️ Mettre à jour l'application » dans la barre de gauche
  (il passe en bleu quand une nouvelle version a été téléchargée). L'application
  redémarre toute seule en une dizaine de secondes.
- **Arrêter le serveur de l'application** : `windows\stop_app.ps1`.
- **Tout désinstaller** : `powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1`
