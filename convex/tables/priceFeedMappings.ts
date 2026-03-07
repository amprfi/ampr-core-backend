import { defineTable } from "convex/server";
import { v } from "convex/values";
import { PriceFeed } from "./assets";

/**
 * Price feed mappings - maps assets to external price provider identifiers.
 * Maintains abstraction between internal assets and external data sources.
 *
 * Example: asset "Bitcoin" → price_feed "defianalyst" → external_id "bitcoin" (CoinGecko ID)
 */
export const priceFeedMappings = defineTable({
  asset: v.id("assets"),
  price_feed: PriceFeed,
  external_id: v.string(),
})
  .index("by_asset", ["asset"])
  .index("by_price_feed", ["price_feed"])
  .index("by_price_feed_external_id", ["price_feed", "external_id"]);
