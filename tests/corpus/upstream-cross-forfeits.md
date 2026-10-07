# Cross-forfeited team draws

Upstream commit c9d84ab counts a match as played when both teams score game
points, including a match whose boards all end by forfeit. The corpus previously
built the following fixtures without counting those matches in the played-match
and colour histories:

- `team_0142`: round 2, teams 8 and 2, opposite forfeit winners on the two boards.
  Including that drawn match changes prescribed colours in rounds 3 and 6 and
  prescribed opponents in round 4.
- `team_0172`: round 7, teams 11 and 10, opposite forfeit winners on the two boards.
  Including that drawn match changes the round 8 bye, opponents and colours.

Their original TRF records are retained. Both fixtures are now labelled invalid
because their later declared pairings differ from the current upstream engine.
This records upstream's changed cross-forfeit interpretation; it does not resolve
how an all-forfeit draw should be classified under C.04.6.

PR #10 now separates result-bearing matches from actual board play. The public
`played` value and standings treatment are retained; C.04.6 colour history,
initial-colour recovery, encounter history, bye priority and float history use
actual board play. This fixes every round of the original issue #23 attachment.

In the team feature overlay, `team_0142` is consequently valid again: both
pairing and tie-break checks return 0. Only its verdict field changes; its TRF
text is unchanged. `team_0172` also passes the pairing check, but still fails
its declared Board Count standings, so it remains invalid.

`team_0256` remains invalid: its seventh round leaves teams 2 and 6 unpaired in
addition to the pairing-allocated bye. The actual-play correction removes its
earlier round-5 rejection, exposing the old checker fallback that incorrectly
accepts the incomplete seventh round. It therefore returns to the team feature's
known failures. PR #9 removes that fallback and correctly rejects the file;
its status-code overlay removes this expected failure in the combined branch.

The shared corpus retains the upstream verdicts for branches without this fix.
