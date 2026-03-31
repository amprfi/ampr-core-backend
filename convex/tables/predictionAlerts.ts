import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validator for prediction alert kind
 */
export const PredictionAlertKind = v.union(
  v.literal("percentage_24h"),
  v.literal("percentage_7d")
);

/**
 * Prediction alerts - Oracle module notification configuration.
 *
 * Supports percentage-based alerts on prediction event markets:
 * - percentage_24h: fires when any market's 1D price change exceeds threshold.
 *   Max once per day.
 * - percentage_7d: fires when any market's 1W price change exceeds threshold.
 *   Max once per week.
 *
 * Thresholds are set as decimals (e.g., 0.05 for 5% probability change)
 * since Polymarket prices range from 0 to 1.
 *
 * last_triggered_at: Timestamp of the last time this alert fired.
 * Used for per-period deduplication (24h alerts: once/day, 7d alerts: once/week).
 */
export const predictionAlerts = defineTable({
  user: v.id("users"),
  event: v.optional(v.id("predictionEvents")),
  alert_kind: PredictionAlertKind,
  notification_type: v.id("notificationTypes"),
  threshold_pct: v.optional(v.float64()),
  last_triggered_at: v.optional(v.float64()),
})
  .index("by_user", ["user"])
  .index("by_user_event", ["user", "event"])
  .index("by_alert_kind", ["alert_kind"])
  .index("by_user_alert_kind", ["user", "alert_kind"])
  .index("by_event_alert_kind", ["event", "alert_kind"]);
