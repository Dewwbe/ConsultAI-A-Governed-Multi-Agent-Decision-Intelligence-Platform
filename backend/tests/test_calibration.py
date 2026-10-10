from app.control_plane.calibration import MIN_PER_CLASS, auc, best_threshold, calibrate


def rec(decision, **scores):
    return {"decision": decision, "evaluation_scores": scores}


def test_auc_perfect_none_and_inverted():
    assert auc([0.9, 0.8], [0.2, 0.1]) == 1.0
    assert auc([0.2], [0.9]) == 0.0
    assert auc([0.5], [0.5]) == 0.5  # ties count half
    assert auc([], [0.5]) is None


def test_best_threshold_separates_the_groups():
    t, bal = best_threshold([0.9, 0.85, 0.8], [0.4, 0.5, 0.3])
    assert 0.8 <= t <= 0.85 and bal == 1.0


def test_a_score_that_separates_is_reported_with_policy_effects():
    records = [rec("approve", groundedness=0.9)] * 40 + [rec("reject", groundedness=0.4)] * 35
    records += [rec("modify", groundedness=0.8)] * 5  # modified: not an acceptance as written
    report = calibrate(records, {"min_groundedness": 0.75})
    m = report.metrics[0]
    assert (report.approved, report.not_approved) == (40, 40)
    assert m.auc > 0.9 and m.policy_threshold == 0.75
    assert m.false_accept_rate == 0.125  # the 5 modified runs at 0.8 pass a 0.75 minimum
    assert m.false_block_rate == 0.0


def test_a_score_that_does_not_separate_is_called_weak():
    records = [rec("approve", groundedness=0.8)] * 35 + [rec("reject", groundedness=0.8)] * 35
    assert calibrate(records).metrics[0].verdict.startswith("weak")


def test_a_lenient_policy_threshold_is_flagged():
    records = [rec("approve", groundedness=0.9)] * 35 + [rec("reject", groundedness=0.8)] * 35
    verdict = calibrate(records, {"min_groundedness": 0.7}).metrics[0].verdict
    assert "consider raising" in verdict


def test_a_thin_sample_is_never_presented_as_calibration():
    report = calibrate([rec("approve", groundedness=0.9), rec("reject", groundedness=0.1)])
    assert "thin sample" in report.metrics[0].verdict
    assert any(str(MIN_PER_CLASS) in n for n in report.notes)


def test_no_decisions_says_what_is_needed():
    report = calibrate([])
    assert report.decisions == 0 and "no decisions" in report.notes[0]


def test_modify_can_count_as_acceptance_and_bad_records_are_skipped():
    records = [rec("modify", groundedness=0.9), {"decision": "approve"}, {"decision": "weird", "evaluation_scores": {"a": 1}}]
    report = calibrate(records, modify_as_approved=True)
    assert (report.approved, report.not_approved) == (1, 0)


def test_an_inverted_score_is_called_inverted():
    records = [rec("approve", groundedness=0.2)] * 35 + [rec("reject", groundedness=0.9)] * 35
    assert calibrate(records).metrics[0].verdict.startswith("inverted")
