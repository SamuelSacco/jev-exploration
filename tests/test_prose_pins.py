"""Prose pins for the adversarial-review follow-up fixes.

Substring assertions on the edited prose files. Each test FAILS on the
pre-fix wording and PASSES on the fixed wording, so a revert of the fix
fails loudly. Reading file contents, not importing the modules under
test, keeps these cheap.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# P0 S1/M4: the "no draw worse than doing nothing" claim was false per draw.
def test_fit_platt_intercept_docstring_discloses_the_backfire_draws():
    text = read("jevlab/calibration.py")
    assert "3 of 480" in text
    assert "no draw worse than doing nothing" not in text


def test_exp_transfer_docstring_discloses_the_backfire_draws():
    text = read("lab/exp_transfer.py")
    assert "3 of 480" in text
    assert "no draw worse than doing nothing" not in text


def test_backfire_disclosure_names_draw_23():
    assert "draw 23" in read("jevlab/calibration.py")
    assert "draw 23" in read("lab/exp_transfer.py")


# P1 P0-2: the Noul corpus grew from 2,580 to 11,148 answers.
def test_claims_audit_endpoint_table_uses_grown_corpus():
    text = read("docs/claims-audit.md")
    assert "11,148" in text
    assert "0.0344%" in text
    assert "2,580" not in text


def test_footguns_quantisation_counts_use_grown_corpus():
    text = read("docs/footguns.md")
    assert "11,148+" in text
    assert "2,580" not in text


def test_exp_response_shape_quantisation_counts_use_grown_corpus():
    text = read("lab/exp_response_shape.py")
    assert "11,148" in text
    assert "0.0344%" in text
    assert "2,580" not in text


def test_readme_quantisation_count_uses_grown_corpus():
    text = read("README.md")
    assert "11,148" in text
    assert "2,580" not in text


# P1 A1: the slope-as-model-property claim is qualified after issue #9.
def test_slope_model_property_claim_qualified_on_email():
    assert "a property of the model on e-mail" in read("docs/claims-audit.md")
    assert "a property of the model on e-mail" in read("lab/exp_transfer.py")
    assert "a property of the model on e-mail" in read("jevlab/calibration.py")


# P1 A4: the circularity preregistration over-read noise at the per-tier level.
def test_circularity_preregistration_not_refuted_on_every_clause():
    text = read("analysis/CIRCULARITY.md")
    assert "REFUTED, on every clause" not in text
    assert "unsettled" in text


# P1 A5: README finding 2 carries the decomposition caveat.
def test_readme_finding_two_carries_the_decomposition_caveat():
    text = read("README.md")
    assert "t1→t4 pair" in text
    assert "never significant" in text
