# Definition of Done (DoD)

This checklist applies to every commit and release.  
Before pushing to GitHub, verify that these conditions are met:

---

## Code Quality
- [X] Code runs locally without errors
- [-] Linting/formatting passes (once tools like `ruff`/`black` are added)
- [ ] No secrets, passwords, or tokens in the repo

## Documentation
- [x] README updated if usage/behavior changed
- [x] CHANGELOG updated under **Unreleased** (or new version entry if tagging)
- [ ] Backlog updated if tasks were completed or new ones discovered
- [ ] New diagrams/screenshots added to `/docs` if relevant

## Git Hygiene
- [ ] Commit message is clear and descriptive (Conventional Commits style preferred)
- [ ] Each commit addresses a focused change (no unrelated mix)
- [ ] Release tags are annotated (`git tag -a vX.Y.Z -m "..."`)

## Security / Safety
- [ ] Code and flows run as non-admin user
- [ ] No unnecessary ports/services exposed
- [ ] Dependencies are pinned in requirements or package files

---

*Note: The DoD is a living document — update it as the project grows.*
