import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { EventWatchStatus } from "./tables/watchlistEvents";

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Get all watchlist events for a user, with resolved event details.
 */
export const getWatchlistByUser = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    const items = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();

    const enriched = await Promise.all(
      items.map(async (item) => {
        const event = item.event ? await ctx.db.get(item.event) : null;
        return { ...item, event_details: event };
      })
    );

    return enriched;
  },
});

/**
 * Get a single watchlist item by user and event.
 */
export const getWatchlistItem = query({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .unique();
  },
});

/**
 * Get all active watchers of a specific event (stated watch or inferred watch).
 * Returns watchlist items with last_alerted_at for deduplication.
 */
export const getWatchersByEvent = query({
  args: { event: v.id("predictionEvents") },
  handler: async (ctx, args) => {
    const items = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_event", (q) => q.eq("event", args.event))
      .collect();

    return items.filter(
      (item) =>
        item.event_status === "stated watch" ||
        item.event_status === "inferred watch"
    );
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
      .query("watchlistEvents")
      .collect();

    return inferredItems.filter(
      (item) =>
        item.event_status === "inferred watch" &&
        (item.last_mentioned_at === undefined ||
          item.last_mentioned_at < thirtyDaysAgo)
    );
  },
});

/**
 * Get distinct watched event IDs (events that have at least one active watcher).
 * Used by the probability poller to know which events to fetch from Polymarket.
 */
export const getDistinctWatchedEventIds = query({
  args: {},
  handler: async (ctx) => {
    const items = await ctx.db
      .query("watchlistEvents")
      .collect();

    const activeItems = items.filter(
      (item) =>
        item.event !== undefined &&
        (item.event_status === "stated watch" ||
          item.event_status === "inferred watch")
    );

    // Deduplicate event IDs
    const eventIds = [...new Set(activeItems.map((item) => item.event!))];
    return eventIds;
  },
});

/**
 * Get a watchlist event by user and event.
 * Alias for getWatchlistItem used by the alert checker.
 */
export const getWatchlistEvent = query({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .unique();
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Add an event to the user's watchlist.
 * - If no existing item, creates with "stated watch".
 * - If existing "pending inferred watch" or "inferred watch", upgrades to "stated watch".
 * - If already "stated watch", no-op (returns existing).
 */
export const addToWatchlist = mutation({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .unique();

    if (existing) {
      if (
        existing.event_status === "pending inferred watch" ||
        existing.event_status === "inferred watch"
      ) {
        await ctx.db.patch(existing._id, { event_status: "stated watch" });
        return { ...existing, event_status: "stated watch" };
      }
      return existing;
    }

    const id = await ctx.db.insert("watchlistEvents", {
      user: args.user,
      event: args.event,
      event_status: "stated watch",
    });

    return await ctx.db.get(id);
  },
});

/**
 * Add an inferred watch (called by AI when user mentions a prediction event).
 * Uses a 7-day rolling window for promotion:
 * - If no existing item, creates with "pending inferred watch" (mention_count = 1).
 * - If existing "pending inferred watch" and first_mention_at is within 7 days,
 *   increments mention count. When count reaches 3, upgrades to "inferred watch".
 * - If first_mention_at is older than 7 days, resets the window (count = 1).
 * - If already "inferred watch" or "stated watch", no-op.
 */
export const addInferredWatch = mutation({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;

    const existing = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .unique();

    if (existing) {
      if (existing.event_status === "pending inferred watch") {
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
            event_status: "inferred watch",
            inferred_mention_count: newCount,
          });
          return { ...existing, event_status: "inferred watch", inferred_mention_count: newCount };
        }
        await ctx.db.patch(existing._id, { inferred_mention_count: newCount });
        return { ...existing, inferred_mention_count: newCount };
      }
      return existing;
    }

    const id = await ctx.db.insert("watchlistEvents", {
      user: args.user,
      event: args.event,
      event_status: "pending inferred watch",
      inferred_mention_count: 1,
      first_mention_at: now,
    });

    return await ctx.db.get(id);
  },
});

/**
 * Remove an event from the watchlist.
 * Deletes items with "pending inferred watch", "inferred watch", or "stated watch" status.
 */
export const removeFromWatchlist = mutation({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .unique();

    if (!existing) {
      throw new Error("Watchlist event not found");
    }

    await ctx.db.delete(existing._id);
    return true;
  },
});

/**
 * Stamp last_alerted_at on a watchlist event after sending a prediction alert.
 * When is_override is true, stamps override_alerted_at instead (one-time 2x bypass).
 * When is_override is false, stamps last_alerted_at and clears override_alerted_at.
 */
export const stampAlerted = mutation({
  args: {
    id: v.id("watchlistEvents"),
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
 * Update last_mentioned_at timestamp for an event interest.
 * Called by the watchlist inferrer on every mention.
 */
export const stampMentioned = mutation({
  args: {
    user: v.id("users"),
    event: v.id("predictionEvents"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
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
    event: v.id("predictionEvents"),
    module: v.id("modules"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
      )
      .unique();

    if (!existing) {
      throw new Error("Watchlist event not found");
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
    event: v.id("predictionEvents"),
    module: v.id("modules"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("watchlistEvents")
      .withIndex("by_user_event", (q) =>
        q.eq("user", args.user).eq("event", args.event)
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
