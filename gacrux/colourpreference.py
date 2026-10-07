# -*- coding: utf-8 -*-
"""C.04.3 art. 1.7 colour preferences for individual Swiss tournaments.

Shared by crosstable_dutch.color_preference and an explicitly requested Dutch
COP listing (tiebreak.compute_cop). Generic score preparation builds COD and CSQ;
other pairing systems use their own colour-preference rules.

The result gives the colour and strength:
    "w2" / "b2" - absolute, art. 1.7.1
    "w1" / "b1" - strong, art. 1.7.2
    "w0" / "b0" - mild, art. 1.7.3
    "nc"        - no preference, art. 1.7.4

cod is games played with White minus games played with Black (art. 1.6).
csq is the played colour sequence. Callers exclude unplayed games and games
without an opponent, as required by C.04.2 art. 3.4.

The definitions in art. 1.7 can overlap. A player with history bbww has zero
colour difference: art. 1.7.1 gives an absolute preference for Black, while
art. 1.7.3 gives a mild preference for Black. The strength affects allocation
under art. 5.2.2, which grants the stronger preference.

This function preserves the engine's precedence: the first matching definition
in article order wins, so bbww has an absolute preference. The article does not
explicitly resolve the overlap. C.04.6 has a similar overlap, but its team
strengths differ and remain in crosstable_fideteam.color_preference.
"""


def color_preference(cod, csq):
    """The colour preference of a player with colour difference *cod* and history *csq*."""
    # C.04.3 art. 1.7.1: "The preference is for White when the colour difference is less
    # than -1 OR when the last two games were played with Black." The second clause is
    # unconditional on the colour difference. Gating it at cod <= 0 (resp. cod >= 0) drops
    # the |cod| == 1 cases, which then fall through to art. 1.7.2 and come back as a STRONG
    # preference for the OPPOSITE colour -- e.g. a player with the colour history wwwbb
    # (cod = +1, last two Black) has an absolute preference for White by 1.7.1, but was
    # returned "b1". Widening to cod <= 1 / cod >= -1 covers them.
    #
    # cod >= +2 with the last two games Black (and its mirror) is left resolving by the
    # colour difference, as before: there art. 1.7.1 asserts BOTH preferences, and the
    # article does not say which wins.
    if cod <= -2 or cod <= 1 and csq[-2:] == "bb":
        return "w2"
    elif cod >= 2 or cod >= -1 and csq[-2:] == "ww":
        return "b2"
    elif cod == -1:
        return "w1"
    elif cod == 1:
        return "b1"
    elif csq[-1:] == "b":
        return "w0"
    elif csq[-1:] == "w":
        return "b0"
    return "nc"
