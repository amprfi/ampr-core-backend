import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { PredictionAlertKind } from "./tables/predictionAlerts";

// Default thresholds used when creating initial alert registrations.
// These are baked into predictionAlerts rows at registration time, not used as
// runtime fallbacks. Exported for use in the registration mutation.
// Values are decimals (0.05 = 5% probability change) since Polymarket prices
// range from 0 to 1.
export const DEFAULT_THRESHOLD_24H_PCT = 0.05;
export const DEFAULT_THRESHOLD_7D_PCT = 0.10;

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Resolve the effective percentage threshold for a user + event + alert kind.
 *
 * Resolution order:
 * 1. Per-user per-event threshold for this alert kind
 * 2. Per-user default threshold for this alert kind (event is undefined)
 * 3. null — no registration exists, no alert should fire
 */
export const getEffectiveThreshold = query({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
    alert_kind: v.optional(PredictionAlertKind),
  },
  handler: async (ctx, args) => {
    const kind = args.alert_kind ?? "percentage_24h";

    const userAlerts = await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const kindAlerts = userAlerts.filter((t) => t.alert_kind === kind);

    // 1. Per-user per-event
    const eventAlert = kindAlerts.find(
      (t) => t.event !== undefined && t.event === args.event
    );
    if (eventAlert) {
      return eventAlert.threshold_pct;
    }

    // 2. Per-user default
    const userDefault = kindAlerts.find((t) => t.event === undefined);
    if (userDefault) {
      return userDefault.threshold_pct;
    }

    // 3. No registration — return null so alert checker skips this user+event
    return null;
  },
});

/**
 * Get all prediction alerts configured by a user.
 */
export const getUserAlerts = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();
  },
});

/**
 * Get all percentage alerts for a specific event (across all users).
 * Used by the alert checker to find registered user+event combos to check.
 */
export const getPercentageAlertsByEvent = query({
  args: { event: v.id("predictionEvents") },
  handler: async (ctx, args) => {
    const alerts = await ctx.db
      .query("predictionAlerts")
      .withIndex("by_event_alert_kind", (q) => q.eq("event", args.event))
      .collect();

    return alerts.filter(
      (a) => a.alert_kind === "percentage_24h" || a.alert_kind === "percentage_7d"
    );
  },
});

/**
 * Get alerts for a specific user + event combination.
 */
export const getUserEventAlerts = query({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .collect();
  },
});

/**
 * Get a percentage alert for a specific user + event + alert_kind.
 * Used by the alert checker for per-period deduplication.
 */
export const getPercentageAlert = query({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
    alert_kind: PredictionAlertKind,
  },
  handler: async (ctx, args) => {
    const alerts = await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
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
 * - With event: sets per-event threshold
 * - Without event: sets user default threshold
 */
export const setPercentageThreshold = mutation({
  args: {
    user: v.id("users"),
    event: v.optional(v.id("predictionEvents")),
    alert_kind: PredictionAlertKind,
    notification_type: v.id("notificationTypes"),
    threshold_pct: v.float64(),
  },
  handler: async (ctx, args) => {
    const userAlerts = await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const existing = userAlerts.find(
      (t) =>
        t.alert_kind === args.alert_kind &&
        (args.event ? t.event === args.event : t.event === undefined)
    );

    if (existing) {
      await ctx.db.patch(existing._id, {
        threshold_pct: args.threshold_pct,
        notification_type: args.notification_type,
      });
      return existing._id;
    }

    return await ctx.db.insert("predictionAlerts", {
      user: args.user,
      event: args.event,
      alert_kind: args.alert_kind,
      notification_type: args.notification_type,
      threshold_pct: args.threshold_pct,
    });
  },
});

/**
 * Create default percentage alert rows for a user + event.
 * Called by a module's register_notifications() when an event is added to the watchlist.
 * No-op for any alert_kind that already has a row for this user + event.
 */
export const registerDefaultAlerts = mutation({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
    notification_type_24h: v.id("notificationTypes"),
    notification_type_7d: v.id("notificationTypes"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .collect();

    const created: string[] = [];

    // Create percentage_24h if not already registered
    if (!existing.find((a) => a.alert_kind === "percentage_24h")) {
      const id = await ctx.db.insert("predictionAlerts", {
        user: args.user,
        event: args.event,
        alert_kind: "percentage_24h",
        notification_type: args.notification_type_24h,
        threshold_pct: DEFAULT_THRESHOLD_24H_PCT,
      });
      created.push(id);
    }

    // Create percentage_7d if not already registered
    if (!existing.find((a) => a.alert_kind === "percentage_7d")) {
      const id = await ctx.db.insert("predictionAlerts", {
        user: args.user,
        event: args.event,
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
 * Remove a prediction alert.
 */
export const removeAlert = mutation({
  args: { id: v.id("predictionAlerts") },
  handler: async (ctx, args) => {
    await ctx.db.delete(args.id);
    return true;
  },
});

/**
 * Remove all alerts for a user + event combination.
 * Used by the interest expiration job when deregistering module notifications.
 */
export const removeAlertsByUserEvent = mutation({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    const alerts = await ctx.db
      .query("predictionAlerts")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .collect();

    for (const alert of alerts) {
      await ctx.db.delete(alert._id);
    }

    return alerts.length;
  },
});

/**
 * Stamp last_triggered_at on a prediction alert after it fires.
 * Used for per-period deduplication.
 */
export const stampTriggered = mutation({
  args: {
    id: v.id("predictionAlerts"),
    last_triggered_at: v.float64(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.id, { last_triggered_at: args.last_triggered_at });
  },
});
