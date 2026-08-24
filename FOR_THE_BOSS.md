# Overnight Edge — pour Simon (et l'équipe)

**Version :** 3.0.0
**Installateur Windows :** `OvernightEdgeSetup.exe`

Double-cliquez-le. Pas de Python. Pas de droits administrateur. Il s'installe
dans le profil de l'utilisateur, puis crée des raccourcis dans le menu
Démarrer et sur le Bureau.

Si Windows SmartScreen affiche « Windows a protégé votre PC » : cliquez
**Plus d'infos**, puis **Exécuter quand même**. L'application n'est pas signée ;
cet avertissement est normal.

Après installation, ouvrez **Overnight Edge**. En **août** seulement, une courte
animation d'anniversaire apparaît (**Bonne fête Simon 2026**) — cliquez
**Continuer** (ou Entrée / Échap). À partir de septembre, l'application
s'ouvre directement.

---

## Ce que l'outil fait chaque jour

1. **Achat** au close de la séance (16 h 00 heure de New York)
2. **Vente** à 09 h 29 le lendemain matin (pré-ouverture)
3. **Composition** de 100 % du capital chaque nuit
4. **Classement** du S&P 500 complet
5. **Comparaison** avec le scan de la veille : Δ Rang et Δ Composé %

Lancez-le une fois par jour de bourse. L'historique est stocké dans :

`%APPDATA%\OvernightEdge\history`

Les rapports (ouvrent dans Excel ou un navigateur) :

`%APPDATA%\OvernightEdge\output`

Relancer le même jour **écrase** le snapshot de ce jour. C'est le scan du
**lendemain** qui active les colonnes de variation vs la veille.

La première ouverture de l'application installée peut prendre 10–20 secondes
le temps que Windows la décompresse. Ensuite c'est plus rapide.

Taille du texte : boutons **A+** / **A−** en haut à droite si besoin.

---

## Comment installer sur un autre PC

1. Copiez `OvernightEdgeSetup.exe` (ou tout le dossier `GiveToBoss`)
2. Double-cliquez le setup (aucun droit administrateur requis)
3. Lancez depuis le raccourci du Bureau

Option portable : `OvernightEdge.exe` seul fonctionne aussi (les données vont
dans `%APPDATA%`).

Si un scan échoue silencieusement, ouvrez :

`%APPDATA%\OvernightEdge\crash.log`

---

## Onglet « Analyse d'une valeur »

Outre le classement quotidien, l'onglet **Analyse d'une valeur** permet
d'étudier un ticker précis sur une période choisie :

- Périodes rapides : 5 / 10 / 15 / 30 dernières nuits, ou tout l'historique
- **Ou** dates exactes **Du / Au** au format AAAA-MM-JJ
- Bouton **Analyser** : télécharge les barres 5 min et recalcule le coup par
  coup (achat, vente, rendement par nuit, courbe de capital composée)

Le même onglet compare aussi **Overnight vs Intraday vs Buy & Hold** sur la
même période et le même capital de départ (tableau en bas) : Overnight
(16:00 → 09:29, composé), Intraday (09:30 → 16:00), Buy & Hold (1er open →
dernier close). La meilleure stratégie est surlignée.

Revenir un autre jour de bourse et relancer le même ticker : « N dernières
nuits » inclut automatiquement les nouvelles nuits ; une plage de dates fixe
reste figée. L'outil se met à jour au fil des jours.

## « Copier la Watchlist (TradingView) »

Bouton en haut à droite : copie la liste des tickers affichés (ordre + filtre
du champ « Rechercher ») dans le presse-papiers → à coller dans TradingView
via **Paste symbols**.

## Historique long (accumulation locale + repli quotidien)

Yahoo limite les barres 5 minutes à ~60 jours. Pour aller plus loin :

- **Accumulation locale** : chaque scan sauvegarde les barres 5 min dans
  `<dossier d'installation>\bars_cache` (à côté de `OvernightEdge.exe`).
  La fenêtre précise grandit chaque jour.
- **Repli quotidien** : pour une période > 60 jours, l'outil utilise les barres
  quotidiennes (~10 ans) : achat = close du jour T, vente = open du jour T+1.
  Résultat marqué **« Approximatif »** (pas de vrai pré-marché 09:29).

L'onglet « Analyse d'une valeur » accepte des dates **Du / Au** éloignées ;
le badge « Précis » / « Approximatif » indique la source. Le tableau Overnight
vs Intraday vs Buy & Hold devient pertinent sur 1-5 ans.

---

## Onglet « Optimiseur jour / nuit » ⚖

Un outil graphique neuf pour trouver **le meilleur moment d'achat et de vente**
pour un titre — ou pour tout le S&P 500 — en comparant les deux familles de
créneaux :

| Famille | Achat | Vente | Combos |
|---------|-------|-------|--------|
| **Jour** | matin 09:30 → 10:30 | après-midi 15:00 → 15:55 | 25 |
| **Nuit** | après-clôture 16:00 → 16:30 | pré-ouverture 09:00 → 09:25 | 30 |

Chaque créneau est évalué **par le rendement composé** (100 % réinvesti à
chaque cycle, exactement comme le scan principal). L'optimiseur maximise ce
rendement pour choisir le meilleur créneau **jour** et le meilleur créneau
**nuit**.

**Deux cercles animés** reportent le **rendement par titre** : un point par
ticker, **vert** au-dessus de zéro (rendement positif), **rouge** en-dessous
(perte), **gris** ~zéro, taille du point proportionnelle à l'ampleur du
rendement — on voit d'un coup d'œil quels titres gagnent et lesquels perdent.
Pendant l'analyse les cercles se rafraîchissent environ **une fois par seconde**
(sans saccade) ; l'animation des points un par un se joue une seule fois à la
fin (les cercles restent **fixes** après l'optimisation, sans bug ni boucle).

Comment l'utiliser :
1. **« Jours à remonter (0–30) »** : taille de la fenêtre (0 → dernière semaine).
2. **« Jusqu'au »** : date de fin AAAA-MM-JJ (au plus ~60 jours en arrière pour le
   pré-marché précis 5 min).
3. **Univers** : `S&P 500 complet`, un favori sauvegardé, ou `Liste libre`.
4. **Ticker libre + Ajouter** : ajoute un titre hors liste (même non présent
   dans le S&P 500) → il est téléchargé puis intégré à l'optimisation.
5. Cliquez **Optimiser**.

L'onglet est organisé en **deux sous-pages** :
- **① Listes de titres** : créez / éditez vos listes (pleine hauteur).
- **② Optimiser** : plage de dates, mode, bouton, bannières de résultats, cercles
  et tableau de détail.

Résultats :
- **Bannières** : meilleur créneau Jour et Nuit (achat → vente, composé %).
- **Cercles** : répartition profit / perte de chaque famille.
- **Détail par titre** : le meilleur créneau de chaque titre, son composé et
  son taux de gain. **Cliquez un en-tête de colonne pour trier** (Titre, Famille,
  Créneau, Composé %, Taux de réussite) ; recliquez pour inverser. Le tri est
  conservé pendant toute l'optimisation.
- Chaque jour et chaque titre se voient ainsi sous l'angle de la fenêtre de
  temps choisie, pour un terminal en direct (risque de composition intra-jour).

Les créneaux de **Jour** n'achètent que pendant les heures de marché normales
(09:30 → 10:30) ; les créneaux de **Nuit** n'achètent qu'à la clôture /
after-hours (16:00 → 16:30) et ne vendent qu'en pré-ouverture (09:00 → 09:25).

Les favoris sont sauvegardés sur disque (`%APPDATA%\OvernightEdge\optimizer_favorites.json`)
et retrouvés au prochain lancement.

---

## Composition (le chiffre qui classe)

Ce n'est **pas** la somme des pourcentages journaliers.

`10 000 $ × (1+r1) × (1+r2) × …`
Exemple : +2 % puis +3 % → **10 506 $ (+5,06 %)**, pas +5,00 %.

- **Gains %** = fréquence des nuits positives (sur les N nuits de la fenêtre).
- **Tirage max** = plus forte baisse de la courbe de capital composée (peak → creux).
- **Composé %** = rendement total composé : capital final / capital initial − 1.

---

Bonne fête Simon 2026.
