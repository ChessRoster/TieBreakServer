# -*- coding: utf-8 -*-
"""The truncation transform: cut a TRF to the results of rounds ``1..keep_rounds``
and recompute everything that has to stay consistent with that cut.

See ``PLAN-REGRESSION.md`` section 5 for the specification this module implements.
This is deliberately the only piece of real engineering in the interop sweep: a
truncation bug can manufacture a divergence on *both* sides of a comparison at
once, which is why it gets its own unit tests (``test_trftrunc.py``) and its own
self-validation gate (see the runner, step 4 of the plan's order of work).

Column arithmetic (record ``001``, zero-based Python slices), verified against
``trf2json.py`` and a real fixture:

    starting rank    line[4:8]
    points           line[80:84], written "%4.1f"
    rank             line[85:89]
    round r (1-based) round-block line[81+10*r : 89+10*r]; within it, opponent
                     is [81+10*r:85+10*r], colour is at 86+10*r, result at 88+10*r

Truncating a player line to the first k rounds is ``line[:89 + 10*k]``.

Points and rank are **not** just carried over truncated: bbpPairings verifies
that each player's declared score reconciles with their results under the
file's point system and refuses to proceed otherwise, so a stale points field
would be a hard stop rather than a subtle skew. Rather than reimplement FIDE
scoring, the recomputation goes through this repository's own TRF reader
(``trf2json.py`` / ``scoresystem.py``) so it stays correct if the score rules
are ever revised -- see ``_score_decimals`` below.
"""
import os
import sys
from decimal import Decimal

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers import parse_int  # noqa: E402
from trf2json import trf2json  # noqa: E402


class TruncationError(Exception):
    """Raised when a TRF cannot be truncated -- malformed input, not a normal
    engine outcome."""


def _score_decimals(trf_text):
    """Resolve the file's declared game-point system to a {trf-result-char:
    Decimal} table, by running the file through this repository's own TRF
    reader exactly as the real read path does. Falls back to the TRF-2026
    default score system (1 / 0.5 / 0, no record 162) if the file cannot be
    parsed for some reason unrelated to scoring -- callers that need a hard
    failure on unparseable input should read the file themselves first.
    """
    reader = trf2json()
    try:
        reader.parse_file(trf_text, False)
        tournament = reader.get_tournament(1)
        if tournament is None:
            raise TruncationError("no tournament in TRF")
        game_score = reader.scores.score.get("game")
        if not game_score:
            raise TruncationError("no game score system resolved")
        decimals = {}
        for char, meta in reader.results.items():
            category = meta["points"]
            decimals[char] = reader.scores.get_score(tournament, "game", category)
        return decimals
    except TruncationError:
        raise
    except Exception:
        # No record 162 in the file: the TRF-2026 default game score system
        # applies uniformly (see PLAN-REGRESSION.md section 2.4 -- the corpus
        # carries no 162 records at all). Resolve the same table trf2json
        # would have produced for that default, without needing a full parse.
        import scoresystem

        scores = scoresystem.scoresystem()
        default = scores.fill_default_scoresystem("game")
        trans = {}
        for result in ["W", "D", "L", "Z"]:
            trans[default[result]] = result
        for result in ["F", "H", "P", "A", "U"]:
            if isinstance(default[result], Decimal) and default[result] in trans:
                default[result] = trans[default[result]]
        scores.score["game"] = default
        decimals = {}
        for char, meta in reader.results.items():
            category = meta["points"]
            val = category
            while not isinstance(val, Decimal):
                val = default[val]
            decimals[char] = val
        return decimals


def _player_points(line, keep_rounds, decimals, extra_round=None):
    """Sum a player's points over rounds 1..keep_rounds from their own 001
    line, reading each round's result character directly (own-perspective:
    '1'/'='/'0'/'+'/'-'/... regardless of colour, exactly as trf2json reads
    it in parse_trf_game). If ``extra_round`` is given (the pair-round's own
    block was preserved by ``_pair_round_exemption_end`` because it carries a
    pre-declared exemption), its result is included too: this repository's
    own reader (scoresystem.py's "Incorrect score for player" check) sums
    every result character present anywhere in the line, not just those
    through the current round, so a preserved exemption's points must be
    folded into the declared total or the file fails to reconcile even
    though the exemption itself is legitimately there."""
    total = Decimal("0.0")
    rounds = list(range(1, keep_rounds + 1))
    if extra_round is not None:
        rounds.append(extra_round)
    for r in rounds:
        pos = 88 + 10 * r
        if pos >= len(line):
            continue
        ch = line[pos].upper()
        if ch == " " or ch == "":
            continue
        total += decimals.get(ch, Decimal("0.0"))
    return total


def _compute_ranks(startnos, points):
    """Standard competition ("1224") ranking by descending recomputed points,
    ties broken by starting rank for determinism. The pairing engine itself
    never reads this field back in -- see pairingdutch.py, which computes its
    own scorelevels from results, not from record 001's rank column -- so this
    exists purely to keep the file internally consistent for engines (like
    bbpPairings) that do read it."""
    ordered = sorted(startnos, key=lambda sn: (-points[sn], sn))
    ranks = {}
    prev_points = None
    prev_rank = 0
    for i, sn in enumerate(ordered, start=1):
        if points[sn] != prev_points:
            prev_rank = i
            prev_points = points[sn]
        ranks[sn] = prev_rank
    return ranks


def _pair_round_exemption(line, keep_rounds):
    """Column layout keeps round r's own block -- opponent [81+10r:85+10r],
    colour at 86+10r, result at 88+10r -- at a *fixed* absolute position
    regardless of how many earlier rounds are kept, so a not-yet-played round
    can still carry real data there: a pre-declared exemption (a requested or
    forced bye, opponent ``0000`` with a non-blank result code) known and
    written into the file before the round is paired, exactly like records
    250/260 which section 5 point 5 already leaves untouched because pairing
    the round needs them. Round `pair_round` = keep_rounds + 1 is the round
    about to be paired, so its own block is the only one that can carry such
    a signal for *this* truncation -- rounds after it are not being paired
    yet and are dropped along with everything else beyond keep_rounds.

    Opponent ``0000`` alone is not enough to tell a pre-declared exemption
    apart from the *output* of pairing round `pair_round` itself: result code
    ``U`` is the pairing-allocated bye (C.04.7/A.4 -- exactly the answer this
    round's pairing is being asked to produce, not a fact known in advance of
    it) and ``+`` is a forfeit win, and bbpPairings' own reader
    (fileformats/trf.cpp: `participatedInPairing = opponent != id ||
    resultChar == 'U' || resultChar == '+'`) treats both as advancing how
    many rounds the file has "played", so preserving either one makes
    bbpPairings believe round `pair_round` already happened and pair the
    round *after* it instead -- a comparison-methodology bug that manufactures
    a divergence on top of a genuine one, confirmed empirically: excluding
    them turned 120/120 sampled PAIRING-class divergences into MATCH with no
    effect on 120/120 sampled MATCH controls. ``H`` (half-point bye) and
    ``Z`` (zero-point bye) remain genuine pre-declared exemptions and are
    preserved -- bbpPairings' own eligibleForBye() check confirms they do not
    advance playedRounds.

    A played game never has opponent ``0000`` (a real opponent is a positive
    startno), so opponent == "0000" with a non-blank, non-U/+ result is
    unambiguous: it cannot be "a result that legitimately shouldn't exist
    yet", because a real game does not go in that slot. Returns ``(end_col,
    extra_round)``: ``end_col`` is where to cut the line (89 +
    10*keep_rounds if no exemption, else 89 + 10*pair_round to include the
    exemption block), and ``extra_round`` is ``pair_round`` when the block
    was kept, else ``None`` -- callers need this to fold the exemption's
    points into the recomputed total (see _player_points), since this
    repository's own reader sums every result character present in the
    line, not just those through keep_rounds."""
    pair_round = keep_rounds + 1
    block_start = 81 + 10 * pair_round
    block_end = 89 + 10 * pair_round
    default_end = 89 + 10 * keep_rounds
    if len(line) < block_end:
        return default_end, None
    opponent = parse_int(line[block_start : block_start + 4])
    result = line[block_end - 1].upper()
    if opponent == 0 and result.strip() != "" and result not in ("U", "+"):
        return block_end, pair_round
    return default_end, None


def _rewrite_player_line(line, keep_rounds, points, ranks):
    startno = parse_int(line[4:8])
    pts = points[startno]
    rank = ranks[startno]
    rewritten = line[:80] + f"{pts:4.1f}" + " " + f"{rank:>4}" + line[89:]
    end_col, _ = _pair_round_exemption(line, keep_rounds)
    return rewritten[:end_col]


def _truncate_320(line, keep_rounds):
    # Record 320 (PAB byes) carries one 4-column slot per round, starting at
    # column 17 with a 3-digit competitor number, one slot per round from
    # round 1 (see trf2json.parse_trf_pab: the loop walks 4-char strides from
    # offset 17, incrementing an implicit round counter every stride,
    # regardless of whether that round's slot is blank). Keeping only rounds
    # 1..keep_rounds is therefore a straight character truncation to
    # 13 + 4*keep_rounds -- 13 is the end of the gamePoints column (line[9:13])
    # that precedes the per-round slots.
    return line[: 13 + 4 * keep_rounds]


def truncate(trf_text, keep_rounds):
    """Truncate ``trf_text`` to the declared results of rounds 1..keep_rounds
    and return the resulting TRF text. See PLAN-REGRESSION.md section 5.

    keep_rounds == 0 drops every round's results (an all-byes-unpaired file).
    keep_rounds == the tournament's full round count is the identity
    transform: every recomputed field should equal the input's own.
    """
    if keep_rounds < 0:
        raise ValueError("keep_rounds must be >= 0, got %r" % (keep_rounds,))

    newline = "\r\n" if "\r\n" in trf_text else "\n"
    normalised = trf_text.replace("\r\n", "\n")
    trailing_newline = normalised.endswith("\n")
    lines = normalised.split("\n")
    if trailing_newline:
        lines = lines[:-1]

    decimals = _score_decimals(trf_text)

    # Pass 1: recompute every player's points from the surviving rounds only.
    startnos = []
    points = {}
    for line in lines:
        if line[:3] == "001":
            startno = parse_int(line[4:8])
            startnos.append(startno)
            _, extra_round = _pair_round_exemption(line, keep_rounds)
            points[startno] = _player_points(line, keep_rounds, decimals, extra_round)
    ranks = _compute_ranks(startnos, points)

    # Pass 2: rewrite record 001 (points, rank, round columns) and filter or
    # truncate the per-round records. Record 142 (scheduled round count) is
    # deliberately left untouched -- see PLAN-REGRESSION.md section 5 point 4:
    # Baku acceleration and several C.04 provisions key off the tournament's
    # *scheduled* length, not how many rounds have been played. 152, 192, 162,
    # 250 and 260 are likewise untouched (section 5 point 5).
    out = []
    for line in lines:
        prefix = line[:3]
        if prefix == "001":
            out.append(_rewrite_player_line(line, keep_rounds, points, ranks))
        elif prefix == "240":
            # Bye section HPB/FPB: round is line[6:9].
            if parse_int(line[6:9]) <= keep_rounds:
                out.append(line)
        elif prefix == "300":
            # Out-of-order records: round is line[4:7].
            if parse_int(line[4:7]) <= keep_rounds:
                out.append(line)
        elif prefix == "320":
            out.append(_truncate_320(line, keep_rounds))
        elif prefix == "330":
            # Forfeited matches: round is line[7:10].
            if parse_int(line[7:10]) <= keep_rounds:
                out.append(line)
        else:
            out.append(line)

    text = newline.join(out)
    if trailing_newline:
        text += newline
    return text
