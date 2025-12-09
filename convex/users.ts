import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/**
 * Get user by email
 */
export const getUserByEmail = query({
  args: { email: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("users")
      .withIndex("by_email", (q) => q.eq("email", args.email))
      .unique();
  },
});

/**
 * Get user by phone
 */
export const getUserByPhone = query({
  args: { phone: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("users")
      .withIndex("by_phone", (q) => q.eq("phone", args.phone))
      .unique();
  },
});

/**
 * Get user by Telegram ID
 */
export const getUserByTelegramId = query({
  args: { telegram_id: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("users")
      .withIndex("by_telegram_id", (q) => q.eq("telegram_id", args.telegram_id))
      .first();
  },
});

/**
 * Get all users
 */
export const getUsers = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("users").collect();
  },
});

/**
 * Create a new user
 * 
 * Returns the created user with auto-generated _id and _creationTime
 * Throws error if email or phone already exists
 */
export const createUser = mutation({
  args: {
    first_name: v.string(),
    last_name: v.string(),
    email: v.string(),
    phone: v.string(),
  },
  handler: async (ctx, args) => {
    // Check for duplicate email
    const existingEmail = await ctx.db
      .query("users")
      .withIndex("by_email", (q) => q.eq("email", args.email))
      .first();
    if (existingEmail !== null) {
      throw new Error(
        `In table "users" cannot create a duplicate document with field "email" of value \`${args.email}\`, existing document with ID "${
          existingEmail._id as string
        }" already has it.`,
      );
    }

    // Check for duplicate phone
    const existingPhone = await ctx.db
      .query("users")
      .withIndex("by_phone", (q) => q.eq("phone", args.phone))
      .first();
    if (existingPhone !== null) {
      throw new Error(
        `In table "users" cannot create a duplicate document with field "phone" of value \`${args.phone}\`, existing document with ID "${
          existingPhone._id as string
        }" already has it.`,
      );
    }

    const userId = await ctx.db.insert("users", {
      first_name: args.first_name,
      last_name: args.last_name,
      email: args.email,
      phone: args.phone,
    });
    
    return await ctx.db.get(userId);
  },
});

/**
 * Link a Telegram ID to an existing user (by phone number)
 */
export const linkTelegramToUser = mutation({
  args: {
    phone: v.string(),
    telegram_id: v.string(),
  },
  handler: async (ctx, args) => {
    // Find user by phone
    const user = await ctx.db
      .query("users")
      .withIndex("by_phone", (q) => q.eq("phone", args.phone))
      .first();
    
    if (!user) {
      throw new Error(`No user found with phone ${args.phone}`);
    }
    
    // Update user with Telegram ID
    await ctx.db.patch(user._id, {
      telegram_id: args.telegram_id,
    });
    
    return user._id;
  },
});
