import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { NotificationQueueStatus } from "./tables/notifications";

// ============================================================================
// MODULES REGISTRY
// ============================================================================

/**
 * Register a module and get its unique ID.
 * If module already exists, returns existing ID.
 */
export const registerModule = mutation({
  args: {
    name: v.string(),
    description: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("modules")
      .withIndex("by_name", (q) => q.eq("name", args.name))
      .first();

    if (existing) {
      if (args.description) {
        await ctx.db.patch(existing._id, { description: args.description });
      }
      return existing._id;
    }

    return await ctx.db.insert("modules", args);
  },
});

/**
 * Get a module by name.
 */
export const getModuleByName = query({
  args: { name: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("modules")
      .withIndex("by_name", (q) => q.eq("name", args.name))
      .first();
  },
});

/**
 * Get a module by ID.
 */
export const getModule = query({
  args: { id: v.id("modules") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Get all registered modules.
 */
export const getAllModules = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("modules").collect();
  },
});

// ============================================================================
// NOTIFICATION TYPES REGISTRY
// ============================================================================

/**
 * Register a notification type for a module.
 * Called by modules at startup to register their notification types.
 * Returns the notification type _id for use when sending notifications.
 */
export const registerNotificationType = mutation({
  args: {
    module: v.id("modules"),
    name: v.string(),
    description: v.string(),
    default_enabled: v.boolean(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("notificationTypes")
      .withIndex("by_module_name", (q) =>
        q.eq("module", args.module).eq("name", args.name)
      )
      .first();

    if (existing) {
      await ctx.db.patch(existing._id, {
        description: args.description,
        default_enabled: args.default_enabled,
      });
      return existing._id;
    }

    return await ctx.db.insert("notificationTypes", args);
  },
});

/**
 * Get all notification types for a module.
 */
export const getNotificationTypesByModule = query({
  args: { module: v.id("modules") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("notificationTypes")
      .withIndex("by_module", (q) => q.eq("module", args.module))
      .collect();
  },
});

/**
 * Get all registered notification types (for preference management).
 */
export const getAllNotificationTypes = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("notificationTypes").collect();
  },
});

/**
 * Get a specific notification type by ID.
 */
export const getNotificationType = query({
  args: { id: v.id("notificationTypes") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Get a notification type by module and name.
 */
export const getNotificationTypeByName = query({
  args: { module: v.id("modules"), name: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("notificationTypes")
      .withIndex("by_module_name", (q) =>
        q.eq("module", args.module).eq("name", args.name)
      )
      .first();
  },
});

// ============================================================================
// NOTIFICATION PREFERENCES
// ============================================================================

/**
 * Set a user's preference for a specific notification type.
 */
export const setNotificationPreference = mutation({
  args: {
    user: v.id("users"),
    module: v.id("modules"),
    notification_type: v.id("notificationTypes"),
    enabled: v.boolean(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_module_type", (q) =>
        q
          .eq("user", args.user)
          .eq("module", args.module)
          .eq("notification_type", args.notification_type)
      )
      .first();

    if (existing) {
      await ctx.db.patch(existing._id, { enabled: args.enabled });
      return existing._id;
    }

    return await ctx.db.insert("notificationPreferences", args);
  },
});

/**
 * Set a user's preference for a specific module.
 */
export const setModuleNotificationPreference = mutation({
  args: {
    user: v.id("users"),
    module: v.id("modules"),
    enabled: v.boolean(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_module", (q) =>
        q
          .eq("user", args.user)
          .eq("module", args.module)
      )
      .first();

    if (existing) {
      await ctx.db.patch(existing._id, { enabled: args.enabled });
      return existing._id;
    }

    return await ctx.db.insert("notificationPreferences", args);
  },
});

/**
 * Set a user's global notification preference (opt-in/opt-out of all notifications).
 */
export const setGlobalNotificationPreference = mutation({
  args: {
    user: v.id("users"),
    enabled: v.boolean(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_global", (q) =>
        q.eq("user", args.user)
      )
      .first();

    if (existing) {
      await ctx.db.patch(existing._id, { enabled: args.enabled });
      return existing._id;
    }

    return await ctx.db.insert("notificationPreferences", {
      user: args.user,
      enabled: args.enabled,
    });
  },
});

/**
 * Get all notification preferences for a user.
 */
export const getUserPreferences = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_global", (q) => q.eq("user", args.user))
      .collect();
  },
});

/**
 * Check if notifications are enabled for a user + module + type.
 * Resolution order:
 * 1. User-level preference (global opt-out)
 * 2. Module-level preference
 * 3. Type-level preference
 * 4. Notification type's default_enabled
 */
export const isNotificationEnabled = query({
  args: {
    user: v.id("users"),
    module: v.id("modules"),
    notification_type: v.id("notificationTypes"),
  },
  handler: async (ctx, args) => {
    // 1. Check user-level preference (global opt-out)
    const userPref = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_global", (q) =>
        q.eq("user", args.user)
      )
      .first();

    if (userPref) {
      return userPref.enabled;
    }

    // 2. Check module-level preference
    const modulePref = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_module_type", (q) =>
        q
          .eq("user", args.user)
          .eq("module", args.module)
          .eq("notification_type", undefined)
      )
      .first();

    if (modulePref) {
      return modulePref.enabled;
    }

    // 3. Check type-level preference
    const typePref = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_module_type", (q) =>
        q
          .eq("user", args.user)
          .eq("module", args.module)
          .eq("notification_type", args.notification_type)
      )
      .first();

    if (typePref) {
      return typePref.enabled;
    }

    // 4. Fall back to notification type's default
    const notificationType = await ctx.db.get(args.notification_type);
    return notificationType?.default_enabled ?? true;
  },
});

/**
 * Delete a notification preference (revert to default).
 */
export const deleteNotificationPreference = mutation({
  args: {
    user: v.id("users"),
    module: v.optional(v.id("modules")),
    notification_type: v.optional(v.id("notificationTypes")),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("notificationPreferences")
      .withIndex("by_user_module_type", (q) =>
        q
          .eq("user", args.user)
          .eq("module", args.module)
          .eq("notification_type", args.notification_type)
      )
      .first();

    if (existing) {
      await ctx.db.delete(existing._id);
      return true;
    }
    return false;
  },
});

// ============================================================================
// NOTIFICATION QUEUE
// ============================================================================

/**
 * Add a notification to the queue for later delivery.
 */
export const enqueueNotification = mutation({
  args: {
    user: v.id("users"),
    module: v.id("modules"),
    notification_type: v.id("notificationTypes"),
    content: v.string(),
    scheduled_for: v.number(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("notificationQueue", {
      ...args,
      status: "pending",
      attempts: 0,
    });
  },
});

/**
 * Get pending notifications that are due for delivery.
 */
export const getPendingNotifications = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const now = Date.now();
    const limit = args.limit ?? 50;

    return await ctx.db
      .query("notificationQueue")
      .withIndex("by_status_scheduled", (q) =>
        q.eq("status", "pending").lte("scheduled_for", now)
      )
      .take(limit);
  },
});

/**
 * Update notification queue item status.
 */
export const updateNotificationStatus = mutation({
  args: {
    id: v.id("notificationQueue"),
    status: NotificationQueueStatus,
    last_error: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const item = await ctx.db.get(args.id);
    if (!item) return null;

    const updates: Record<string, unknown> = { status: args.status };

    if (args.status === "sending" || args.status === "failed") {
      updates.attempts = (item.attempts ?? 0) + 1;
    }

    if (args.last_error !== undefined) {
      updates.last_error = args.last_error;
    }

    await ctx.db.patch(args.id, updates);
    return args.id;
  },
});

/**
 * Cancel a queued notification.
 */
export const cancelQueuedNotification = mutation({
  args: { id: v.id("notificationQueue") },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.id, { status: "cancelled" });
    return true;
  },
});

/**
 * Get queued notifications for a user.
 */
export const getUserQueuedNotifications = query({
  args: { user: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("notificationQueue")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .collect();
  },
});
