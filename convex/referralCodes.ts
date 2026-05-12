import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import type { MutationCtx, QueryCtx } from "./_generated/server";

// Character set for random part of referral code (excluding easily confused characters)
const CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

/**
 * Generates a referral code using initials when available
 * Format: AA-BBBB (first two from initials, hyphen, four random)
 */
function generateRandomCode(firstName?: string, lastName?: string): string {
  // First two characters: initials if available, otherwise random
  let firstPart = "";
  const firstInitial = firstName?.trim()?.[0]?.toUpperCase();
  const lastInitial = lastName?.trim()?.[0]?.toUpperCase();

  firstPart += firstInitial || CHARACTERS.charAt(Math.floor(Math.random() * CHARACTERS.length));
  firstPart += lastInitial || CHARACTERS.charAt(Math.floor(Math.random() * CHARACTERS.length));

  // Generate last four characters
  let secondPart = "";
  for (let i = 0; i < 4; i++) {
    secondPart += CHARACTERS.charAt(
      Math.floor(Math.random() * CHARACTERS.length),
    );
  }

  // Combine into AA-BBBB format
  return `${firstPart}-${secondPart}`;
}

/**
 * Checks if a referral code is unique (case-insensitive)
 */
async function isReferralCodeUnique(
  ctx: QueryCtx,
  code: string,
): Promise<boolean> {
  const normalizedCode = code.toUpperCase();
  const existingProfile = await ctx.db
    .query("profiles")
    .withIndex("by_referral_code", (q) => q.eq("referral_code", normalizedCode))
    .unique();
  return !existingProfile;
}

/**
 * Generates a unique referral code
 */
export async function generateUniqueReferralCode(
  ctx: MutationCtx,
  firstName?: string,
  lastName?: string,
): Promise<string> {
  let attempts = 0;
  const maxAttempts = 10;

  while (attempts < maxAttempts) {
    const code = generateRandomCode(firstName, lastName);
    const normalizedCode = code.toUpperCase();
    if (await isReferralCodeUnique(ctx, normalizedCode)) {
      return normalizedCode;
    }
    attempts++;
  }

  throw new Error(
    `Failed to generate unique referral code after ${maxAttempts} attempts`,
  );
}

/**
 * Look up a profile by referral code (case-insensitive)
 */
export const lookupByReferralCode = query({
  args: {
    referralCode: v.string(),
  },
  handler: async (ctx, args) => {
    const normalizedCode = args.referralCode.toUpperCase();
    return await ctx.db
      .query("profiles")
      .withIndex("by_referral_code", (q) =>
        q.eq("referral_code", normalizedCode),
      )
      .unique();
  },
});

/**
 * Increment referrals count and update contribution score
 */
export const incrementReferrals = mutation({
  args: {
    userId: v.id("users"),
  },
  handler: async (ctx, args) => {
    const profile = await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", args.userId))
      .unique();

    if (!profile) {
      throw new Error("User profile not found");
    }

    const referrals = (profile.referrals || 0) + 1;
    const officeHours = profile.office_hours || 0;
    const productImprovements = profile.product_improvements || 0;
    const contributionScore =
      4.0 * referrals + 0.5 * officeHours + 2.0 * productImprovements;

    await ctx.db.patch(profile._id, {
      referrals,
      contribution_score: contributionScore,
    });

    return { referrals, contribution_score: contributionScore };
  },
});
