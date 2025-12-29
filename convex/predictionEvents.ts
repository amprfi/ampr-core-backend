import { v } from "convex/values";
import { query } from "./_generated/server";

/**
 * Get all active tracked prediction events
 */
export const getActiveEvents = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db
      .query("predictionEvents")
      .withIndex("by_active", (q) => q.eq("active", true))
      .collect();
  },
});

/**
 * Get all tracked prediction events
 */
export const getAllEvents = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("predictionEvents").collect();
  },
});

/**
 * Get a prediction event by slug
 */
export const getEventBySlug = query({
  args: { slug: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("predictionEvents")
      .withIndex("by_slug", (q) => q.eq("slug", args.slug))
      .unique();
  },
});
