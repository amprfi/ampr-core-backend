import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { AlertKind, PriceDirection } from "./tables/priceAlerts";

// Default thresholds used when creating initial alert registrations.
// These are baked into priceAlerts rows at registration time, not used as
// runtime fallbacks. Exported for use in the registration mutation.
export const DEFAULT_THRESHOLD_24H_PCT = 5.0;
export const DEFAULT_THRESHOLD_7D_PCT = 10.0;

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Resolve the effective percentage threshold for a user + asset + alert kind.
 *
 * Resolution order:
 * 1. Per-user per-asset threshold for this alert kind
 * 2. Per-user default threshold for this alert kind (asset is undefined)
 * 3. null — no registration exists, no alert should fire
 */
export const getEffectiveThreshold = query({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    alert_kind: v.optional(AlertKind),
  },
  handler: async (ctx, args) => {
    const kind = args.alert_kind ?? "percentage_24h";

    if (kind === "absolute_price") {
      return null;
    }

    const userAlerts = await ctx.db
      .query("priceAlerts")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const kindAlerts = userAlerts.filter((t) => t.alert_kind === kind);

    // 1. Per-user per-asset
    const assetAlert = kindAlerts.find(
      (t) => t.asset !== undefined && t.asset === args.asset
    );
    if (assetAlert) {
      return assetAlert.threshold_pct;
    }

    // 2. Per-user default
    const userDefault = kindAlerts.find((t) => t.asset === undefined);
    if (userDefault) {
      return userDefault.threshold_pct;
    }

    // 3. No registration — return null so alert checker skips this user+asset
    return null;
  },
});

/**
 * Get all price alerts configured by a user.
 */
export const getUserAlerts = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceAlerts")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();
  },
});

/**
 * Get all percentage alerts for a specific asset (across all users).
 * Used by the alert checker to find registered user+asset combos to check.
 */
export const getPercentageAlertsByAsset = query({
  args: { asset: v.id("assets") },
  handler: async (ctx, args) => {
    const alerts = await ctx.db
      .query("priceAlerts")
      .withIndex("by_asset_alert_kind", (q) => q.eq("asset", args.asset))
      .collect();

    return alerts.filter(
      (a) => a.alert_kind === "percentage_24h" || a.alert_kind === "percentage_7d"
    );
  },
});

/**
 * Get all active absolute price alerts for a specific asset.
 * Used by the price poller to check if any thresholds have been crossed.
 */
export const getAbsolutePriceAlerts = query({
  args: { asset: v.id("assets") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceAlerts")
      .withIndex("by_asset_alert_kind", (q) =>
        q.eq("asset", args.asset).eq("alert_kind", "absolute_price")
      )
      .collect();
  },
});

/**
 * Get all absolute price alerts for a user.
 */
export const getUserAbsolutePriceAlerts = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceAlerts")
      .withIndex("by_user_alert_kind", (q) =>
        q.eq("user", args.user).eq("alert_kind", "absolute_price")
      )
      .collect();
  },
});

/**
 * Get alerts for a specific user + asset combination.
 */
export const getUserAssetAlerts = query({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("priceAlerts")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .collect();
  },
});

/**
 * Get a percentage alert for a specific user + asset + alert_kind.
 * Used by the alert checker for per-period deduplication.
 */
export const getPercentageAlert = query({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    alert_kind: AlertKind,
  },
  handler: async (ctx, args) => {
    const alerts = await ctx.db
      .query("priceAlerts")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .collect();

    return alerts.find((a) => a.alert_kind === args.alert_kind) ?? null;
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Set a percentage threshold for a user.
 * - With asset: sets per-asset threshold
 * - Without asset: sets user default threshold
 */
export const setPercentageThreshold = mutation({
  args: {
    user: v.id("users"),
    asset: v.optional(v.id("assets")),
    alert_kind: AlertKind,
    notification_type: v.id("notificationTypes"),
    threshold_pct: v.float64(),
  },
  handler: async (ctx, args) => {
    if (args.alert_kind === "absolute_price") {
      throw new Error("Use createAbsolutePriceAlert for absolute price alerts");
    }

    const userAlerts = await ctx.db
      .query("priceAlerts")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const existing = userAlerts.find(
      (t) =>
        t.alert_kind === args.alert_kind &&
        (args.asset ? t.asset === args.asset : t.asset === undefined)
    );

    if (existing) {
      await ctx.db.patch(existing._id, {
        threshold_pct: args.threshold_pct,
        notification_type: args.notification_type,
      });
      return existing._id;
    }

    return await ctx.db.insert("priceAlerts", {
      user: args.user,
      asset: args.asset,
      alert_kind: args.alert_kind,
      notification_type: args.notification_type,
      threshold_pct: args.threshold_pct,
    });
  },
});

/**
 * Create an absolute price alert.
 * Validates that the current price is on the opposite side of the target.
 */
export const createAbsolutePriceAlert = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    notification_type: v.id("notificationTypes"),
    direction: PriceDirection,
    target_price: v.float64(),
    current_price: v.float64(),
  },
  handler: async (ctx, args) => {
    // Validate current price is on the correct side of target
    if (args.direction === "above" && args.current_price >= args.target_price) {
      throw new Error(
        `Current price (${args.current_price}) is already above target (${args.target_price})`
      );
    }
    if (args.direction === "below" && args.current_price <= args.target_price) {
      throw new Error(
        `Current price (${args.current_price}) is already below target (${args.target_price})`
      );
    }

    return await ctx.db.insert("priceAlerts", {
      user: args.user,
      asset: args.asset,
      alert_kind: "absolute_price",
      notification_type: args.notification_type,
      direction: args.direction,
      target_price: args.target_price,
    });
  },
});

/**
 * Create default percentage alert rows for a user + asset.
 * Called by a module's register_notifications() when an asset is added to the watchlist.
 * No-op for any alert_kind that already has a row for this user + asset.
 */
export const registerDefaultAlerts = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
    notification_type_24h: v.id("notificationTypes"),
    notification_type_7d: v.id("notificationTypes"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("priceAlerts")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .collect();

    const created: string[] = [];

    // Create percentage_24h if not already registered
    if (!existing.find((a) => a.alert_kind === "percentage_24h")) {
      const id = await ctx.db.insert("priceAlerts", {
        user: args.user,
        asset: args.asset,
        alert_kind: "percentage_24h",
        notification_type: args.notification_type_24h,
        threshold_pct: DEFAULT_THRESHOLD_24H_PCT,
      });
      created.push(id);
    }

    // Create percentage_7d if not already registered
    if (!existing.find((a) => a.alert_kind === "percentage_7d")) {
      const id = await ctx.db.insert("priceAlerts", {
        user: args.user,
        asset: args.asset,
        alert_kind: "percentage_7d",
        notification_type: args.notification_type_7d,
        threshold_pct: DEFAULT_THRESHOLD_7D_PCT,
      });
      created.push(id);
    }

    return created.length;
  },
});

/**
 * Remove a price alert (reverts to next level in the hierarchy for
 * percentage alerts; deletes the alert for absolute price alerts).
 */
export const removeAlert = mutation({
  args: { id: v.id("priceAlerts") },
  handler: async (ctx, args) => {
    await ctx.db.delete(args.id);
    return true;
  },
});

/**
 * Remove all alerts for a user + asset combination.
 * Used by the interest expiration job when deregistering module notifications.
 */
export const removeAlertsByUserAsset = mutation({
  args: {
    user: v.id("users"),
    asset: v.id("assets"),
  },
  handler: async (ctx, args) => {
    const alerts = await ctx.db
      .query("priceAlerts")
      .withIndex("by_user_asset", (q) =>
        q.eq("user", args.user).eq("asset", args.asset)
      )
      .collect();

    for (const alert of alerts) {
      await ctx.db.delete(alert._id);
    }

    return alerts.length;
  },
});

/**
 * Stamp last_triggered_at on a price alert after it fires.
 * Used for per-period deduplication.
 */
export const stampTriggered = mutation({
  args: {
    id: v.id("priceAlerts"),
    last_triggered_at: v.float64(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.id, { last_triggered_at: args.last_triggered_at });
  },
});
