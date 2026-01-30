import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validator for message status
 */
export const MessageStatus = v.union(
  v.literal("Current"),
  v.literal("PendingSummary"),
  v.literal("Archived")
);

/**
 * Enum validator for channel
 */
export const Channel = v.union(
  v.literal("sms"),
  v.literal("rcs"),
  v.literal("whatsapp"),
  v.literal("telegram"),
  v.literal("email"),
  v.literal("app"),
  v.literal("rest")
);

/**
 * Chats table - conversation containers owned by users
 */
export const chats = defineTable({
  owner: v.id("users"),
})
  .index("by_owner", ["owner"]);

/**
 * Messages table - individual messages in chats
 * Key pattern: Compound index on (chat, _creationTime) for efficient queries
 * 
 * Note: _creationTime is automatically added to the end of every index
 */
export const messages = defineTable({
  role: v.string(), // "user" or "assistant"
  channel: Channel,
  content: v.string(), // Original message content (shown to user)
  preprocessed_content: v.optional(v.string()), // Preprocessed content (used by agents) - only for user messages
  chat: v.id("chats"),
  status: MessageStatus,
  // Notification metadata - set when message is a notification
  is_notification: v.optional(v.boolean()),
  notification_module: v.optional(v.id("modules")),
  notification_type: v.optional(v.id("notificationTypes")),
  // Module attribution - set when assistant response is powered by a specialist module
  specialist_module: v.optional(v.string()), // Module name (e.g., "defianalyst", "oracle")
})
  .index("by_chat", ["chat"]) // Primary query pattern - _creationTime auto-added
  .index("by_chat_status", ["chat", "status"]); // For combined queries - _creationTime auto-added

/**
 * Summaries table - message summaries for chats
 */
export const summaries = defineTable({
  content: v.string(),
  range_start: v.number(), // Unix timestamp
  range_end: v.number(), // Unix timestamp
  chat: v.id("chats"),
})
  .index("by_chat", ["chat"]); // _creationTime is auto-added for chronological ordering
