# Overnight Edge — pour Simon (et l'équipe)

**Version :** 2.7.0
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
