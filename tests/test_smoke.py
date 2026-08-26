def test_package_imports():
    import aura_life
    assert hasattr(aura_life, "__version__")
