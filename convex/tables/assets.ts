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

/**
 * Enum validators for native module to provide price feed
 */
export const PriceFeed = v.union(
  v.literal("defianalyst")
)

export const assets = defineTable({
  ticker: v.optional(v.string()),
  name: v.optional(v.string()),
  liquid: v.boolean(),
  asset_category: AssetCategory,
  price_feed: v.optional(PriceFeed),
  current_price_usd: v.optional(v.float64()),
  price_change_pct_24h: v.optional(v.float64()),
  price_change_pct_7d: v.optional(v.float64()),
  price_updated_at: v.optional(v.float64()),
})
  .index("by_ticker", ["ticker"])
  .index("by_category", ["asset_category"])
  .searchIndex("search_name", {
    searchField: "name",
    filterFields: ["asset_category"],
  });
