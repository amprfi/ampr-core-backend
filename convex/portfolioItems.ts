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
 * Uses a 7-day rolling window for promotion:
 * - If no existing item, creates with "pending inferred watch" (mention_count = 1).
 * - If existing "pending inferred watch" and first_mention_at is within 7 days,
 *   increments mention count. When count reaches 3, upgrades to "inferred watch".
 * - If first_mention_at is older than 7 days, resets the window (count = 1).
 * - If already "inferred watch", "stated watch", or "owned", no-op.
 */
export const addInferredWatch = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;

    const existing = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();

    if (existing) {
      if (existing.asset_status === "pending inferred watch") {
        const firstMention = existing.first_mention_at ?? existing._creationTime;
        const windowExpired = (now - firstMention) > sevenDaysMs;

        if (windowExpired) {
          // Reset rolling window
          await ctx.db.patch(existing._id, {
            inferred_mention_count: 1,
            first_mention_at: now,
          });
          return { ...existing, inferred_mention_count: 1, first_mention_at: now };
        }

        const newCount = (existing.inferred_mention_count ?? 1) + 1;
        if (newCount >= 3) {
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
      first_mention_at: now,
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
 * When is_override is true, stamps override_alerted_at instead (one-time 2x bypass).
 * When is_override is false, stamps last_alerted_at and clears override_alerted_at.
 */
export const stampAlerted = mutation({
  args: {
    id: v.id("portfolioItems"),
    last_alerted_at: v.float64(),
    is_override: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    if (args.is_override) {
      await ctx.db.patch(args.id, { override_alerted_at: args.last_alerted_at });
    } else {
      await ctx.db.patch(args.id, {
        last_alerted_at: args.last_alerted_at,
        override_alerted_at: undefined,
      });
    }
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

/**
 * Update last_mentioned_at timestamp for an asset interest.
 * Called by the watchlist inferrer on every mention.
 */
export const stampMentioned = mutation({
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
      await ctx.db.patch(existing._id, { last_mentioned_at: Date.now() });
    }
  },
});

/**
 * Add a module to an interest's notification_modules array.
 * Idempotent — skips if module already present.
 */
export const addNotificationModule = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    module: v.id("modules"),
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

    const modules = existing.notification_modules ?? [];
    if (modules.includes(args.module)) {
      return existing._id;
    }

    await ctx.db.patch(existing._id, {
      notification_modules: [...modules, args.module],
    });
    return existing._id;
  },
});

/**
 * Remove a module from an interest's notification_modules array.
 */
export const removeNotificationModule = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    module: v.id("modules"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("portfolioItems")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .unique();

    if (!existing) {
      return;
    }

    const modules = existing.notification_modules ?? [];
    await ctx.db.patch(existing._id, {
      notification_modules: modules.filter((m) => m !== args.module),
    });
  },
});

/**
 * Get expired inferred watches — inferred watches not mentioned in the last 30 days.
 * Used by the expiration background job.
 */
export const getExpiredInferredWatches = query({
  args: {},
  handler: async (ctx) => {
    const thirtyDaysAgo = Date.now() - 30 * 24 * 60 * 60 * 1000;

    const inferredItems = await ctx.db
      .query("portfolioItems")
      .collect();

    return inferredItems.filter(
      (item) =>
        item.asset_status === "inferred watch" &&
        (item.last_mentioned_at === undefined ||
          item.last_mentioned_at < thirtyDaysAgo)
    );
  },
});
