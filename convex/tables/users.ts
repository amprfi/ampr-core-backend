import { defineTable } from "convex/server";
import { v } from "convex/values";

export const users = defineTable({
  first_name: v.optional(v.string()),
  last_name: v.optional(v.string()),
  email: v.optional(v.string()),
  phone: v.optional(v.string()),
  telegram_id: v.optional(v.string()),
})
  .index("by_email", ["email"])
  .index("by_phone", ["phone"])
  .index("by_telegram_id", ["telegram_id"]);
