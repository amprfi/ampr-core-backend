import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { AssetStatus } from "./tables/portfolioItems";

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Get all portfolio items for a user, with resolved asset details.
 */
export const getPortfolioByUser = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    const items = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const enriched = await Promise.all(
      items.map(async (item) => {
        const asset = await ctx.db.get(item.asset);
        return { ...item, asset_details: asset };
      })
    );

    return enriched;
  },
});

/**
 * Get watchlist items for a user (stated watch + inferred watch only).
 */
export const getWatchlist = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    const items = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const watchItems = items.filter(
      (item) =>
        item.asset_status === "stated watch" ||
        item.asset_status === "inferred watch"
    );

    const enriched = await Promise.all(
      watchItems.map(async (item) => {
        const asset = await ctx.db.get(item.asset);
        return { ...item, asset_details: asset };
      })
    );

    return enriched;
  },
});

/**
 * Get owned assets for a user.
 */
export const getOwnedAssets = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    const items = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_status", (q) =>
        q.eq("user", args.user).eq("asset_status", "owned")
      )
      .collect();

    const enriched = await Promise.all(
      items.map(async (item) => {
        const asset = await ctx.db.get(item.asset);
        return { ...item, asset_details: asset };
      })
    );

    return enriched;
  },
});

/**
 * Get a single portfolio item by user and asset.
 */
export const getPortfolioItem = query({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();
  },
});

/**
 * Get all active watchers of a specific asset (stated watch, inferred watch, or owned).
 * Returns portfolio items with last_alerted_at for deduplication.
 */
export const getWatchersByAsset = query({
  args: { asset: v.id("assets") },
  handler: async (ctx, args) => {
    const items = await ctx.db
      .query("portfolioItems")
      .withIndex("by_asset", (q) => q.eq("asset", args.asset))
      .collect();

    return items.filter(
      (item) =>
        item.asset_status === "stated watch" ||
        item.asset_status === "inferred watch" ||
        item.asset_status === "owned"
    );
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Add an asset to the user's watchlist.
 * - If no existing item, creates with "stated watch".
 * - If existing "pending inferred watch" or "inferred watch", upgrades to "stated watch".
 * - If already "stated watch" or "owned", no-op (returns existing).
 */
export const addToWatchlist = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();

    if (existing) {
      if (
        existing.asset_status === "pending inferred watch" ||
        existing.asset_status === "inferred watch"
      ) {
        await ctx.db.patch(existing._id, { asset_status: "stated watch" });
        return { ...existing, asset_status: "stated watch" };
      }
      return existing;
    }

    const id = await ctx.db.insert("portfolioItems", {
      user: args.user,
      asset: args.asset,
      asset_status: "stated watch",
    });

    return await ctx.db.get(id);
  },
});

/**
 * Add an inferred watch (called by AI when user mentions an asset).
 * Four-step promotion:
 * - If no existing item, creates with "pending inferred watch" (mention_count = 1).
 * - If existing "pending inferred watch", increments mention count.
 * - When mention count reaches 4, upgrades to "inferred watch".
 * - If already "inferred watch", "stated watch", or "owned", no-op.
 */
export const addInferredWatch = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();

    if (existing) {
      if (existing.asset_status === "pending inferred watch") {
        const newCount = (existing.inferred_mention_count ?? 1) + 1;
        if (newCount >= 4) {
          await ctx.db.patch(existing._id, {
            asset_status: "inferred watch",
            inferred_mention_count: newCount,
          });
          return { ...existing, asset_status: "inferred watch", inferred_mention_count: newCount };
        }
        await ctx.db.patch(existing._id, { inferred_mention_count: newCount });
        return { ...existing, inferred_mention_count: newCount };
      }
      return existing;
    }

    const id = await ctx.db.insert("portfolioItems", {
      user: args.user,
      asset: args.asset,
      asset_status: "pending inferred watch",
      inferred_mention_count: 1,
    });

    return await ctx.db.get(id);
  },
});

/**
 * Remove an asset from the watchlist.
 * - Deletes items with "pending inferred watch", "inferred watch", or "stated watch" status.
 * - Does NOT delete "owned" items.
 */
export const removeFromWatchlist = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();

    if (!existing) {
      throw new Error("Portfolio item not found");
    }

    if (existing.asset_status === "owned") {
      throw new Error("Cannot remove an owned asset from watchlist");
    }

    await ctx.db.delete(existing._id);
    return true;
  },
});

/**
 * Stamp last_alerted_at on a portfolio item after sending a price alert.
 */
export const stampAlerted = mutation({
  args: {
    id: v.id("portfolioItems"),
    last_alerted_at: v.float64(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.id, { last_alerted_at: args.last_alerted_at });
  },
});

/**
 * Update the status of a portfolio item.
 */
export const updateAssetStatus = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    asset_status: AssetStatus,
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();

    if (!existing) {
      throw new Error("Portfolio item not found");
    }

    await ctx.db.patch(existing._id, { asset_status: args.asset_status });
    return await ctx.db.get(existing._id);
  },
});
