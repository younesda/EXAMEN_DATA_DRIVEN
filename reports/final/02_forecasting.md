# 02 — Forecasting final

Deux décisions séparées, sans vainqueur global :

- **Prévision quotidienne : `CrostonOptimized`.**
- **Planification cumulée à 30 jours : `LightGBM_Tweedie`.**

| model            |    wape |       std |   daily_wins |        bias |   wape30 |   n_windows |
|:-----------------|--------:|----------:|-------------:|------------:|---------:|------------:|
| CrostonOptimized | 1.09452 | 0.0276115 |            4 | -0.0595882  | 0.369956 |           6 |
| MovingAverage28  | 1.09789 | 0.0221816 |            0 | -0.0245606  | 0.324067 |           6 |
| LightGBM_Tweedie | 1.10103 | 0.0279013 |            2 | -0.0256601  | 0.31057  |           6 |
| Naive            | 1.32566 | 0.0866417 |            0 | -0.0593922  | 1.07707  |           6 |
| SeasonalNaive7   | 1.36164 | 0.0400055 |            0 |  0.00722315 | 0.495252 |           6 |

## Fenêtres

Six fenêtres non chevauchantes de 30 jours sont évaluées. Les 546 jours disponibles laissent 366 jours avant la première fenêtre. Les trois fenêtres précédentes étaient un compromis de coût sur les 90 derniers jours; elles ont été réutilisées par checkpoint et seules les trois fenêtres supplémentaires ont été calculées.

## Intervalles conformes de CrostonOptimized

|   level | segment      |   coverage |   mean_width |     n |
|--------:|:-------------|-----------:|-------------:|------:|
|    0.8  | abc_a        |   0.782715 |      3.18118 | 28290 |
|    0.8  | global       |   0.815611 |      2.84054 | 54000 |
|    0.8  | intermittent |   0.815611 |      2.84054 | 54000 |
|    0.95 | abc_a        |   0.94567  |      5.11345 | 28290 |
|    0.95 | global       |   0.949519 |      4.74037 | 54000 |
|    0.95 | intermittent |   0.949519 |      4.74037 | 54000 |

Chaque quantile utilise exclusivement un bloc de calibration ou des fenêtres strictement antérieurs à la fenêtre évaluée. Les bornes inférieures sont tronquées à zéro.

## Garde-fous

- NaN ou infinis : 0.
- Prédictions négatives : 0.
- Cold-start observés : 0; repli défini : moyenne globale du train.
- Historiques de moins de 28 jours observés : 0; repli défini : moyenne disponible puis SeasonalNaive7.

Commande : `python -m src.pipelines.final_forecasting`.
