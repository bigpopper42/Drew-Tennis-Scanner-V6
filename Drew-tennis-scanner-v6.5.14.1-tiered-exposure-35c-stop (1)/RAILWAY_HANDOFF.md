# Railway Handoff — Version 6.5.14

Deploy the flat-root repository to the existing Railway service. Preserve V6.5.13 as the rollback point.

Production values are locked in code:

- worker cycle: **15 seconds**
- one-break target exposure: **15%**
- two+ break target exposure: **25%**
- backed-outcome stop trigger: **35¢**

A qualifying one-break position can be increased after a two+ break upgrade, but only by the amount required to reach the 25% total target. Repeat signals cannot stack beyond that target.
