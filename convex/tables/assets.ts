import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validators for asset categories
 */
export const AssetCategory = v.union(
  v.literal("cryptotoken"),
  v.literal("stock"),
  v.literal("currency"),
  v.literal("commodity")
);

export const assets = defineTable({
  ticker: v.optional(v.string()),
  name: v.optional(v.string()),
  liquid: v.boolean(),
  asset_category: AssetCategory,
})
  .index("by_ticker", ["ticker"])
  .index("by_category", ["asset_category"]);
