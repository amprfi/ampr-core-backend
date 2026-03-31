import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validators for event watch status
 */
export const EventWatchStatus = v.union(
  v.literal("pending inferred watch"),
  v.literal("inferred watch"),
  v.literal("stated watch")
);

/**
 * Watchlist events junction table - many-to-many relationship between users and prediction events.
 * Parallel to portfolioItems but for prediction events (Oracle module).
 *
 * notification_modules: Array of module IDs that have notification registrations
 * tied to this interest. Used by the expiration job to deregister module-level
 * notifications when an inferred interest expires (30 days without mention).
 *
 * last_mentioned_at: Timestamp of the user's most recent mention of this event.
 * Used for 30-day expiration of inferred watches and the 3-mentions-in-a-week
 * inference threshold.
 */
export const watchlistEvents = defineTable({
  user: v.id("users"),
  event: v.optional(v.id("predictionEvents")),
  event_status: EventWatchStatus,
  inferred_mention_count: v.optional(v.float64()),
  last_alerted_at: v.optional(v.float64()),
  override_alerted_at: v.optional(v.float64()),
  notification_modules: v.optional(v.array(v.id("modules"))),
  last_mentioned_at: v.optional(v.float64()),
  first_mention_at: v.optional(v.float64()),
})
  .index("by_user", ["user"])
  .index("by_event", ["event"])
  .index("by_user_event", ["user", "event"])
  .index("by_user_status", ["user", "event_status"]);
