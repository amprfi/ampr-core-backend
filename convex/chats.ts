import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/**
 * Get chat by user ID
 * 
 * Returns the first chat owned by the user (users should have only one chat)
 */
export const getChatByUser = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("chats")
      .withIndex("by_owner", (q) => q.eq("owner", args.userId))
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
    chatId: v.id("chats") 
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
      recent_messages: messages.map(m => ({
        _id: m._id,
        _creationTime: m._creationTime,
        role: m.role,
        channel: m.channel,
        content: m.content,
        preprocessed_content: m.preprocessed_content,
        status: m.status,
      })),
      summaries: summaries.map(s => ({
        _id: s._id,
        _creationTime: s._creationTime,
        content: s.content,
        range_start: s.range_start,
        range_end: s.range_end,
      })),
    };
  },
});

/**
 * Create a new chat for a user
 * 
 * Returns the created chat with auto-generated _id and _creationTime
 */
export const createChat = mutation({
  args: {
    owner: v.id("users"),
  },
  handler: async (ctx, args) => {
    const chatId = await ctx.db.insert("chats", {
      owner: args.owner,
    });
    
    return await ctx.db.get(chatId);
  },
});
