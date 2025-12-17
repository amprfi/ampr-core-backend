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
 * Get user by ID
 */
export const getUser = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.userId);
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
 * 
 * At least one of phone or telegram_id must be provided
 */
export const createUser = mutation({
  args: {
    first_name: v.optional(v.string()),
    last_name: v.optional(v.string()),
    email: v.optional(v.string()),
    phone: v.optional(v.string()),
    telegram_id: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    // Validate at least one identifier
    if (!args.phone && !args.telegram_id) {
      throw new Error("At least one of phone or telegram_id must be provided");
    }

    // Check for duplicate email if provided
    if (args.email) {
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
    }

    // Check for duplicate phone if provided
    if (args.phone) {
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
    }

    // Check for duplicate telegram_id if provided
    if (args.telegram_id) {
      const existingTelegram = await ctx.db
        .query("users")
        .withIndex("by_telegram_id", (q) => q.eq("telegram_id", args.telegram_id))
        .first();
      if (existingTelegram !== null) {
        throw new Error(
          `In table "users" cannot create a duplicate document with field "telegram_id" of value \`${args.telegram_id}\`, existing document with ID "${
            existingTelegram._id as string
          }" already has it.`,
        );
      }
    }

    const userId = await ctx.db.insert("users", {
      first_name: args.first_name,
      last_name: args.last_name,
      email: args.email,
      phone: args.phone,
      telegram_id: args.telegram_id,
      onboarding_complete: false,
    });
    
    return await ctx.db.get(userId);
  },
});

/**
 * Update user information
 */
export const updateUser = mutation({
  args: {
    id: v.id("users"),
    first_name: v.optional(v.string()),
    last_name: v.optional(v.string()),
    email: v.optional(v.string()),
    phone: v.optional(v.string()),
    telegram_id: v.optional(v.string()),
    onboarding_complete: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    const { id, ...updateFields } = args;
    
    // Remove undefined fields
    const fieldsToUpdate: Record<string, string | boolean> = {};
    for (const [key, value] of Object.entries(updateFields)) {
      if (value !== undefined) {
        fieldsToUpdate[key] = value;
      }
    }
    
    if (Object.keys(fieldsToUpdate).length === 0) {
      throw new Error("No fields to update");
    }
    
    // Check for duplicate email if updating email
    if (fieldsToUpdate.email && typeof fieldsToUpdate.email === "string") {
      const existingEmail = await ctx.db
        .query("users")
        .withIndex("by_email", (q) => q.eq("email", fieldsToUpdate.email as string))
        .first();
      if (existingEmail && existingEmail._id !== id) {
        throw new Error(
          `Cannot update: email "${fieldsToUpdate.email}" is already registered`
        );
      }
    }
    
    // Check for duplicate phone if updating phone
    if (fieldsToUpdate.phone && typeof fieldsToUpdate.phone === "string") {
      const existingPhone = await ctx.db
        .query("users")
        .withIndex("by_phone", (q) => q.eq("phone", fieldsToUpdate.phone as string))
        .first();
      if (existingPhone && existingPhone._id !== id) {
        throw new Error(
          `Cannot update: phone "${fieldsToUpdate.phone}" is already registered`
        );
      }
    }
    
    // Check for duplicate telegram_id if updating telegram_id
    if (fieldsToUpdate.telegram_id && typeof fieldsToUpdate.telegram_id === "string") {
      const existingTelegram = await ctx.db
        .query("users")
        .withIndex("by_telegram_id", (q) => q.eq("telegram_id", fieldsToUpdate.telegram_id as string))
        .first();
      if (existingTelegram && existingTelegram._id !== id) {
        throw new Error(
          `Cannot update: telegram_id "${fieldsToUpdate.telegram_id}" is already registered`
        );
      }
    }
    
    await ctx.db.patch(id, fieldsToUpdate);
    return await ctx.db.get(id);
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
