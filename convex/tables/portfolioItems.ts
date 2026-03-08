import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validators for asset status
 */
export const AssetStatus = v.union(
  v.literal("pending inferred watch"),
  v.literal("inferred watch"),
  v.literal("stated watch"),
  v.literal("owned")
);

/**
 * Portfolio items junction table - many-to-many relationship between users and assets
 * Pattern: Junction table for many-to-many with additional relationship data (is_inferred)
 */
export const portfolioItems = defineTable({
  user: v.id("users"),
  asset: v.id("assets"),
  asset_status: AssetStatus,
  inferred_mention_count: v.optional(v.float64()),
  last_alerted_at: v.optional(v.float64()),
})
  .index("by_user", ["user"])
  .index("by_asset", ["asset"])
  .index("by_user_asset", ["user", "asset"])
  .index("by_user_status", ["user", "asset_status"])
