import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

// Global default threshold if user has no configuration
const GLOBAL_DEFAULT_THRESHOLD_PCT = 0.1;

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Resolve the effective threshold for a user + asset.
 *
 * Resolution order:
 * 1. Per-user per-asset threshold
 * 2. Per-user default threshold (asset is undefined)
 * 3. Global default constant
 */
export const getEffectiveThreshold = query({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    const userThresholds = await ctx.db
      .query("alertThresholds")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    // 1. Per-user per-asset
    const assetThreshold = userThresholds.find(
      (t) => t.asset !== undefined && t.asset === args.asset
    );
    if (assetThreshold) {
      return assetThreshold.threshold_pct;
    }

    // 2. Per-user default
    const userDefault = userThresholds.find((t) => t.asset === undefined);
    if (userDefault) {
      return userDefault.threshold_pct;
    }

    // 3. Global default
    return GLOBAL_DEFAULT_THRESHOLD_PCT;
  },
});

/**
 * Get all alert thresholds configured by a user.
 */
export const getUserThresholds = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("alertThresholds")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Set a threshold for a user.
 * - With asset: sets per-asset threshold
 * - Without asset: sets user default threshold
 */
export const setThreshold = mutation({
  args: {
    user: v.id("users"),
    asset: v.optional(v.id("assets")),
    threshold_pct: v.float64(),
  },
  handler: async (ctx, args) => {
    const userThresholds = await ctx.db
      .query("alertThresholds")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const existing = args.asset
      ? userThresholds.find((t) => t.asset === args.asset)
      : userThresholds.find((t) => t.asset === undefined);

    if (existing) {
      await ctx.db.patch(existing._id, { threshold_pct: args.threshold_pct });
      return existing._id;
    }

    return await ctx.db.insert("alertThresholds", {
      user: args.user,
      asset: args.asset,
      threshold_pct: args.threshold_pct,
    });
  },
});

/**
 * Remove a threshold (reverts to next level in the hierarchy).
 */
export const removeThreshold = mutation({
  args: { id: v.id("alertThresholds") },
  handler: async (ctx, args) => {
    await ctx.db.delete(args.id);
    return true;
  },
});
