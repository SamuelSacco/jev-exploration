"""Tests for the circularity audit, the transport seam and the relabeling experiment."""
import json
import os

import pytest

from analysis import circularity as circ
from jevlab import transport
from lab import exp_circularity as exp

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def gold():
    path = os.path.join(HERE, "lab", "runs", f"{circ.TIER_RUN}-tiers-t1_trivial.jsonl")
    if not os.path.exists(path):
        pytest.skip("tier run not committed")
    from lab.tiers.baselines import load

    return {r["id"]: r["is_phishing"] for r in load()}


@pytest.fixture(scope="module")
def tiers(gold):
    from lab.tiers.analyse import read_pass
    from lab.tiers.baselines import TIER_ORDER

    return {t: read_pass(circ.TIER_RUN, t, 0, gold) for t in TIER_ORDER}


# ------------------------------------------------------------------- provenance


def test_labels_are_not_model_derived():
    """The load-bearing claim: circularity needs a path from the model under test
    to the ground truth, and there is none."""
    prov = circ.label_provenance()
    assert prov["label_precedes_text"] is True
    assert prov["api_imports"] == []
    assert prov["model_output_reads"] == []
    assert prov["verdict"] == "labels are not model-derived"


def test_provenance_check_would_notice_an_api_import(tmp_path, monkeypatch):
    """A guard that fails if someone later wires model output into the generator."""
    generator = os.path.join(HERE, "lab", "tiers", "generate.py")
    with open(generator, encoding="utf-8") as fh:
        src = fh.read()
    assert "JevClient" not in src
    # And the checker is not vacuous: it looks for tokens that would appear.
    import inspect

    checker = inspect.getsource(circ.label_provenance)
    assert "JevClient" in checker and "urllib" in checker


# ------------------------------------------------------------------- corruption


def test_adversarial_corruption_raises_ece_monotonically():
    from jevlab.stats import ece

    pairs = [(0.95, True)] * 40 + [(0.05, False)] * 40
    before = ece(pairs)
    after = ece(circ.corrupt_adversarially(pairs, 5))
    assert after > before


def test_adversarial_corruption_flips_exactly_k_items():
    pairs = [(0.9, True)] * 20 + [(0.1, False)] * 20
    corrupted = circ.corrupt_adversarially(pairs, 6)
    changed = sum(1 for a, b in zip(pairs, corrupted) if a[1] != b[1])
    assert changed == 6
    assert [p for p, _ in corrupted] == [p for p, _ in pairs], "probabilities untouched"


def test_random_corruption_flips_exactly_k_items():
    pairs = [(0.9, True)] * 30
    corrupted = circ.corrupt_randomly(pairs, 7, seed=1)
    assert sum(1 for a, b in zip(pairs, corrupted) if a[1] != b[1]) == 7


def test_adversarial_is_at_least_as_damaging_as_random():
    from jevlab.stats import ece

    pairs = [(0.9, True)] * 50 + [(0.2, False)] * 50
    k = 10
    adversarial = ece(circ.corrupt_adversarially(pairs, k))
    randoms = [ece(circ.corrupt_randomly(pairs, k, seed=s)) for s in range(10)]
    assert adversarial >= max(randoms)


# ------------------------------------------------------------------ sensitivity


def test_b2_budget_is_arithmetic_and_small(tiers):
    """Every item above the threshold is a hit, so each bad label costs one."""
    block = circ.sensitivity_b2(tiers["t4_adversarial"])
    assert block["hit_rate"] == 1.0
    assert 1 <= block["flips_to_fall_below_target"] <= 5
    assert block["as_fraction_of_tier"] < 0.05


def test_b1_is_more_fragile_than_b2_not_less(tiers):
    """The conclusion this file asserted backwards for two revisions.

    The earlier assertion was b1 > b2, and it passed because the greedy
    search's ties were resolved by lowest index, which is consistently the
    kindest choice available to an adversary. Sampling the ties reverses it.
    """
    b1 = circ.sensitivity_b1(
        tiers["t1_trivial"], tiers["t4_adversarial"], tie_break_samples=8
    )
    b2 = circ.sensitivity_b2(tiers["t4_adversarial"])
    assert b1["intact_margin"] > 0
    assert b1["fraction_to_break"] <= b2["as_fraction_of_tier"]


def test_b1_is_intact_before_any_corruption(tiers):
    b1 = circ.sensitivity_b1(
        tiers["t1_trivial"], tiers["t4_adversarial"], tie_break_samples=2
    )
    assert b1["intact_margin"] > 0
    assert b1["flips_to_break"] >= 1


def test_the_greedy_search_has_many_tied_candidates(tiers):
    """Why no single greedy answer exists: twenty flips are equally damaging."""
    from jevlab.stats import ece

    pairs = tiers["t4_adversarial"]
    scored = [round(ece(circ.flip(pairs, i)), circ.TIE_PRECISION) for i in range(len(pairs))]
    best = max(scored)
    assert scored.count(best) >= 10


def test_the_lowest_index_tie_break_is_reproducible(tiers):
    """Rounding before comparing is what makes it the same on 3.11 and 3.12."""
    a = circ.corrupt_adversarially(tiers["t4_adversarial"], 3)
    b = circ.corrupt_adversarially(tiers["t4_adversarial"], 3)
    assert a == b


def test_sampling_the_ties_reaches_a_cheaper_attack(tiers):
    """The lowest-index choice is not neutral; it flatters the finding."""
    block = circ.sensitivity_b1(
        tiers["t1_trivial"], tiers["t4_adversarial"], tie_break_samples=10
    )
    assert block["flips_to_break"] < block["lowest_index_tie_break"]
    lo, hi = block["tie_break_range"]
    assert lo == block["flips_to_break"] <= hi


def test_a_seeded_tie_break_is_deterministic(tiers):
    import random

    a = circ.corrupt_adversarially(tiers["t4_adversarial"], 3, rng=random.Random(5))
    b = circ.corrupt_adversarially(tiers["t4_adversarial"], 3, rng=random.Random(5))
    assert a == b


def test_the_headline_is_the_minimum_across_passes_and_tie_breaks(gold):
    across = circ.sensitivity_b1_all_passes(
        circ.TIER_RUN, gold, passes=3, tie_break_samples=6
    )
    per_pass = [b["flips_to_break"] for b in across["per_pass"].values()]
    assert across["flips_range"][0] == min(per_pass)
    assert across["worst_case_fraction"] == min(
        b["fraction_to_break"] for b in across["per_pass"].values()
    )


# -------------------------------------------------------------------- transport


def test_default_sender_is_the_repo_client(monkeypatch):
    monkeypatch.delenv(transport.ENV_VAR, raising=False)
    assert "JevClient" in transport.describe_sender()


def test_transport_can_be_injected(monkeypatch, tmp_path):
    """An operator holding their own credential must be able to substitute a
    sender without this repo containing any credential code."""
    module = tmp_path / "opsmod.py"
    module.write_text(
        "def send(state, questions, model='jev-latest'):\n"
        "    return {'model': 'stub', 'answers': {q: {'type': 'noul', 'noul': 0.5}\n"
        "            for q in questions}, '_elapsed_s': 0.1}\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv(transport.ENV_VAR, "opsmod:send")
    sender = transport.resolve_sender()
    raw, elapsed = transport.timed(sender, "state", {"q1": {}})
    assert raw["model"] == "stub" and elapsed == 0.1
    assert transport.describe_sender() == "opsmod:send"


def test_bad_transport_spec_is_rejected(monkeypatch):
    monkeypatch.setenv(transport.ENV_VAR, "not_a_spec")
    with pytest.raises(ValueError, match="package.module:callable"):
        transport.resolve_sender()


def test_non_callable_transport_is_rejected(monkeypatch, tmp_path):
    module = tmp_path / "badmod.py"
    module.write_text("send = 42\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv(transport.ENV_VAR, "badmod:send")
    with pytest.raises(TypeError):
        transport.resolve_sender()


SECRET_NAMES = {"TYPESAFE_API_KEY", "API_KEY", "TOKEN", "SECRET", "PASSWORD"}


def _executable_source(path: str) -> str:
    """Source with docstrings and comments stripped.

    Naming an environment variable in prose is documentation. Reading its value
    is credential handling. Only the second one is a violation, so the check has
    to look at code rather than at text.
    """
    import ast
    import io
    import tokenize

    with open(os.path.join(HERE, path), encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node):
                node.body[0] = ast.Expr(value=ast.Constant(value=""))
    stripped = ast.unparse(tree)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(stripped).readline):
        if tok.type != tokenize.COMMENT:
            out.append(tok.string)
    return " ".join(out)


@pytest.mark.parametrize(
    "path",
    [
        "lab/exp_circularity.py",
        "lab/probe_structure.py",
        "lab/exp_transfer.py",
        "lab/exp_headtohead.py",
        "jevlab/transport.py",
    ],
)
def test_no_credential_is_read_or_emitted(path):
    """The operating constraint: these run under an operator's own credential
    handling and must contain none of their own."""
    code = _executable_source(path)
    for name in SECRET_NAMES:
        assert name not in code, f"{path} touches {name} in executable code"
    for token in ("Authorization", "Bearer", ".env", "api_key="):
        assert token not in code, f"{path} builds {token} in executable code"


def test_describe_sender_reports_the_mechanism_without_naming_a_secret(monkeypatch):
    """Run logs should say which transport is in use, not which variable holds a key."""
    monkeypatch.delenv(transport.ENV_VAR, raising=False)
    described = transport.describe_sender()
    assert "JevClient" in described
    assert not any(name in described for name in SECRET_NAMES)

    monkeypatch.setenv(transport.ENV_VAR, "opsmod:send")
    assert transport.describe_sender() == "opsmod:send"


def test_the_default_mechanism_is_documented_for_an_operator():
    """Naming it in prose is how an operator knows what to override."""
    assert "TYPESAFE_API_KEY" in transport.__doc__
    assert "JEV_TRANSPORT" in transport.__doc__


# ------------------------------------------------------------------- experiment


def test_labelling_wording_differs_from_scoring():
    """Identical wording would make the premium 1.0 by construction."""
    assert exp.SCORING_INSTRUCTIONS != exp.LABELLING_INSTRUCTIONS
    assert set(exp.SCORING_CRITERIA.values()) != set(exp.LABELLING_CRITERIA.values())


def test_scoring_question_matches_the_published_run():
    """The premium is only meaningful if 'scoring' is the same measurement B1/B2 used."""
    from lab import run_tiers

    assert exp.SCORING_INSTRUCTIONS == run_tiers.INSTRUCTIONS
    assert exp.SCORING_CRITERIA == run_tiers.CRITERIA


def test_premium_is_zero_when_self_labels_match_truth():
    truth = {f"i{n}": n % 2 == 0 for n in range(20)}
    scoring = {k: (0.9 if v else 0.1) for k, v in truth.items()}
    self_labels = {k: (0.9 if v else 0.1) for k, v in truth.items()}
    result = exp.score(scoring, truth, self_labels)
    assert result["circularity_premium"] == 0.0
    assert result["self_label_agreement_with_truth"] == 1.0


def test_premium_is_positive_when_the_model_agrees_with_its_own_errors():
    truth = {f"i{n}": True for n in range(20)}
    # The model says False on half, and its own labels repeat that mistake.
    scoring = {f"i{n}": 0.1 if n < 10 else 0.9 for n in range(20)}
    self_labels = dict(scoring)
    result = exp.score(scoring, truth, self_labels)
    assert result["under_generator_labels"]["accuracy"] == 0.5
    assert result["under_self_labels"]["accuracy"] == 1.0
    assert result["circularity_premium"] == 0.5


def test_dry_run_makes_no_calls(capsys, monkeypatch):
    def explode(*a, **kw):
        raise AssertionError("--dry-run must not resolve a sender")

    monkeypatch.setattr(exp, "resolve_sender", explode)
    assert exp.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Total calls" in out and "preregistered" in out
