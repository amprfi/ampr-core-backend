import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import {
  InvestmentHorizon,
  AgeGroup,
  InvestmentKnowledge,
  RiskAppetite,
} from "./tables/profiles";

/**
 * Get profile by user ID
 */
export const getProfileByUser = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", args.userId))
      .unique();
  },
});

/**
 * Get user investment preferences
 */
export const getInvestmentPreferences = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    const profile = await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", args.userId))
      .unique();

    if (!profile) {
      return null;
    }

    return {
      stated_investment_horizon: profile.stated_investment_horizon,
      inferred_investment_horizon: profile.inferred_investment_horizon,
      stated_risk_appetite: profile.stated_risk_appetite,
      inferred_risk_appetite: profile.inferred_risk_appetite,
      stated_investment_knowledge: profile.stated_investment_knowledge,
      inferred_investment_knowledge: profile.inferred_investment_knowledge,
      stated_financial_goals: profile.stated_financial_goals,
      inferred_financial_goals: profile.inferred_financial_goals,
      other_investments: profile.other_investments,
      inferred_investment_thesis: profile.inferred_investment_thesis,
    };
  },
});

/**
 * Get user country (resolves the country reference to full country data)
 */
export const getUserCountry = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    const profile = await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", args.userId))
      .unique();

    if (!profile) {
      return null;
    }

    const country = profile.country ? await ctx.db.get(profile.country) : null;
    return { country };
  },
});

/**
 * Get user's preferred currency code (lightweight query for currency conversion)
 */
export const getUserCurrency = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    const profile = await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", args.userId))
      .unique();

    return { preferred_currency: profile?.preferred_currency ?? null };
  },
});

/**
 * Create or update a user profile (upsert).
 *
 * Profiles are now auto-created with growth-metric defaults inside
 * `users.createUser`, so this mutation patches the existing profile rather
 * than throwing. Any provided field overwrites the existing value.
 */
export const createProfile = mutation({
  args: {
    user: v.id("users"),
    country: v.optional(v.id("countries")),
    kyc_passed: v.boolean(),
    age_group: v.optional(AgeGroup),
    stated_investment_horizon: v.optional(InvestmentHorizon),
    stated_risk_appetite: v.optional(RiskAppetite),
    stated_investment_knowledge: v.optional(InvestmentKnowledge),
    stated_financial_goals: v.optional(v.array(v.string())),
    other_investments: v.optional(v.array(v.string())),
    inferred_investment_horizon: v.optional(InvestmentHorizon),
    inferred_risk_appetite: v.optional(RiskAppetite),
    inferred_investment_knowledge: v.optional(InvestmentKnowledge),
    inferred_financial_goals: v.optional(v.array(v.string())),
    inferred_investment_thesis: v.optional(v.string()),
    preferred_currency: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { user, ...rest } = args;

    const existingProfile = await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", user))
      .first();

    if (existingProfile !== null) {
      await ctx.db.patch(existingProfile._id, rest);
      return await ctx.db.get(existingProfile._id);
    }

    const profileId = await ctx.db.insert("profiles", {
      user,
      ...rest,
    });

    return await ctx.db.get(profileId);
  },
});

/**
 * Update an existing user profile
 *
 * Only updates fields that are provided (partial update)
 */
export const updateProfile = mutation({
  args: {
    user: v.id("users"),
    country: v.optional(v.id("countries")),
    kyc_passed: v.optional(v.boolean()),
    age_group: v.optional(AgeGroup),
    stated_investment_horizon: v.optional(InvestmentHorizon),
    stated_risk_appetite: v.optional(RiskAppetite),
    stated_investment_knowledge: v.optional(InvestmentKnowledge),
    stated_financial_goals: v.optional(v.array(v.string())),
    other_investments: v.optional(v.array(v.string())),
    inferred_investment_horizon: v.optional(InvestmentHorizon),
    inferred_risk_appetite: v.optional(RiskAppetite),
    inferred_investment_knowledge: v.optional(InvestmentKnowledge),
    inferred_financial_goals: v.optional(v.array(v.string())),
    inferred_investment_thesis: v.optional(v.string()),
    preferred_currency: v.optional(v.string()),
    office_hours: v.optional(v.number()),
    product_improvements: v.optional(v.number()),
    referrals: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    let profile = await ctx.db
      .query("profiles")
      .withIndex("by_user", (q) => q.eq("user", args.user))
      .unique();

    if (!profile) {
      const profileId = await ctx.db.insert("profiles", {
        user: args.user,
        kyc_passed: false,
      });
      profile = await ctx.db.get(profileId);
      if (!profile) {
        throw new Error(`Failed to create profile for user "${args.user}"`);
      }
    }

    const updates: any = {};

    if (args.country !== undefined) updates.country = args.country;
    if (args.kyc_passed !== undefined) updates.kyc_passed = args.kyc_passed;
    if (args.age_group !== undefined) updates.age_group = args.age_group;
    if (args.stated_investment_horizon !== undefined)
      updates.stated_investment_horizon = args.stated_investment_horizon;
    if (args.stated_risk_appetite !== undefined)
      updates.stated_risk_appetite = args.stated_risk_appetite;
    if (args.stated_investment_knowledge !== undefined)
      updates.stated_investment_knowledge = args.stated_investment_knowledge;
    if (args.stated_financial_goals !== undefined) {
      const existingGoals = profile.stated_financial_goals || [];
      const newGoals = args.stated_financial_goals || [];
      updates.stated_financial_goals = Array.from(
        new Set([...existingGoals, ...newGoals]),
      );
    }
    if (args.other_investments !== undefined) {
      const existingInvestments = profile.other_investments || [];
      const newInvestments = args.other_investments || [];
      updates.other_investments = Array.from(
        new Set([...existingInvestments, ...newInvestments]),
      );
    }
    if (args.inferred_investment_horizon !== undefined)
      updates.inferred_investment_horizon = args.inferred_investment_horizon;
    if (args.inferred_risk_appetite !== undefined)
      updates.inferred_risk_appetite = args.inferred_risk_appetite;
    if (args.inferred_investment_knowledge !== undefined)
      updates.inferred_investment_knowledge =
        args.inferred_investment_knowledge;
    if (args.inferred_financial_goals !== undefined) {
      // Merge with existing goals and deduplicate
      const existingGoals = profile.inferred_financial_goals || [];
      const newGoals = args.inferred_financial_goals || [];
      updates.inferred_financial_goals = Array.from(
        new Set([...existingGoals, ...newGoals]),
      );
    }
    if (args.inferred_investment_thesis !== undefined)
      updates.inferred_investment_thesis = args.inferred_investment_thesis;
    if (args.preferred_currency !== undefined)
      updates.preferred_currency = args.preferred_currency;

    if (
      args.office_hours !== undefined ||
      args.product_improvements !== undefined
    ) {
      // Recompute contribution_score whenever an input field changes here.
      // Note: `referrals` is owned by referralCodes.incrementReferrals, which
      // recomputes the score itself. Any other writer of `referrals` must
      // recompute the score too or it will go stale.
      const referrals = profile.referrals || 0;
      const officeHours =
        args.office_hours !== undefined
          ? args.office_hours
          : profile.office_hours || 0;
      const productImprovements =
        args.product_improvements !== undefined
          ? args.product_improvements
          : profile.product_improvements || 0;
      updates.contribution_score =
        4.0 * referrals + 0.5 * officeHours + 2.0 * productImprovements;
    }

    await ctx.db.patch(profile._id, updates);

    return await ctx.db.get(profile._id);
  },
});
