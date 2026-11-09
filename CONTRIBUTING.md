# Contributing to EasyMaint

**English** | [Français](CONTRIBUTING.fr.md)

Thank you for your interest! Fixes, translations (Arabic and others), improvements and new features are welcome.

## Project principles

- **No fake features**: a delivered feature is complete, tested and documented.
- **Never remove an existing feature** without prior discussion.
- All business data inherits from `TenantScopedModel` and goes through `objects` (filtered on the current
  company): see [docs/architecture.md](docs/architecture.md).
- Every page checks a permission (`CapabilityRequiredMixin` or `require_capability`): the test
  `apps/core/tests/test_security.py` visits every URL and fails otherwise.
- No scripts inside templates (Content Security Policy): page behaviour goes in `static/js`.
- Interface texts are written in French (the reference language) and marked for translation
  (`{% translate %}`, `gettext`). Every text must have its English translation in
  `locale/en/LC_MESSAGES/django.po`: `apps/core/tests/test_i18n.py` fails otherwise (see `locale/LISEZMOI.md`).

## Proposing a change

1. Create a branch and develop with tests.
2. Check: `ruff check --select F,E9,I .` then `docker compose run --rm web pytest` (all tests pass,
   migrations and translations included).
3. Update the documentation (`docs/`) and `docs/CHANGELOG.md`.
4. Open a pull request explaining the maintenance need behind it.

By contributing, you agree that your code is distributed under the project's license (AGPL-3.0).

## Reporting a security issue

Please do not open a public issue: write to contact@jugurthasoft.com.
