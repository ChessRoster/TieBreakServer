"""Original issue #17 attachment: C.04.6 arts. 3.6.1-3.6.4 TPN identifiers.

https://github.com/OttoMilvang/TieBreakServer/issues/17
"""
from pathlib import Path

from gacrux.pairingfideteam import pairing_fideteam
from gacrux.trf2json import trf2json


def identifier(pairs):
    ordered = sorted(tuple(sorted((p["ca"], p["cb"]))) for p in pairs)
    return tuple(a for a, b in ordered) + tuple(b for a, b in ordered)


def test_issue17_smaller_tpn_is_top_member_even_when_it_floated_up():
    """Arts. 3.6.1-3.6.4 compare TPN identifiers, never score-group positions."""
    reader = trf2json()
    fixture = Path(__file__).parent / "fixtures" / "fideteam_issue17.trf"
    reader.parse_file(fixture.read_text(), 0)
    engine = pairing_fideteam(reader.get_tournament(1), 2,
                             {"experimental": [], "verbose": 0, "rank": False, "top_color": "w"})
    brackets = engine.compute_pairing(False)
    bracket = next(b for b in brackets if set(b["competitors"]) == {4, 7, 10, 12, 14, 6})
    assert bracket["upfloaters"] == [6]
    assert identifier(bracket["pairs"]) == (4, 6, 7, 10, 12, 14)
    assert identifier(bracket["pairs"]) < (4, 6, 7, 14, 10, 12)
    # The same rule also corrects a different bracket in the original attachment.
    # Its declared 1-16/2-3 loses to 1-3/2-16, so the whole file is not a valid oracle.
    top = next(b for b in brackets if set(b["competitors"]) == {1, 2, 3, 16})
    assert identifier(top["pairs"]) == (1, 2, 3, 16)
    assert identifier(top["pairs"]) < (1, 2, 16, 3)


