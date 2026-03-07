import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { PriceFeed } from "./tables/assets";

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Get price feed mappings for assets that are actively watched or owned by at least one user.
 * This is the primary entry point for the price poller.
 */
export const getWatchedPriceFeedMappings = query({
  args: { price_feed: PriceFeed },
  handler: async (ctx, args) => {
    const allItems = await ctx.db
      .query("portfolioItems")
      .collect();

    const watchedAssetIds = new Set(
      allItems
        .filter(
          (item) =>
            item.asset_status === "stated watch" ||
            item.asset_status === "inferred watch" ||
            item.asset_status === "owned"
        )
        .map((item) => item.asset.toString())
    );

    const mappings = await ctx.db
      .query("priceFeedMappings")
      .withIndex("by_price_feed", (q) => q.eq("price_feed", args.price_feed))
      .collect();

    return mappings.filter((m) => watchedAssetIds.has(m.asset.toString()));
  },
});

/**
 * Get all price feed mappings for an asset.
 */
export const getMappingsByAsset = query({
  args: { asset: v.id("assets") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceFeedMappings")
      .withIndex("by_asset", (q) => q.eq("asset", args.asset))
      .collect();
  },
});

/**
 * Get all mappings for a specific price feed provider.
 * Used by the price poller to batch-fetch prices for all mapped assets.
 */
export const getMappingsByPriceFeed = query({
  args: { price_feed: PriceFeed },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceFeedMappings")
      .withIndex("by_price_feed", (q) => q.eq("price_feed", args.price_feed))
      .collect();
  },
});

/**
 * Look up a mapping by price feed and external ID.
 * Used to resolve an external identifier back to an internal asset.
 */
export const getMappingByExternalId = query({
  args: {
    price_feed: PriceFeed,
    external_id: v.string(),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceFeedMappings")
      .withIndex("by_price_feed_external_id", (q) =>
        q.eq("price_feed", args.price_feed).eq("external_id", args.external_id)
      )
      .unique();
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Create a price feed mapping for an asset.
 * If a mapping already exists for this asset + price_feed combo, updates the external_id.
 */
export const upsertMapping = mutation({
  args: {
    asset: v.id("assets"),
    price_feed: PriceFeed,
    external_id: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("priceFeedMappings")
      .withIndex("by_asset", (q) => q.eq("asset", args.asset))
      .collect();

    const match = existing.find((m) => m.price_feed === args.price_feed);

    if (match) {
      await ctx.db.patch(match._id, { external_id: args.external_id });
      return await ctx.db.get(match._id);
    }

    const id = await ctx.db.insert("priceFeedMappings", {
      asset: args.asset,
      price_feed: args.price_feed,
      external_id: args.external_id,
    });

    return await ctx.db.get(id);
  },
});

/**
 * Remove a price feed mapping.
 */
export const removeMapping = mutation({
  args: { id: v.id("priceFeedMappings") },
  handler: async (ctx, args) => {
    await ctx.db.delete(args.id);
    return true;
  },
});
