# Contributing

Thanks for your interest! Before opening a PR:

1. **Open an issue first** describing the change you have in mind, so we can
   agree on the direction before you write code.
2. **One logical change per PR**; follow the existing code style.
3. **Run the test suite — PRs must be green:**

   ```bash
   python -m pytest tests -q
   ```

   Python 3.11+ and `pytest` are all it needs; the suite uses no network. Run it
   in an environment with no host application on `sys.path` —
   `test_multi_instance.py` asserts that explicitly.

A few repo-specific rules:

- **Do not edit `NOTICE`.** It carries the legally load-bearing relicensing
  attribution for this code (extracted from a PolyForm-Noncommercial project and
  relicensed under Apache-2.0 by the copyright holder). PRs that modify or
  remove it will not be accepted.
- Two committed fixtures are contracts, not caches: `tests/api_surface.json`
  (the public `__all__` surface) and `tests/fixtures/persona_parity_golden.json`.
  If your change alters the public API, say so in the PR and regenerate the
  snapshot deliberately (`API_SURFACE_WRITE_SNAPSHOT=1`) — never delete a
  fixture to make a test pass.
- By contributing you agree your contribution is licensed under Apache-2.0,
  like the rest of the project.
