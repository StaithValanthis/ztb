from ztb import __version__


def test_version_format() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    for p in parts:
        assert p.isdigit()
