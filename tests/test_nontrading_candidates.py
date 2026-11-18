from scripts.nontrading_candidates import is_retired_nontrading_candidate


def test_only_adjudicated_candidate_keys_are_retired():
    assert is_retired_nontrading_candidate("H00922", "20180618")
    assert is_retired_nontrading_candidate("H00300", "20261114")
    assert not is_retired_nontrading_candidate("H20915", "20261114")
    assert not is_retired_nontrading_candidate("H00300", "20261117")
    assert not is_retired_nontrading_candidate("H00918", "20180618")
