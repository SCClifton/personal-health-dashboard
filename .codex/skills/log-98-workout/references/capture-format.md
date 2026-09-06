# Strength capture format

Use this format with `scripts/log_strength_session.py`. Keep each performed set as a separate object, even when several sets share the same prescription.

## Example

```json
{
  "source_record_id": "voice:2026-09-07:98-performance:w10b3:strength-sprint",
  "source_kind": "voice",
  "source_text": "Exact available transcript of Sam's recap.",
  "capture_status": "partial",
  "started_at": "2026-09-07T06:30:00+10:00",
  "duration_seconds": 3600,
  "timezone": "Australia/Sydney",
  "timing_confidence": "estimated",
  "program_name": "98 Performance",
  "program_session_name": "Strength + Sprint",
  "program_week": 10,
  "program_block": 3,
  "program_notes": "Coach notes transcribed from the app, if useful.",
  "session_rpe": 8,
  "notes": "Conditioning result was not reported.",
  "exercises": [
    {
      "position": 1,
      "series_name": "Series 1",
      "name": "Barbell Strict Press",
      "status": "completed",
      "planned_reps": "3-2-1-1+",
      "planned_tempo": "10X1",
      "planned_rest_seconds": 30,
      "target_intensity": "80/85/90/90%",
      "planned_notes": "Exercise-specific coach notes from the app, if useful.",
      "sets": [
        {
          "position": 1,
          "status": "completed",
          "reps": 3,
          "load_value": 64,
          "load_unit": "kg",
          "rpe": 8,
          "is_warmup": false
        }
      ]
    },
    {
      "position": 2,
      "series_name": "Series 2",
      "name": "Supported Single Arm Dumbbell Row",
      "status": "partial",
      "planned_sets": "4 x 6.6",
      "target_intensity": "RPE 8",
      "sets": [
        {
          "position": 1,
          "status": "completed",
          "reps": 6,
          "rep_multiplier": 2,
          "load_value": 30,
          "load_unit": "kg",
          "notes": "Six reps on each side."
        }
      ]
    }
  ]
}
```

## Field rules

- `source_record_id`: stable, human-readable identity. Never include the full transcript.
- `source_kind`: `voice`, `typed`, or `import`.
- `source_text`: verbatim transcription or typed recap. It is preserved only in the raw event.
- `capture_status`: `complete` only when the performed workout is adequately captured and at least one performed set exists; otherwise `partial`.
- `started_at` and `ended_at`: ISO 8601 with an explicit UTC offset. Do not use a timezone-naive timestamp.
- `timezone`: valid IANA name for the local session location.
- `timing_confidence`: `exact` only when reported or device-backed; otherwise `estimated`. If only the date is known, use local noon as a documented date-only placeholder and state in `notes` that the actual time was not reported.
- `status`: exercise values may be `completed`, `partial`, `skipped`, or `unknown`; set values may be `completed`, `partial`, or `skipped`.
- `planned_*`, `program_notes`, and `target_intensity`: transcribe from the 98 app. These are not evidence that the work was performed. Use exercise `planned_notes` for app-supplied coach or movement notes; reserve `notes` for user-reported outcomes and capture uncertainty.
- `reps`: repetitions performed within that set. Use `null` when unknown.
- `rep_multiplier`: default `1`. Use `2` when `reps` is explicitly per side and both sides were performed.
- `load_value`: the reported load. For a barbell, use total loaded bar weight. Use `null`, not zero, when load is unknown or not applicable.
- `load_unit`: `kg` or `lb`; required whenever `load_value` is present.
- `load_multiplier`: default `1`. Use `2` only when the reported load is per implement and two implements were used, such as two 20 kg dumbbells. Do not use it for one dumbbell moved between sides.
- `duration_seconds` and `distance_meters`: permitted at session/set level as supported by the schema. Store only reported or device-observed values.
- `rpe`: 1 to 10. Do not convert a planned RPE into an actual RPE.
- `is_warmup`: `true` only for a user-reported warm-up set.

## Calculations

- Performed sets include `completed` and `partial`, but not `skipped`.
- Repetitions = sum of `reps × rep_multiplier`.
- Volume load = sum of `load_kg × reps × rep_multiplier × load_multiplier`, reported as kg-reps.
- Bodyweight, carries, timed work, and conditioning can have zero volume load while still retaining repetitions, distance, or duration.
- Average set RPE is used only when no session RPE was reported.

Volume load is a descriptive training measure, not a calorie estimate or a health conclusion.
