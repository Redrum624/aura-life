def test_package_imports():
    import aura_life
    assert hasattr(aura_life, "__version__")


def test_version_has_one_source():
    """The attribute and the installed distribution must agree. 0.3.0 shipped with
    ``__version__ == "0.1.0"`` while its metadata said 0.3.0, because the two were
    maintained separately; setuptools now reads the attribute, so they cannot drift."""
    from importlib.metadata import version

    assert aura_life.__version__ == version("aura-life")
