def test_package_imports():
    import aura_life
    assert hasattr(aura_life, "__version__")


def test_version_has_one_source():
    """The attribute and the installed distribution must agree. 0.3.0 shipped with
    ``__version__ == "0.1.0"`` while its metadata said 0.3.0, because the two were
    maintained separately; setuptools now reads the attribute, so they cannot drift."""
    from importlib.metadata import version

    import aura_life

    assert aura_life.__version__ == version("aura-life")


def test_the_changelog_s_top_section_is_this_version():
    """The newest section of CHANGELOG.md is the version the package says it
    is (released or not), so a bump cannot leave its notes under another
    heading."""
    import pathlib
    import re

    import aura_life

    changelog = (pathlib.Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert top is not None and top.group(1) == aura_life.__version__, (top and top.group(0), aura_life.__version__)
