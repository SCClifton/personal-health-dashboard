from health_dashboard.connectors.apple_health import metrics_from_apple_record
from health_dashboard.db import SessionLocal
from health_dashboard.models import NormalizedMetric, RawEvent
from health_dashboard.services.ingestion import rebuild_daily_features


def main() -> None:
    created = 0
    with SessionLocal() as db:
        rows = db.query(RawEvent).filter(RawEvent.provider == "apple_health").all()
        for raw_event in rows:
            if raw_event.metrics:
                continue
            for metric in metrics_from_apple_record(raw_event.payload_json):
                db.add(
                    NormalizedMetric(
                        provider=raw_event.provider,
                        source=metric.source or raw_event.provider,
                        metric_name=metric.metric_name,
                        value_numeric=metric.value_numeric,
                        value_text=metric.value_text,
                        unit=metric.unit,
                        observed_start=metric.observed_start,
                        observed_end=metric.observed_end,
                        aggregation_window=metric.aggregation_window,
                        confidence=metric.confidence,
                        raw_event_id=raw_event.id,
                    )
                )
                created += 1
        rebuild_daily_features(db)
        db.commit()
    print(f"created_normalized_metrics={created}")


if __name__ == "__main__":
    main()
