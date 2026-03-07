import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Get an asset by ID.
 */
export const getAsset = query({
  args: { id: v.id("assets") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Get an asset by ticker symbol.
 */
export const getAssetByTicker = query({
  args: { ticker: v.string() },
  handler: async (ctx, args) => {
    const ticker = args.ticker.toUpperCase();
    return await ctx.db
      .query("assets")
      .withIndex("by_ticker", (q) => q.eq("ticker", ticker))
      .first();
  },
});

/**
 * Search for an asset by name (full-text search).
 * Returns the best match, if any.
 */
export const searchAssetByName = query({
  args: { name: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("assets")
      .withSearchIndex("search_name", (q) => q.search("name", args.name))
      .first();
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Bulk update price data for multiple assets.
 * Called by the price poller after fetching market data.
 */
export const updateAssetPrices = mutation({
  args: {
    updates: v.array(
      v.object({
        asset_id: v.id("assets"),
        current_price_usd: v.float64(),
        price_change_pct_24h: v.optional(v.float64()),
        price_change_pct_7d: v.optional(v.float64()),
        price_updated_at: v.float64(),
      })
    ),
  },
  handler: async (ctx, args) => {
    for (const update of args.updates) {
      await ctx.db.patch(update.asset_id, {
        current_price_usd: update.current_price_usd,
        price_change_pct_24h: update.price_change_pct_24h,
        price_change_pct_7d: update.price_change_pct_7d,
        price_updated_at: update.price_updated_at,
      });
    }
    return args.updates.length;
  },
});

/**
 * Create an asset (if it doesn't already exist by ticker).
 */
export const createAsset = mutation({
  args: {
    ticker: v.optional(v.string()),
    name: v.optional(v.string()),
    liquid: v.boolean(),
    asset_category: v.union(
      v.literal("cryptotoken"),
      v.literal("stock"),
      v.literal("currency"),
      v.literal("commodity")
    ),
    price_feed: v.optional(v.union(v.literal("defianalyst"))),
  },
  handler: async (ctx, args) => {
    const ticker = args.ticker?.toUpperCase();

    if (ticker) {
      const existing = await ctx.db
        .query("assets")
        .withIndex("by_ticker", (q) => q.eq("ticker", ticker))
        .first();

      if (existing) {
        return existing;
      }
    }

    const id = await ctx.db.insert("assets", { ...args, ticker });
    return await ctx.db.get(id);
  },
});
