# Delivery Roadmap

This roadmap keeps product code and generic delivery work in GitHub while all personal measurements, goals, routes, provider payloads, credentials, databases, logs, and generated reports remain local.

## Operating outcome

The dashboard should answer four questions reliably:

1. Is the primary weight trend moving towards the locally configured goal?
2. Are food intake, cycling, strength work, sleep, and recovery complete enough to explain the trend?
3. Are duplicate device records or modelled calorie values distorting the picture?
4. What is the single highest-value data or behaviour gap to address next?

The dashboard is an exploratory tracking system, not a diagnostic or treatment tool.

## Source model

| Domain | Preferred source | Fallback/context | Current capability | Next delivery outcome |
|---|---|---|---|---|
| Weight | Direct scale export/API or explicit manual entry | Apple Health and nutrition-app weight | Manual/CSV ingestion and source priority exist | Confirm official paths for the active scales and add idempotent ingestion |
| Food intake | Complete daily nutrition log/export | Manual summary | MyFitnessPal CSV/zip import exists | Make weekly completeness visible and agree targets outside the codebase |
| Cycling | Local FIT activity plus device-recorded HR/cadence/power when present | Strava and Apple Health summaries | Strava summary/rich run ingestion exists | Add a Wahoo FIT importer, cycling metrics, and commute view |
| Strength | Structured session, exercise, set, load, and effort data | WHOOP/Strava workout summary | Summary workout context only | Add a local detailed strength-session schema and capture flow |
| Sleep/recovery | WHOOP and direct Oura data kept source-separated | Apple Health; Eight Sleep as bed-context only | WHOOP/Oura connectors and concordance foundations exist | Complete local Oura authorisation and expose freshness/source agreement |
| Goal progress | Locally configured active goal and daily weight trend | None | Goal model and coaching dashboard exist | Use a rolling trend, trajectory, completeness, and weekly review |

Measured values, device estimates, and modelled values must remain explicitly distinguishable. The system must not sum duplicated workouts or calorie estimates across devices.

## Delivery stages

### 0. Managed baseline

- [#2](https://github.com/SCClifton/personal-health-dashboard/issues/2): establish the privacy-safe managed project baseline.
- [#9](https://github.com/SCClifton/personal-health-dashboard/issues/9): isolate standard tests from the private runtime database.
- Track the application, tests, generic documentation, and GitHub workflow files on an issue branch.
- Keep raw/private material out of Git through explicit ignore rules and review checks.
- Require a linked issue, focused pull request, and passing fixture-driven tests.
- Resolve repository visibility and branch/ruleset changes through explicit approval.

### 1. Trustworthy daily loop

- [#3](https://github.com/SCClifton/personal-health-dashboard/issues/3): restore provider freshness and complete local Oura authorisation.
- [#4](https://github.com/SCClifton/personal-health-dashboard/issues/4): add idempotent ingestion for the active scales.
- [#5](https://github.com/SCClifton/personal-health-dashboard/issues/5): make nutrition completeness and local targets visible.
- Make a daily weigh-in easy and source-labelled.
- Confirm scale vendor/model and lawful official export/API options before connector work.
- Make nutrition completeness visible without inventing calorie or protein targets.
- Restore WHOOP, Strava, Oura, and Apple Health freshness checks.
- Show missing/stale sources before presenting coaching interpretations.

### 2. Activity and training detail

- [#6](https://github.com/SCClifton/personal-health-dashboard/issues/6): add Wahoo FIT ingestion and a cycling dashboard.
- [#7](https://github.com/SCClifton/personal-health-dashboard/issues/7): add detailed local strength-session capture.
- Add an idempotent Wahoo FIT raw-event importer.
- Add cycling distance, duration, elevation, HR, cadence, measured power, and estimate provenance.
- Add commute matching without committing precise route coordinates.
- Add detailed gym session capture for exercises, sets, reps, load, duration, and optional effort notes.
- Join activity load to recovery context without implying causation.

### 3. Weekly operating review

- [#8](https://github.com/SCClifton/personal-health-dashboard/issues/8): build the weekly goal and data-completeness review.
- Compare a seven-day weight trend with the local goal trajectory.
- Report data completeness before outcomes.
- Review nutrition logging, commute frequency, gym consistency, and recovery context.
- Separate observed facts, model outputs, hypotheses, and suggested next actions.
- Select one operational change for the following week and retain the prior snapshot locally.

## Definition of done

A change is complete when it:

- preserves raw inputs and stable idempotency;
- retains provider/source identity and source priority;
- handles units, dates, timezones, duplicates, and missing integrations in tests;
- contains no secret, private export, exact personal route, or local database;
- updates conflicting documentation in the same change;
- passes the local test suite and GitHub Actions;
- remains conservative and non-diagnostic in user-facing health copy.
