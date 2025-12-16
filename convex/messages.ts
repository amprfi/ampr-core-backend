import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { MessageStatus, Channel } from "./tables/messaging";

/**
 * Create a message and auto-create chat if needed
 * 
 * This mutation:
 * 1. Checks if user has an existing chat
 * 2. Creates a new chat if one doesn't exist
 * 3. Creates the message in the chat
 * 
 * Returns the created message with auto-generated _id and _creationTime
 */
export const createMessage = mutation({
  args: {
    userId: v.id("users"),
    role: v.string(),
    channel: Channel,
    content: v.string(),
    preprocessed_content: v.optional(v.string()),
    is_notification: v.optional(v.boolean()),
    notification_module: v.optional(v.id("modules")),
    notification_type: v.optional(v.id("notificationTypes")),
  },
  handler: async (ctx, args) => {
    let chat = await ctx.db
      .query("chats")
      .withIndex("by_owner", (q) => q.eq("owner", args.userId))
      .first();

    if (!chat) {
      const chatId = await ctx.db.insert("chats", {
        owner: args.userId,
      });
      chat = await ctx.db.get(chatId);
      if (!chat) {
        throw new Error("Failed to create chat");
      }
    }

    const messageId = await ctx.db.insert("messages", {
      chat: chat._id,
      role: args.role,
      channel: args.channel,
      content: args.content,
      preprocessed_content: args.preprocessed_content,
      status: "Current",
      is_notification: args.is_notification,
      notification_module: args.notification_module,
      notification_type: args.notification_type,
    });

    return await ctx.db.get(messageId);
  },
});

/**
 * Get messages that need to be summarized
 * 
 * Returns up to 20 messages with status "PendingSummary" for the given chat,
 * ordered by creation time (oldest first).
 * Excludes notification messages from summarization.
 */
export const getMessagesToSummarize = query({
  args: { chatId: v.id("chats") },
  handler: async (ctx, args) => {
    const messages = await ctx.db
      .query("messages")
      .withIndex("by_chat_status", (q) => 
        q.eq("chat", args.chatId).eq("status", "PendingSummary")
      )
      .filter((q) => q.neq(q.field("is_notification"), true))
      .take(20);

    return messages.map(m => ({
      _id: m._id,
      _creationTime: m._creationTime,
      role: m.role,
      content: m.content,
    }));
  },
});

/**
 * Update message status for archiving
 * 
 * This mutation:
 * 1. Finds the 20th most recent "Current" message to establish a cutoff
 * 2. Updates all "Current" messages older than the cutoff to "PendingSummary"
 * 3. Returns the count of messages now in "PendingSummary" status
 * 
 * Note: Uses offset 19 because we want messages at position 20+ (0-indexed)
 * Notification messages are excluded from the count and status updates.
 */
export const updateMessageStatus = mutation({
  args: { chatId: v.id("chats") },
  handler: async (ctx, args) => {
    const allCurrentMessages = await ctx.db
      .query("messages")
      .withIndex("by_chat_status", (q) => 
        q.eq("chat", args.chatId).eq("status", "Current")
      )
      .collect();

    // Filter out notifications for memory management
    const currentMessages = allCurrentMessages.filter(m => m.is_notification !== true);
    currentMessages.sort((a, b) => b._creationTime - a._creationTime);

    if (currentMessages.length <= 19) {
      const pendingMessages = await ctx.db
        .query("messages")
        .withIndex("by_chat_status", (q) => 
          q.eq("chat", args.chatId).eq("status", "PendingSummary")
        )
        .filter((q) => q.neq(q.field("is_notification"), true))
        .collect();
      return pendingMessages.length;
    }

    const cutoffMessage = currentMessages[19];
    if (!cutoffMessage) {
      throw new Error("Failed to find cutoff message");
    }
    const cutoffTime = cutoffMessage._creationTime;

    const messagesToUpdate = currentMessages.filter(
      m => m._creationTime < cutoffTime
    );

    for (const message of messagesToUpdate) {
      await ctx.db.patch(message._id, { status: "PendingSummary" });
    }

    const pendingMessages = await ctx.db
      .query("messages")
      .withIndex("by_chat_status", (q) => 
        q.eq("chat", args.chatId).eq("status", "PendingSummary")
      )
      .filter((q) => q.neq(q.field("is_notification"), true))
      .collect();

    return pendingMessages.length;
  },
});

/**
 * Create summary and archive messages
 * 
 * This mutation:
 * 1. Creates a summary for the specified messages
 * 2. Updates all specified messages to "Archived" status
 * 
 * Returns the created summary and list of archived message IDs
 */
export const createSummaryAndArchive = mutation({
  args: {
    chatId: v.id("chats"),
    content: v.string(),
    range_start: v.number(),
    range_end: v.number(),
    messageIds: v.array(v.id("messages")),
  },
  handler: async (ctx, args) => {
    const summaryId = await ctx.db.insert("summaries", {
      chat: args.chatId,
      content: args.content,
      range_start: args.range_start,
      range_end: args.range_end,
    });

    const archivedIds = [];
    for (const messageId of args.messageIds) {
      await ctx.db.patch(messageId, { status: "Archived" });
      archivedIds.push(messageId);
    }

    const summary = await ctx.db.get(summaryId);

    return {
      summary,
      archived_messages: archivedIds.map(id => ({ _id: id })),
    };
  },
});
