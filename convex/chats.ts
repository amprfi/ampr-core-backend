import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/**
 * Get a chat by (owner, channel, period).
 *
 * Returns the matching chat or null if none exists.
 */
export const getChatByOwnerChannelPeriod = query({
  args: {
    owner: v.id("users"),
    channel: v.string(),
    period: v.string(), // "2025-06" YYYY-MM format
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("chats")
      .withIndex("by_owner_channel_period", (q) =>
        q.eq("owner", args.owner).eq("channel", args.channel).eq("period", args.period)
      )
      .first();
  },
});

/**
 * Get chat with all messages and summaries
 *
 * Returns complete chat data including:
 * - Recent messages (ordered by creation time)
 * - Summaries (ordered by range_start)
 */
export const getChat = query({
  args: {
    userId: v.id("users"),
    chatId: v.id("chats"),
  },
  handler: async (ctx, args) => {
    const chat = await ctx.db.get(args.chatId);

    if (!chat) {
      throw new Error(`Chat with ID "${args.chatId}" not found`);
    }

    if (chat.owner !== args.userId) {
      throw new Error(`Chat "${args.chatId}" is not owned by user "${args.userId}"`);
    }

    const messages = await ctx.db
      .query("messages")
      .withIndex("by_chat", (q) => q.eq("chat", args.chatId))
      .collect();

    const summaries = await ctx.db
      .query("summaries")
      .withIndex("by_chat", (q) => q.eq("chat", args.chatId))
      .collect();

    return {
      _id: chat._id,
      _creationTime: chat._creationTime,
      owner: chat.owner,
      recent_messages: messages.map((m) => ({
        _id: m._id,
        _creationTime: m._creationTime,
        role: m.role,
        channel: m.channel,
        content: m.content,
        preprocessed_content: m.preprocessed_content,
        status: m.status,
      })),
      summaries: summaries.map((s) => ({
        _id: s._id,
        _creationTime: s._creationTime,
        content: s.content,
        range_start: s.range_start,
        range_end: s.range_end,
      })),
    };
  },
});
