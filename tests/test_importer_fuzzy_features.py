import math

from flask_app.importer.pipeline.fuzzy_features import (
    ALT_CONTACT_WEIGHT,
    ADDRESS_WEIGHT,
    DOB_WEIGHT,
    EMPLOYER_WEIGHT,
    NAME_WEIGHT,
    SCHOOL_WEIGHT,
    compute_address_similarity,
    compute_alternate_contact_match,
    compute_dob_proximity,
    compute_employer_similarity,
    compute_name_similarity,
    compute_school_similarity,
    summarize_features,
    weighted_score,
)


def test_compute_name_similarity_handles_exact_match():
    score = compute_name_similarity("Isabella", "Martinez", "isabella", "MARTINEZ")
    assert math.isclose(score, 1.0, rel_tol=1e-3)


def test_compute_name_similarity_returns_zero_when_missing():
    assert compute_name_similarity(None, "Martinez", "Isabella", "Martinez") == 0.0


def test_compute_dob_proximity_exact_match():
    assert compute_dob_proximity("1992-05-11", "1992-05-11") == 1.0


def test_compute_dob_proximity_decay():
    score = compute_dob_proximity("1992-05-11", "1993-05-11")
    assert 0.45 <= score <= 0.55  # around 0.5 for 1 year difference


def test_compute_address_similarity_with_bonus():
    score = compute_address_similarity(
        "125 Palm St",
        "San Francisco",
        "94110",
        "125 Palm Street",
        "San Francisco",
        "94110",
    )
    assert score > 0.9


def test_compute_employer_similarity_token_sort_ratio():
    score = compute_employer_similarity("North Beach Tutoring", "North Beach Tutoring Center")
    assert score > 0.7


def test_compute_school_similarity_handles_missing():
    assert compute_school_similarity(None, "Bay Robotics Academy") == 0.0


def test_compute_alternate_contact_match_matches_emails():
    score = compute_alternate_contact_match(
        ["isabella.martinez+alumni@example.org"],
        [],
        ["isabella.martinez@example.org"],
        [],
    )
    assert score == 1.0


def test_weighted_score_combines_features():
    features = {
        "name": 1.0,
        "dob": 0.5,
        "address": 0.8,
        "employer": 0.6,
        "school": 0.4,
        "alternate_contact": 1.0,
    }
    score = weighted_score(features)
    expected = (
        NAME_WEIGHT * 1.0
        + DOB_WEIGHT * 0.5
        + ADDRESS_WEIGHT * 0.8
        + EMPLOYER_WEIGHT * 0.6
        + SCHOOL_WEIGHT * 0.4
        + ALT_CONTACT_WEIGHT * 1.0
    )
    assert math.isclose(score, expected, rel_tol=1e-6)


def test_summarize_features_clamps_and_rounds():
    summary = summarize_features({"name": 1.234, "dob": -0.4, "address": 0.87654})
    assert summary["name"] == 1.0
    assert summary["dob"] == 0.0
    assert summary["address"] == 0.877
