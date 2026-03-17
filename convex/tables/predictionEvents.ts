import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Tracked prediction events from Polymarket.
 * Auto-populated by the oracle background job based on configured tags.
 */
export const predictionEvents = defineTable({
  polymarketId: v.string(),
  slug: v.string(),
  title: v.string(),
  description: v.optional(v.string()),
  searchText: v.string(),
  tags: v.optional(v.array(v.string())),
  endDate: v.optional(v.string()),
  active: v.boolean(),
  closed: v.boolean(),
  historical: v.boolean(),
})
  .index("by_slug", ["slug"])
  .index("by_polymarketId", ["polymarketId"])
  .index("by_active", ["active"])
  .searchIndex("search_events", {
    searchField: "searchText",
    filterFields: ["active"],
  });
