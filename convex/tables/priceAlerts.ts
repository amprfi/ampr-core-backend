import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validator for alert kind
 */
export const AlertKind = v.union(
  v.literal("percentage_24h"),
  v.literal("percentage_7d"),
  v.literal("absolute_price")
);

/**
 * Enum validator for price direction (absolute price alerts only)
 */
export const PriceDirection = v.union(
  v.literal("above"),
  v.literal("below")
);

/**
 * Price alerts - DeFiAnalyst notification configuration.
 *
 * Supports two alert kinds:
 * - Percentage alerts (24h / 7d): trigger when price change exceeds threshold_pct.
 *   Two-tier resolution for threshold_pct:
 *   1. Per-user per-asset: user + asset set → threshold for a specific asset
 *   2. Per-user default: user set, asset null → fallback for all user's assets
 *   If no row exists, no alert fires — rows are created at registration time
 *   with module-defined defaults (5% for 24h, 10% for 7d).
 *
 * - Absolute price alerts: trigger when asset crosses target_price in the
 *   specified direction. One-shot — row is deleted from the DB on trigger.
 *   Validation: current price must be on the opposite side of target_price
 *   at creation time.
 *
 * last_triggered_at: Timestamp of the last time this alert fired.
 * Used for per-period deduplication (24h alerts: once/day, 7d alerts: once/week).
 */
export const priceAlerts = defineTable({
  user: v.id("users"),
  asset: v.optional(v.id("assets")),
  alert_kind: AlertKind,
  notification_type: v.id("notificationTypes"),
  // Percentage alert fields
  threshold_pct: v.optional(v.float64()),
  // Absolute price alert fields
  direction: v.optional(PriceDirection),
  target_price: v.optional(v.float64()),
  // Per-period deduplication
  last_triggered_at: v.optional(v.float64()),
})
  .index("by_user", ["user"])
  .index("by_user_asset", ["user", "asset"])
  .index("by_alert_kind", ["alert_kind"])
  .index("by_user_alert_kind", ["user", "alert_kind"])
  .index("by_asset_alert_kind", ["asset", "alert_kind"]);
