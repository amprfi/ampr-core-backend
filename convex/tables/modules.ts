import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Modules registry - third-party modules register here to get a unique ID.
 * The "ampr" module is reserved for system notifications.
 */
export const modules = defineTable({
  name: v.string(),
  description: v.optional(v.string()),
})
  .index("by_name", ["name"]);
