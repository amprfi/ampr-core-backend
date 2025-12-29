import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Tracked prediction events from Polymarket.
 * Manually curated list of events the oracle agent can query.
 */
export const predictionEvents = defineTable({
  slug: v.string(),
  title: v.string(),
  description: v.optional(v.string()),
  tags: v.optional(v.array(v.string())),
  active: v.boolean(),
  endDate: v.optional(v.string()),
})
  .index("by_slug", ["slug"])
  .index("by_active", ["active"]);
