from integrations.qdrant_store import make_point_id


def test_same_inputs_same_id():
    assert make_point_id("a.pdf", "etag1", 3) == make_point_id("a.pdf", "etag1", 3)


def test_any_component_changes_the_id():
    base = make_point_id("a.pdf", "etag1", 3)
    assert make_point_id("b.pdf", "etag1", 3) != base
    assert make_point_id("a.pdf", "etag2", 3) != base
    assert make_point_id("a.pdf", "etag1", 4) != base


def test_id_is_valid_uuid_string():
    import uuid
    uuid.UUID(make_point_id("a.pdf", "etag1", 0))  # raises if malformed
