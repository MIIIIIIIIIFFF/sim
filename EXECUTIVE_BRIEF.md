# Overnight Edge — Résumé pour la direction

**Version :** 3.0.0
**Installation :** `OvernightEdgeSetup.exe` sur tout PC Windows 64 bits (pas de Python, pas d'administrateur)

## Question

Quelles valeurs du S&P 500 ont produit le plus haut **rendement overnight composé**
(achat au close 16 h 00 HE, vente à 09 h 29 HE le lendemain matin), et comment
les rangs et rendements ont-ils **changé depuis la veille** ?

## Flux quotidien

1. Ouvrir Overnight Edge (splash d'anniversaire en août, puis le scanner)
2. Laisser **Tickers** vide pour le S&P 500 complet
3. Cliquer **Lancer le scan du jour (S&P 500)** (~1 minute, internet requis)
4. Consulter le classement complet, la recherche, et l'onglet
   **Plus grands mouvements au quotidien**
5. Ouvrir le **rapport HTML** pour un tableau de bord présentable

Les snapshots sont dans `%APPDATA%\OvernightEdge`. Lancez une fois par jour de
bourse pour que Δ Rang / Δ Composé aient une veille à comparer. Les dates de
snapshot suivent le calendrier de marché US Eastern.

## Onglet « Analyse d'une valeur »

Étude d'un ticker précis sur une période choisie (5 / 10 / 15 / 30 dernières
nuits, tout l'historique, ou dates **Du / Au** exactes). Recalcule le coup par
coup et la courbe de capital composée. Compare aussi **Overnight vs Intraday
vs Buy & Hold** sur la même période et le même capital. Se met à jour
automatiquement au fil des jours de bourse.

## « Copier la Watchlist (TradingView) »

Bouton copiant la liste des tickers affichés dans le presse-papiers, à coller
dans TradingView (**Paste symbols**). Gain de temps quotidien immédiat.

## Historique long (accumulation + repli)

Yahoo limite les barres 5 minutes à ~60 jours. Pour les périodes plus longues :
accumulation locale des barres 5 min dans `<dossier d'installation>\bars_cache`
(précis, grandit chaque jour) + repli automatique sur barres quotidiennes
(~10 ans, marqué « Approximatif »). Permet des backtests sur plusieurs mois ou
années dans l'onglet « Analyse d'une valeur ».

## Onglet « Optimiseur jour / nuit »

Trouve **le meilleur créneau de temps achat/vente** pour une valeur ou pour tout
le S&P 500, en comparant deux familles :

- **Jour** : achat matin 09:30→10:30, vente après-midi 15:00→15:55 (25 combos)
- **Nuit** : achat after-hours 16:00→16:30, vente pré-ouverture 09:00→09:25 (30 combos)

Chaque créneau est classé par **rendement composé**. Deux **cercles animés**
montrent le **rendement par titre** : un point par ticker, **vert** = gain,
**rouge** = perte, **gris** ~zéro (rafraîchis ~1×/seconde pendant l'analyse,
animation des points une seule fois à la fin, fixes après). Univers au choix :
S&P 500 complet, un favori sauvegardé sur disque, ou un ticker libre ajouté à
la volée. Plage de dates 0–30 jours,
jusqu'à ~60 jours en arrière (5 min précis). Résultats par créneau et par
titre ; le **tableau de détail est triable** par colonne (clic d'en-tête,
sens conservé pendant l'optimisation). Optimisation simultanée **jour et
nuit**, par stock ou sur toute la liste. L'onglet est en deux sous-pages :
**① Listes de titres** (édition, pleine hauteur) et **② Optimiser**.

## Timing

Achat = dernière barre 5 minutes 09:30–16:00 HE. Vente = dernière barre
pré-marché 04:00–09:29 HE (typiquement 09:25). Composition = réinvestissement
complet chaque nuit.

## Notes Windows

Si SmartScreen apparaît : **Plus d'infos → Exécuter quand même**. Première
ouverture : 10–20 secondes. Taille de texte ajustable via **A+** / **A−**.

## Avertissement

Backtest de recherche. Pas un conseil en investissement. Pas de frais ni
slippage. Les résultats passés ne prédisent pas l'avenir.
