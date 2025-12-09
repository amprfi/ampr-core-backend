import { defineTable } from "convex/server";
import { v } from "convex/values";

export const users = defineTable({
  first_name: v.string(),
  last_name: v.string(),
  email: v.string(),
  phone: v.string(),
  telegram_id: v.optional(v.string()),
})
  .index("by_email", ["email"])
  .index("by_phone", ["phone"])
  .index("by_telegram_id", ["telegram_id"]);
