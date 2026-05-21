import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { MessageStatus, Channel } from "./tables/messaging";

/**
 * Search all messages for a keyword (admin utility).
 *
 * Uses the full-text search index on the messages table.
 * Returns matching messages enriched with the owning user's name
 * and the chat owner (user ID) so the caller can identify who
 * sent each message.
 *
 * Results are limited to `limit` matches (default 50, max 200)
 * and filtered to `role` "user" only (assistant messages are
 * excluded by default). Pass `role: "any"` to include all roles.
 */
export const searchMessages = query({
  args: {
    keyword: v.string(),
    limit: v.optional(v.number()),
    role: v.optional(v.string()), // "user" (default), "assistant", or "any"
  },
  handler: async (ctx, args) => {
    const limit = Math.min(args.limit ?? 50, 200);
    const filterRole = args.role ?? "user";

    // Over-fetch to account for role filtering, but cap to avoid
    // blowing through Convex read limits on common keywords.
    const fetchLimit = filterRole === "any" ? limit : limit * 3;
    const raw = await ctx.db
      .query("messages")
      .withSearchIndex("search_content", (q) => q.search("content", args.keyword))
      .take(fetchLimit);

    // Apply role filter
    const filtered =
      filterRole === "any"
        ? raw
        : raw.filter((m) => m.role === filterRole);

    // Enrich with user info and take up to `limit`
    const enriched: Array<Record<string, unknown>> = [];
    for (const msg of filtered) {
      if (enriched.length >= limit) break;

      // Look up the chat to find the owner (user)
      const chat = await ctx.db.get(msg.chat);
      let owner: string | null = null;
      let userName: string | null = null;
      if (chat) {
        owner = chat.owner as unknown as string;
        const user = await ctx.db.get(chat.owner);
        if (user) {
          const first = (user as Record<string, unknown>).first_name as string | undefined;
          const last = (user as Record<string, unknown>).last_name as string | undefined;
          userName = [first, last].filter(Boolean).join(" ") || null;
        }
      }

      enriched.push({
        _id: msg._id,
        _creationTime: msg._creationTime,
        role: msg.role,
        channel: msg.channel,
        content: msg.content,
        status: msg.status,
        chatId: msg.chat,
        owner,
        userName,
      });
    }

    return enriched;
  },
});

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
    specialist_module: v.optional(v.string()),
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
      specialist_module: args.specialist_module,
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
