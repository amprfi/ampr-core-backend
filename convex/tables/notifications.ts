import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validator for notification queue status
 */
export const NotificationQueueStatus = v.union(
  v.literal("pending"),
  v.literal("sending"),
  v.literal("sent"),
  v.literal("failed"),
  v.literal("cancelled")
);

/**
 * Notification types registry - modules register their notification types here at runtime
 * 
 * Each module can define multiple notification types with their own default behavior.
 * - default_enabled: true = opt-out (user must disable), false = opt-in (user must enable)
 * 
 * Modules register types and receive the Convex _id, which they use when sending notifications.
 */
export const notificationTypes = defineTable({
  module: v.id("modules"),
  name: v.string(),
  description: v.string(),
  default_enabled: v.boolean(),
})
  .index("by_module", ["module"])
  .index("by_module_name", ["module", "name"]);

/**
 * User notification preferences - hierarchical opt-in/opt-out
 * 
 * Preference hierarchy:
 * 1. Module-level: notification_type is null → applies to all types from this module
 * 2. Type-level: notification_type is set → applies to specific type within module
 * 
 * Resolution order:
 * - Check type-level preference first
 * - Fall back to module-level preference
 * - Fall back to notification type's default_enabled
 */
export const notificationPreferences = defineTable({
  user: v.id("users"),
  module: v.optional(v.id("modules")),
  notification_type: v.optional(v.id("notificationTypes")),
  enabled: v.boolean(),
})
  .index("by_user_global", ["user"])
  .index("by_user_module", ["user", "module"])
  .index("by_user_module_type", ["user", "module", "notification_type"]);

/**
 * Notification queue - stores notifications scheduled for later delivery
 * 
 * Used when a notification is triggered outside the user's delivery window.
 * A scheduled job processes pending notifications and delivers them when appropriate.
 */
export const notificationQueue = defineTable({
  user: v.id("users"),
  module: v.id("modules"),
  notification_type: v.id("notificationTypes"),
  content: v.string(),
  scheduled_for: v.number(),
  status: NotificationQueueStatus,
  attempts: v.optional(v.number()),
  last_error: v.optional(v.string()),
})
  .index("by_status_scheduled", ["status", "scheduled_for"])
  .index("by_user", ["user"])
  .index("by_user_module", ["user", "module"]);
