from it2pr_worker import __version__
from it2pr_worker.__main__ import main


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"


def test_main_returns_zero() -> None:
    assert main([]) == 0
