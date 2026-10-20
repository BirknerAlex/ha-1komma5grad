# AGENTS.md

Guidance for AI coding agents (and humans) working on this repository. It is a
[HACS](https://hacs.xyz) custom integration for Home Assistant that talks to the
unofficial 1KOMMA5° Heartbeat API. See [README.md](README.md) for what it does and
[CONTRIBUTE.md](CONTRIBUTE.md) for background on the API.

## Checklist for every PR

Do all of this before you push, not after CI fails.

1. **One PR per feature or fix.** Branch from `dev` and open the PR against `dev` (`main` only receives
   releases). If your change contains two different things, e.g. a new entity and an unrelated bug fix or
   documentation clean-up, split it into two branches and two PRs (see [One PR, one commit](#one-pr-one-commit)).
2. **Update the [README](README.md)** whenever behaviour a user can see changes (see
   [README updates](#readme-updates)).
3. **Add tests.** A new feature needs tests for its behaviour, a bug fix needs a regression test that
   fails without the fix. A new API endpoint also needs a **mock file from a real, anonymized response**
   (see [Tests and mock data](#tests-and-mock-data)). A PR without them is not done.
4. **Run lint and tests locally** and make sure both are clean (see
   [Running lint and tests](#running-lint-and-tests)).
5. **Write commit titles in the semantic release schema** (see [Commit messages](#commit-messages)).
6. **One commit per PR.** Amend it instead of adding fix-up commits (see
   [One PR, one commit](#one-pr-one-commit)) and push with `git push --force-with-lease`, never plain `--force`.
7. **Watch CI** after pushing and fix failures. Resolve review threads (e.g. CodeRabbit)
   that your changes addressed.

## One PR, one commit

- **One PR per feature or fix.** A PR does one thing, so that it can be reviewed, released and, if needed,
  reverted on its own. Things that belong together stay together: a feature includes its tests, its mock
  files and its README changes. Unrelated work does not: a bug fix you notice on the way, a refactor, a lint
  clean-up or a README correction of something else goes into its own PR. If a second change is needed to make
  the first one work, open it first and base the other one on it once it is merged.
- **One commit per PR.** The commit title becomes the changelog entry (see [Commit messages](#commit-messages)).
  When a review, a CI failure or a lint finding needs a change, fold it into that commit instead of adding another one:

  ```bash
  git add -A
  git commit --amend            # keep or improve the message
  git push --force-with-lease   # only your own branch, never dev or main
  ```

  If you ended up with several commits, squash them (`git rebase -i` is not available to agents; use
  `git reset --soft <base>` and commit again).
- Rebase onto the current `dev` (`git rebase dev`) rather than merging `dev` into the branch, then run lint and
  tests again before the push.
- `--force-with-lease` is the only acceptable force push, pinned to the commit you last saw
  (`--force-with-lease=<branch>:<sha>`) so that nothing pushed by somebody else is overwritten.

## Running lint and tests

CI runs on Python 3.13. The local virtualenv is `.venv13` (Python 3.13); do not use another one.

```bash
.venv13/bin/python -m pytest -q   # all tests
tools/lint.sh                     # ruff check + basedpyright, exactly what CI runs
```

- **`ruff check` alone is not enough.** The CI `Test` job also runs `tools/lint.sh`, which
  type checks `custom_components/einskomma5grad` and `tests` with basedpyright. A passing
  `pytest` and `ruff check` can still fail CI on a type error.
- `tools/lint.sh` upgrades `ruff` and `basedpyright` in the venv on purpose: CI installs the
  latest versions without pins, and a stale local ruff can pass what CI rejects.
- The suite is fast (a few seconds). If a test fails on your branch, check whether it also
  fails on `dev` before blaming the environment.
- **Do not run `ruff format .` or `tools/reformat.sh` over the whole repo.** Many existing files
  are not formatted that way, so it would produce a huge unrelated diff. CI only runs
  `ruff check`. Format only the code you touch, if at all.
- Other CI checks you cannot run locally: HACS validation and Hassfest. They fail on a bad
  `manifest.json`, missing or invalid translation keys and similar. Do not hand edit the generated
  fields (`manifest.json` `version`, `hacs.json` `filename`, see [Generated files](#generated-files)).

## Commit messages

Releases are fully automated by semantic-release with the `conventionalcommits` preset
(`.releaserc`). The commit title decides the version and the changelog, so it has to follow:

```
<type>(<optional scope>): <short imperative summary>
```

| Type | Release | Changelog section |
|------|---------|-------------------|
| `feat` | minor | 🚀 Features |
| `fix` | patch | 🛠️ Fixes |
| `perf` | patch | ⏩ Performance |
| `docs` | none | 📔 Docs |
| `revert` | patch | 🙅 Reverts |
| `example` | none | 📝 Examples |
| `test`, `refactor`, `style`, `chore`, `ci`, `build` | none | hidden |

- A breaking change needs `!` after the type or a `BREAKING CHANGE:` footer, and triggers a major release.
- The title becomes a public changelog line, so describe the user visible effect
  (`fix: stop retrying rejected credentials`), not the implementation detail.
- Pick the type by the effect on users, not on the files: a bug fix that only touches tests is
  `test:`, a README change is `docs:`, a new entity is `feat:`.
- Keep the title short (about 72 characters), lower case after the colon, no trailing period.
- Use the body to explain why, and for what you verified (for example against the live API).
- Because a PR is one commit, that commit message is what gets released. Make sure it covers the whole PR;
  tests, mocks and docs of the feature belong in the same commit and do not need their own title.
- Never write `chore(release): ...` commits. The release bot creates them.
- Commits that you wrote with an AI assistant end with the `Co-Authored-By:` trailer you were given.

## README updates

The README is the user documentation, so it has to match the code. When a PR changes any of
the following, update the README in the same PR:

- **Entities:** new, renamed or removed entities, attributes, units, or default enabled state.
  Add them to the matching table under *Entities* (Sensors, Binary sensors, Calendar, Switches, Select, Number, Time)
  and describe attributes in their own section if there are more than a couple.
- **Configuration:** setup or options flow fields, defaults and limits (`const.py`,
  `config_flow.py`, `strings.json`).
- **Refresh behaviour:** polling intervals and which data is refreshed less often.
- **Automation examples:** add a short example when a feature is mainly useful in automations.
  Use `YOUR_SYSTEM_ID` as placeholder for the system id in entity ids.
- **Supported regions, tested hardware, limitations** when they change.

How to check the README is still correct:

- Compare the entity tables with what the integration really creates. The fixtures in `tests/conftest.py`
  can set up the whole integration against the mocks; a throwaway test that dumps
  `hass.states.async_all()` is the quickest way. Do not commit such a dump test.
- Check units and attribute names against the code, not against memory. Several README
  statements were once out of date because only the code was changed.
- Entity ids end with the system id, so document them as `..._YOUR_SYSTEM_ID`.
- Do not edit `CHANGELOG.md`; it is generated.

## Where things live

```
custom_components/einskomma5grad/
  api/                  API client. No Home Assistant imports, keep it testable on its own
  coordinator.py        DataUpdateCoordinator: fetches everything, per endpoint failure isolation
  const.py              Intervals and other constants
  sensor.py, binary_sensor.py, calendar.py, switch.py, select.py, number.py, time.py   platforms
  plan_entity.py        Shared base of the Heartbeat AI plan entities (decision sensors, binary sensor, calendars)
  strings.json, translations/en.json                                     UI texts
  test/mocks/           Anonymized API responses used by the tests
tests/                  pytest suite (pytest-homeassistant-custom-component)
tools/                  lint.sh, heartbeat_openapi.py, 1komma5.py (manual API script)
docs/heartbeat-openapi.json   Unofficial OpenAPI spec of the Heartbeat API
```

### Conventions to follow

- **Entities:** names end with the system id (`f"Battery ... {system_id}"`) and unique ids are
  `f"{DOMAIN}_<key>_{system_id}"`. Changing a unique id creates new entities for all users, so avoid it.
  Attach every entity to a device with `get_device_info`.
- **Coordinator:** fetch optional endpoints through `Coordinator._fetch_field` so one failing endpoint
  does not freeze unrelated data (the price forecast was once frozen that way). Keep slowly changing data
  on its own, longer interval, and keep the previous value on failure. Do not poll more often than the data changes.
- **API layer:** every request goes through `Client.get/post/patch` so it gets the app headers, tracing
  and the API change detection. Use `System._get_json` for plain JSON GETs. Raise `RequestError` on
  failures. Treat any response field as possibly missing or of another type; the API is not under our control.
- **Typing and lint:** code must pass `tools/lint.sh`. Home Assistant callbacks are strictly typed
  (for example `HassJob` is invariant in its return type), so annotate when basedpyright complains instead
  of silencing it.
- **Texts:** user facing strings go to `strings.json` and `translations/en.json`; keep both in sync.
- **Units and currencies:** prices in this integration are EUR/kWh. Convert if the API sends something
  else (the Heartbeat AI market price comes in EUR/MWh).

## Tests and mock data

- **Every new feature gets tests** that cover its behaviour: the normal case, missing or `null` fields,
  an unknown value from the API, and a failing endpoint (the entity must degrade, not crash the update).
  Test the new entities through the integration setup (`mock_api` fixture), not only the helper functions.
- **Every bug fix gets a regression test** that reproduces the bug. Prove it: run the new test against the
  code without your fix and see it fail, then with the fix and see it pass. Say so in the PR description.
- **Every new or changed endpoint gets a mock file made from a real response.** Call the real API (see
  [Exploring the API](#exploring-the-api)), save the response, and anonymize it. Do not write a mock by hand
  from the OpenAPI spec or from what you expect the API to send: hand made mocks miss the odd real values
  (`null`s, shared ids, strings for numbers, missing fields) that cause the bugs. If you cannot reach the API
  (no credentials or no such device), say so in the PR and ask for a capture instead of inventing one.
- **Anonymize before you commit.** Replace ids, names, addresses, coordinates, serial numbers, e-mail
  addresses and tokens with dummy values (the test system id is `a1b2c3d4-0000-0000-0000-000000000001`).
  Prices, schedules, timestamps and enum values are fine. Re-read the file for anything personal before
  committing, and keep the real shape: all fields, same types, same `null`s. Name files
  `<METHOD>_<path>.json` in `custom_components/einskomma5grad/test/mocks/`.
- Keep the tests independent of the exact content of the mock file (assert on structure and on events the test
  builds itself) so that the mock can be replaced by a fresh capture later without touching the tests.
- **Routing:** the `mock_api` fixture in `tests/conftest.py` routes requests to the mocks. Several tests build
  their own router from `insight_response()`. A new endpoint must be registered in `_INSIGHT_MOCKS`, otherwise those tests fail
  with `Unexpected GET URL`.
- Tests must not call the real API or depend on the wall clock being a certain time; build timestamps relative
  to `dt_util.utcnow()` or use fixed dates.

## Exploring the API

The API is undocumented and changes. If you need to see what it returns:

- Log in with the client (`Client(username, password).login()`) and call the endpoint with
  `Authorization: Bearer <token>` and the app headers, like `System._get_json` does.
- Credentials are in `.env` (git ignored). Careful: the shell variable `USERNAME` is the OS login
  name and overrides the `.env` value. Parse the file instead of `source`-ing it.
- Do not hammer the login endpoint with wrong credentials.
- Record what you learn: limits, parameters, enum values. Add new operations to
  `docs/heartbeat-openapi.json` with `tools/heartbeat_openapi.py` (it refuses to write captured values), and
  put observed limits into the docstring of the module that uses the endpoint.
- Never commit tokens, flow dumps, `.env`, `.token` or real response bodies.

## Minimum Home Assistant version

`hacs.json` declares the oldest Home Assistant version the integration supports (`homeassistant`, currently
`2024.11.0`). HACS lets users on older versions install the integration, so the value has to be right.

- When a PR uses a Home Assistant API that is newer than the declared minimum (a new helper, a new keyword argument,
  a new base class method), raise `homeassistant` in `hacs.json` in the same PR and mention it in the README.
- Do not guess the version from memory. Check it: `uv venv --python 3.12 /tmp/venvXXXX`, install the
  `pytest-homeassistant-custom-component` release that pins that exact Home Assistant version (its `Requires-Dist`
  shows which one) and run the whole suite there. The oldest version whose suite passes is the minimum. Do this in a
  throwaway directory outside the repository, with `josepy<2` if the import of `acme` fails.
- Never lower the minimum without running the suite on the lower version.

## Generated files

Do not edit these by hand; the release bot rewrites them:

- `CHANGELOG.md`
- `manifest.json` `version` and the `filename` in `hacs.json` (set by `tools/publish.sh`). The other fields of
  these files are normal code: for example `homeassistant` in `hacs.json` is raised by hand, see
  [Minimum Home Assistant version](#minimum-home-assistant-version).

## Releases

Pushes to `dev` produce pre-releases (`x.y.z-dev.N`), pushes to `main` produce stable releases.
Both run lint and tests first and then semantic-release. Merging a PR into `dev` is therefore
enough to publish a pre-release, so do not merge with a failing or unwatched CI.

## Pull request description

Say what changed and why, how you verified it (live API, tests, lint) and what you could not
verify. Link the issue (`Closes #123` or `Refs #123`). If a PR is a follow-up, link the earlier PR.
