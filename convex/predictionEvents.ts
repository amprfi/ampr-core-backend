import { v } from "convex/values";
import { query, mutation } from "./_generated/server";

/**
 * Get all active prediction events
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
 * Get all prediction events
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

/**
 * Search active prediction events by text query
 */
export const searchEvents = query({
  args: { query: v.string(), limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const maxResults = args.limit ?? 20;
    return await ctx.db
      .query("predictionEvents")
      .withSearchIndex("search_events", (q) =>
        q.search("searchText", args.query).eq("active", true)
      )
      .take(maxResults);
  },
});

/**
 * Upsert a prediction event by polymarketId.
 * Creates if not found, updates if exists.
 */
export const upsertEvent = mutation({
  args: {
    polymarketId: v.string(),
    slug: v.string(),
    title: v.string(),
    description: v.optional(v.string()),
    tags: v.optional(v.array(v.string())),
    endDate: v.optional(v.string()),
    active: v.boolean(),
    closed: v.boolean(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("predictionEvents")
      .withIndex("by_polymarketId", (q) =>
        q.eq("polymarketId", args.polymarketId)
      )
      .unique();

    const searchText = args.description
      ? `${args.title} | ${args.description}`
      : args.title;

    if (existing) {
      await ctx.db.patch(existing._id, {
        slug: args.slug,
        title: args.title,
        description: args.description,
        searchText,
        tags: args.tags,
        endDate: args.endDate,
        active: args.active,
        closed: args.closed,
      });
      return existing._id;
    }

    return await ctx.db.insert("predictionEvents", {
      polymarketId: args.polymarketId,
      slug: args.slug,
      title: args.title,
      description: args.description,
      searchText,
      tags: args.tags,
      endDate: args.endDate,
      active: args.active,
      closed: args.closed,
      historical: false,
    });
  },
});

/**
 * Bulk upsert prediction events.
 * Accepts an array of events and upserts each one.
 * Returns the count of created and updated events.
 */
export const bulkUpsertEvents = mutation({
  args: {
    events: v.array(
      v.object({
        polymarketId: v.string(),
        slug: v.string(),
        title: v.string(),
        description: v.optional(v.string()),
        tags: v.optional(v.array(v.string())),
        endDate: v.optional(v.string()),
        active: v.boolean(),
        closed: v.boolean(),
      })
    ),
  },
  handler: async (ctx, args) => {
    let created = 0;
    let updated = 0;

    for (const event of args.events) {
      const existing = await ctx.db
        .query("predictionEvents")
        .withIndex("by_polymarketId", (q) =>
          q.eq("polymarketId", event.polymarketId)
        )
        .unique();

      const searchText = event.description
        ? `${event.title} | ${event.description}`
        : event.title;

      if (existing) {
        await ctx.db.patch(existing._id, {
          slug: event.slug,
          title: event.title,
          description: event.description,
          searchText,
          tags: event.tags,
          endDate: event.endDate,
          active: event.active,
          closed: event.closed,
        });
        updated++;
      } else {
        await ctx.db.insert("predictionEvents", {
          polymarketId: event.polymarketId,
          slug: event.slug,
          title: event.title,
          description: event.description,
          searchText,
          tags: event.tags,
          endDate: event.endDate,
          active: event.active,
          closed: event.closed,
          historical: false,
        });
        created++;
      }
    }

    return { created, updated };
  },
});

/**
 * Mark events as historical by their IDs.
 */
export const markEventsHistorical = mutation({
  args: { ids: v.array(v.id("predictionEvents")) },
  handler: async (ctx, args) => {
    for (const id of args.ids) {
      await ctx.db.patch(id, { historical: true });
    }
    return args.ids.length;
  },
});

/**
 * Delete events by their IDs.
 */
export const deleteEvents = mutation({
  args: { ids: v.array(v.id("predictionEvents")) },
  handler: async (ctx, args) => {
    for (const id of args.ids) {
      await ctx.db.delete(id);
    }
    return args.ids.length;
  },
});

/**
 * Get inactive, non-historical events for lifecycle processing.
 */
export const getInactiveEvents = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db
      .query("predictionEvents")
      .withIndex("by_active_historical", (q) =>
        q.eq("active", false).eq("historical", false)
      )
      .collect();
  },
});
