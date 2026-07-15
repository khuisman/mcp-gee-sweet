Cut a stable release: merge `develop` → `main`, tag, publish to PyPI via a GitHub Release, then merge `main` back into `develop` so subsequent dev builds immediately pick up the new version as their base. Run this from the main checkout, on `develop`, clean.

**Precondition — release QA sign-off.** This command executes a release, it doesn't decide whether one is ready. Confirm Aziz's release-QA pass has landed on `develop`: a `docs/qa/runs/vX.Y.Z.md` sign-off (and matching `docs/qa/results/<date>.md`) for the version being cut. If it's missing, stop and tell the user to run the release QA pass first (`/team-member Aziz`) — don't review or test anything yourself here.

1. **Determine the version.** Check `docs/roadmap.md`'s Release Cadence table for the target version, and confirm it against the last tag (`git tag --sort=-creatordate | head -1`) so the bump direction (patch/minor/major) makes sense. Confirm the exact version string with the user before proceeding if there's any ambiguity.
2. **Merge `develop` → `main`.**
   - Check for an existing PR first (`gh pr list --base main --head develop`); open one if it doesn't exist (`gh pr create --base main --head develop --title "Release vX.Y.Z" --body ...`).
   - Wait for the "Lint and test" check to pass — do not merge on a failing or pending check.
   - Merge with `gh pr merge <number> --admin --merge` — a real merge commit, **not** `--squash`. This repo's existing `main` history is a chain of "Merge pull request #NNN from khuisman/develop" merge commits (see `git log origin/main`), not squashed releases; squashing here would collapse that convention. `--admin` is required the same way it is in `/merge-pr`: `main` requires 1 approving review that will never come from a solo maintainer, and `enforce_admins` is `false` specifically so this bypass is allowed — it must never be used to skip the "Lint and test" check itself.
3. **Tag the merge commit.**
   - `git fetch origin main`
   - `git tag vX.Y.Z origin/main`
   - `git push origin vX.Y.Z`
4. **Create the GitHub Release from that tag** — `gh release create vX.Y.Z --title vX.Y.Z --generate-notes` (target `main`). This is what fires `.github/workflows/release.yml`'s `pypi-publish` job.
5. **Verify the stable PyPI publish.**
   - `gh run list --workflow=release.yml --limit 1` and watch it to completion.
   - If it fails with `invalid-pending-publisher`: the PyPI trusted-publisher registration reverts to "pending" state once a project already has a publisher on file — tell the user to add `release.yml` as a *current* publisher on the PyPI project's Publishing page (not re-add as pending), then `gh run rerun <run-id> --failed`.
   - Confirm the new version is actually live (`pip index versions mcp-gee-sweet` or check the PyPI project page) before moving on.
6. **Post-release — merge `main` back into `develop`, immediately, every time.** This is the step that was previously skipped and caused real breakage: after v0.8.1 shipped 2026-07-05, `main` never got merged back into `develop`, so `git describe --tags` — which `uv-dynamic-versioning` uses to compute the dev version — kept resolving to the last tag `develop` could already see (`v0.7.0`). Every dev prerelease for the next week+ silently published as `0.7.0.devN` instead of `0.8.1.devN`, even though `develop` had moved well past v0.8.1's feature set. Do not treat this as optional cleanup.
   - `pwd` and `git branch --show-current` first — confirm you're in the main checkout on `develop`, not a stale worker worktree (this exact mistake happened once: a merge landed on `.claude/worktrees/jay` mid-`cd` instead of the main checkout).
   - `git fetch origin main develop`
   - `git checkout develop && git pull`
   - `git merge origin/main -m "Merge main into develop after vX.Y.Z release"` — this should be a clean fast merge with no conflicts, since `main` only ever receives commits that originated on `develop`. If it isn't clean, stop and investigate rather than force through it.
   - `git push origin develop`
7. **Verify version continuity on both branches** — don't just assume step 6 worked:
   - `git describe --tags origin/main` must print exactly `vX.Y.Z` (distance 0). If not, the tag isn't actually on `main`'s tip — stop before publishing or telling the user anything is done.
   - `git describe --tags origin/develop` must show `vX.Y.Z` as its base (e.g. `vX.Y.Z-N-g<hash>`), not an older tag. If it still resolves to a prior tag, the merge-back didn't take (wrong branch, push failed, etc.) — re-check before reporting success.
   - `publish-dev.yml` only fires on pushes touching `src/**`, `tests/**`, `pyproject.toml`, or `uv.lock` — a no-op merge commit may not trigger it, so don't expect an automatic dev-publish run right after the merge-back. That's fine: the `git describe` check above is what proves the *next* real push will publish under the correct base. Don't force a throwaway push just to watch a workflow run.
8. **Report a summary:** the stable version tagged and confirmed live on PyPI, the release URL, the merge-back commit hash, and both `git describe` outputs from step 7 as proof the two branches are version-consistent.
