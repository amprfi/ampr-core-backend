import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/**
 * Get user by email
 * Replaces: src/queries/users/get_user_by_email.edgeql
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
 * Replaces: src/queries/users/get_user_by_phone.edgeql
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
 * Get all users
 * Replaces: src/queries/users/get_users.edgeql
 */
export const getUsers = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("users").collect();
  },
});

/**
 * Create a new user
 * Replaces: src/queries/users/create_user.edgeql
 * 
 * Returns the created user with auto-generated _id and _creationTime
 */
export const createUser = mutation({
  args: {
    first_name: v.string(),
    last_name: v.string(),
    email: v.string(),
    phone: v.string(),
  },
  handler: async (ctx, args) => {
    const userId = await ctx.db.insert("users", {
      first_name: args.first_name,
      last_name: args.last_name,
      email: args.email,
      phone: args.phone,
    });
    
    return await ctx.db.get(userId);
  },
});
