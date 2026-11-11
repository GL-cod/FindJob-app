# Installer « Mes candidatures » pour toi

Ce guide est pour toi si quelqu'un t'a passé cette application et que tu veux ta propre version, avec **ton** profil, **tes** offres et **ton** suivi. Compte environ 45 minutes la première fois. Tu n'as pas de code à écrire.

## Ce que fait l'application

- Elle cherche toute seule des offres de CDI sur HelloWork (depuis GitHub), sur LinkedIn et sur l'APEC (depuis ton PC), et en option des offres de VIE.
- Gemini, l'IA gratuite de Google, lit chaque offre et la compare à ton profil. Il donne une note sur 10, conseille le CV à envoyer et écarte ce qui ne te correspond pas.
- Une application sur ton PC regroupe tout : ouvrir l'offre, « J'ai postulé », « Pas intéressé » (l'application apprend de tes refus), lettre de motivation en Word, préparation d'entretien, statistiques.
- En option, elle se relie à un Google Sheets de suivi de tes candidatures et à un onglet Réseau pour tes prises de contact.

Elle ne postule **jamais** à ta place. C'est toi qui ouvres l'offre et qui envoies ta candidature.

## Ce qu'il te faut

- Un PC **Windows 10 ou 11**.
- Un compte **GitHub** (gratuit) : https://github.com/signup
- Un compte **Google** (pour Gemini et, si tu veux, Google Sheets).
- Un texte qui décrit ton profil. Prépare-le à l'avance (voir l'étape 3).

---

## Étape 1 : copier le dépôt sur ton GitHub

1. Connecte-toi à GitHub, puis ouvre https://github.com/GL-cod/FindJob
2. Clique sur **Fork** en haut à droite, puis sur **Create fork**. Tu as maintenant ta copie : `https://github.com/TON-PSEUDO/FindJob`.
3. Dans **ta** copie, ouvre l'onglet **Actions**. GitHub affiche un message sur les workflows d'un fork : clique sur le bouton vert **I understand my workflows, go ahead and enable them**.

> Ta copie est publique, comme l'original. Les offres trouvées et les raisons de tes refus y sont visibles. Ton profil, ta clé Gemini, ton nom, ton téléphone et ton e-mail, eux, ne sont jamais publiés : ils restent dans les secrets GitHub ou sur ton PC.

## Étape 2 : repartir de zéro

Ta copie contient encore les offres et les réglages de la personne qui t'a passé l'application. Pour les effacer :

1. Onglet **Actions**, puis **Première installation** dans la colonne de gauche.
2. Clique sur **Run workflow**, tape `OUI` en majuscules, puis clique sur le bouton vert **Run workflow**.
3. Attends la coche verte (environ 30 secondes).

## Étape 3 : ta clé Gemini et ton profil

**Clé Gemini.** Ouvre https://aistudio.google.com/apikey, connecte-toi avec ton compte Google, clique sur **Create API key** et copie la clé. Elle est gratuite.

**Ton profil.** C'est le texte que Gemini lit pour juger les offres. Plus il est précis, meilleur est le tri. Écris-le en français, par exemple dans le Bloc-notes :

- ton diplôme, ton école et l'année ;
- tes stages et expériences : où, combien de temps, ce que tu as fait concrètement ;
- tes compétences : outils, logiciels, langages, méthodes ;
- tes langues ;
- les postes que tu cherches et ceux dont tu ne veux pas ;
- la région, et si tu acceptes le télétravail ou les déplacements.

Garde ce texte sous la main : tu vas le coller deux fois, sur GitHub puis sur ton PC.

## Étape 4 : mettre ta clé et ton profil sur GitHub

Dans ta copie : **Settings**, puis **Secrets and variables**, puis **Actions**.

Dans l'onglet **Secrets**, clique sur **New repository secret** et ajoute :

| Name | Secret |
| --- | --- |
| `GEMINI_API_KEY` | ta clé Gemini |
| `CDI_USER_DESCRIPTION` | ton profil (tout le texte) |

Si tu veux aussi les offres de **VIE**, va dans l'onglet **Variables**, clique sur **New repository variable**, et crée `USER_DESCRIPTION` avec ton profil (voir l'étape 9).

## Étape 5 : régler ta recherche

Toujours sur GitHub, ouvre le fichier **`cdi_search.yaml`** de ta copie et clique sur le **crayon** pour le modifier. Les lignes qui commencent par `#` sont des explications.

À changer en priorité :

- **`keywords`** : les intitulés de postes que tu cherches, un par ligne, précédés de `  - ` (deux espaces, un tiret, un espace). Mets-en 5 à 15. Exemple :
  ```yaml
  keywords:
    - chargé de communication
    - community manager
    - chef de projet marketing junior
  ```
- **`candidat` → `metiers`** : tes domaines, en une phrase. Exemple : `"la communication, le marketing digital ou l'événementiel"`.
- **`candidat` → `cvs`** : tes CV. Si tu n'en as qu'un, laisse `principal`. Si tu en as deux ou plus (par exemple un CV technique et un CV gestion de projet), décris chacun. L'application te dira lequel envoyer pour chaque offre.
- **`excluded_title_words`** et **`excluded_domains`** : ce que tu ne veux surtout pas voir.
- **`max_experience_years`** : les offres qui demandent plus d'années d'expérience que ce chiffre sont écartées (3 par défaut).
- **`candidat` → `reseau`** : les mots-clés utilisés pour chercher des contacts sur LinkedIn dans l'onglet Réseau.

**Ta région.** Le fichier est réglé sur l'**Île-de-France**. Si tu cherches ailleurs :

- `hellowork` → `location` : écris ta ville ou ta région (exemple : `Lyon`).
- `linkedin` → `geo_id` : fais une recherche d'emploi sur LinkedIn dans ta région. L'adresse de la page contient `geoId=` suivi d'un nombre : c'est ce nombre.
- `apec` → `lieu` : fais une recherche sur apec.fr en choisissant ta région, puis recopie le code de lieu qui apparaît dans l'adresse de la page.

Ne mets **ni téléphone ni e-mail** dans ce fichier, il est public. Ton nom, tu le mettras sur le PC à l'étape 7.

Clique ensuite sur **Commit changes…**, puis encore sur **Commit changes**.

**Premier test sur GitHub :** onglet **Actions**, puis **CDI Watcher**, puis **Run workflow** et **Run workflow**. Le premier passage prend quelques minutes. Ensuite, la recherche HelloWork se lance toute seule vers 12h et 19h en semaine.

## Étape 6 : installer Python et Git sur ton PC

Ouvre **PowerShell** : touche Windows, tape `powershell`, puis Entrée. Colle ces deux lignes, une par une :

```powershell
winget install -e --id Python.Python.3.13
winget install -e --id Git.Git
```

Accepte ce que Windows te demande, puis **ferme et rouvre PowerShell**.

## Étape 7 : installer l'application

Dans PowerShell, colle ces lignes en remplaçant `TON-PSEUDO` par ton nom d'utilisateur GitHub :

```powershell
git clone https://github.com/TON-PSEUDO/FindJob "$HOME\FindJob"
cd "$HOME\FindJob"
powershell -ExecutionPolicy Bypass -File windows\setup.ps1
```

Le script te guide en 7 étapes :

1. Il vérifie Python.
2. Il installe ce dont l'application a besoin (quelques minutes).
3. Il te demande ta **clé Gemini** et ton **prénom et nom**, qui servent à signer tes lettres. Les deux restent sur ton PC.
4. Il ouvre le **Bloc-notes** : efface la phrase écrite, colle ton profil (le même qu'à l'étape 4), enregistre avec Ctrl+S et ferme le Bloc-notes.
5. Il propose de relier un **Google Sheets** (facultatif, voir l'étape 8). Tu peux répondre `N` et le faire plus tard en relançant le script.
6. Il crée la **recherche LinkedIn + APEC automatique**, du lundi au vendredi à 12h05 et 19h05. Une fenêtre s'ouvre pendant la recherche et se ferme toute seule. Si le PC est éteint à cette heure-là, la recherche se lance au démarrage suivant.
7. Il crée l'icône **Mes candidatures** sur le bureau.

À la fin, il propose une première recherche LinkedIn (réponds `O`), puis il ouvre l'application.

> Si Windows affiche « l'exécution de scripts est désactivée », vérifie que tu as bien copié la ligne entière avec `-ExecutionPolicy Bypass`.

Dans l'application, va dans l'onglet **🔎 Réglages** et complète tes coordonnées (téléphone, e-mail, ville, LinkedIn). Elles servent pour les lettres en Word et restent sur ton PC.

## Étape 8 (facultatif) : relier un Google Sheets de suivi

Le Sheets garde la liste de tes candidatures (Poste, Entreprise, Lien, Date, Retour, Commentaire). Quand tu cliques sur « J'ai postulé », la ligne s'ajoute toute seule.

À l'étape 5 du script, réponds `O`. Un Google Sheets vierge s'ouvre (renomme-le « Suivi candidatures »). Le code à coller est déjà copié.

1. Dans le Sheets, ouvre **Extensions**, puis **Apps Script**.
2. Efface tout le code, puis colle avec **Ctrl+V**.
3. Remplace `COLLE_ICI_TON_CODE_SECRET` par le code que PowerShell affiche en jaune. Garde les apostrophes autour.
4. Enregistre (icône disquette), puis **Déployer**, puis **Nouveau déploiement**. Clique sur la roue dentée et choisis **Application Web**. Mets *Exécuter en tant que : Moi* et *Qui a accès : **Tout le monde***, puis clique sur **Déployer**.
5. Google demande une autorisation. Choisis ton compte. Si Google affiche « Google n'a pas validé cette application », c'est normal (c'est ton propre script) : clique sur **Paramètres avancés**, puis sur **Accéder à … (non sécurisé)**, puis sur **Autoriser**.
6. Copie l'**URL de l'application Web** (elle finit par `/exec`) et colle-la dans PowerShell.

Le script vérifie le lien et affiche « OK » si tout marche.

**Onglet 🤝 Réseau (facultatif) :** il utilise un **deuxième** Google Sheets. Ouvre l'onglet dans l'application : il t'affiche le script à coller (le code secret est déjà rempli) et te guide de la même façon.

## Au quotidien

- **Ouvrir l'application** : icône **Mes candidatures** sur le bureau.
- **📋 Offres** : les nouvelles offres, de la meilleure note à la moins bonne. Pour chacune :
  - « ↗ Ouvrir l'offre » ;
  - « ✅ J'ai postulé » ;
  - « ❌ Pas intéressé » : dis pourquoi, et Gemini écartera ensuite les offres du même genre ;
  - lettre de motivation (téléchargeable en Word) et préparation d'entretien.
- Une offre que tu n'as pas traitée en 14 jours disparaît de la liste.
- **⚙️ Activité** : lancer une recherche LinkedIn tout de suite, voir l'historique des passages.
- La première fois que tu cliques sur « Pas intéressé », Git peut te demander de te connecter à GitHub dans le navigateur. Accepte : c'est ce qui envoie tes refus à la recherche sur GitHub.
- Pour changer tes mots-clés plus tard, modifie `cdi_search.yaml` sur GitHub (étape 5). Ton PC récupère le changement au passage suivant.

## Étape 9 (facultatif) : les offres de VIE

Si tu veux aussi les VIE (Business France) :

1. Ajoute la variable `USER_DESCRIPTION` (voir l'étape 4).
2. GitHub ne lance pas ce workflow tout seul de façon fiable. Fais-le déclencher par **cron-job.org** (gratuit) :
   - Crée un jeton GitHub : photo de profil, puis **Settings**, **Developer settings**, **Personal access tokens**, **Fine-grained tokens**, et **Generate new token**. Pour *Repository access*, choisis *Only select repositories* et ton dépôt FindJob. Dans *Permissions*, mets *Actions* sur **Read and write**. Fixe une date d'expiration et note-la. Copie le jeton, GitHub ne l'affiche qu'une fois.
   - Sur https://cron-job.org, crée un cronjob avec l'URL `https://api.github.com/repos/TON-PSEUDO/FindJob/actions/workflows/watch.yml/dispatches`.
   - Dans la planification personnalisée (crontab), mets `7 8-20 * * 1-5` et choisis le fuseau `Europe/Paris`.
   - Dans les réglages avancés, choisis la méthode **POST** et mets le corps `{"ref":"main"}`.
   - Ajoute ces en-têtes :
     ```
     Accept: application/vnd.github+json
     Authorization: Bearer TON-JETON
     X-GitHub-Api-Version: 2022-11-28
     Content-Type: application/json
     User-Agent: vie-watcher-cron
     ```
   - Clique sur **Test run** : la réponse doit être `204 No Content`.

Le README du dépôt détaille cette partie si besoin (section « Set up the schedule with cron-job.org »).

## Recevoir les mises à jour

Quand la personne qui t'a passé l'application l'améliore :

1. Sur GitHub, dans ta copie, ouvre **Actions**, puis **Mettre à jour depuis l'original**, puis **Run workflow** et **Run workflow**. Le workflow récupère le nouveau code sans toucher à tes offres ni à tes réglages.
2. Dans l'application, clique sur **⬆️ Mettre à jour l'application** dans la barre de gauche.

N'utilise **pas** le bouton « Sync fork » de GitHub : il mélangerait tes offres avec celles de l'original.

## En cas de souci

| Problème | Solution |
| --- | --- |
| L'icône ne fait rien ou affiche une erreur | Lis le message. Le journal est dans `FindJob\logs\app_server_err.log`. Relancer `windows\setup.ps1` répare la plupart des cas. |
| Aucune offre | Vérifie dans **Actions** que **CDI Watcher** a une coche verte, et que tes mots-clés ne sont pas trop rares. |
| « Missing environment variables » sur GitHub | Le secret `GEMINI_API_KEY` ou `CDI_USER_DESCRIPTION` manque (étape 4). |
| Trop d'offres hors sujet | Précise ton profil (secret GitHub **et** `profile_cdi.txt` sur le PC), et utilise « Pas intéressé » avec une raison. |
| LinkedIn renvoie 0 offre | LinkedIn bloque parfois. Réessaie plus tard depuis l'onglet ⚙️ Activité. |
| Arrêter la recherche | GitHub : **Actions**, choisis un workflow, puis **⋯** et **Disable workflow**. PC : `powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1` |

Pour lancer du Python à la main sur le PC, utilise `.venv\Scripts\python.exe` : le `python` de Windows n'a pas les modules de l'application.
