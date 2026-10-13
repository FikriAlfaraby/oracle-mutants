"""A deliberately weak verifier: it checks the shape of the answer, not the counts."""
import json
from pathlib import Path


def test_counts_file_is_a_json_object():
    data = json.loads(Path("/app/counts.json").read_text())
    assert isinstance(data, dict)


def test_mentions_the_most_common_word():
    data = json.loads(Path("/app/counts.json").read_text())
    assert "the" in data
