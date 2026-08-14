# Version 6.5.14.2 Qualification and Consolidation Rules

## Qualification volatility hard gate

A live event is treated as qualifying when API Tennis sets `event_qualification` true or the tournament/round text contains qualifying/qualification wording.

For qualifying matches only:

- backed ATP rank **1-150**: opponent ranking does not matter;
- backed ATP rank **151-200**: opponent must be ranked **450 or worse** (ATP #450+);
- backed ATP rank **201-250**: opponent must be ranked **750 or worse** (ATP #750+);
- backed ATP rank **251 or worse**: NO TRADE;
- missing backed-player ranking: NO TRADE;
- missing opponent ranking is allowed only for backed players ranked 1-150; for backed ranks 151-250 it blocks because the required opponent cutoff cannot be verified.

Main-draw ATP Tour and Challenger matches are not rejected by this qualifier-specific ranking gate.

## Fresh one-break consolidation

The existing one-break maturity rule remains: four current-set games are required if the backed player has not been broken in the set, and five are required if they have been broken once.

Version 6.5.14.2 retains the second hard confirmation when the most recently completed game is the break that creates the current one-break lead:

- fresh break with the backed player now on 4 games: while serving for game 5, they must reach 40-0;
- fresh break with the backed player now on 5 games: while serving for game 6, they must reach 30-0.

Point-by-point history is used so the threshold remains satisfied after it has been reached even if the visible score later moves to 40-15, etc.

Two-break leads retain their existing maturity behavior.
