import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Alert thresholds - configures price change % that triggers notifications.
 *
 * Three-tier resolution:
 * 1. Per-user per-asset: user + asset set → threshold for a specific asset
 * 2. Per-user default: user set, asset null → fallback for all user's assets
 * 3. Global default: hardcoded constant (no row needed)
 */
export const alertThresholds = defineTable({
  user: v.id("users"),
  asset: v.optional(v.id("assets")),
  threshold_pct: v.float64(),
})
  .index("by_user", ["user"])
  .index("by_user_asset", ["user", "asset"]);
