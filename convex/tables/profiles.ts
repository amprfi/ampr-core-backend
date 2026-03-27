import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validators for user profile fields
 */
export const InvestmentHorizon = v.union(
  v.literal("1-5"),
  v.literal("6-10"),
  v.literal("10-20"),
  v.literal("20 plus")
);

export const AgeGroup = v.union(
  v.literal("under 25"),
  v.literal("25-34"),
  v.literal("35-44"),
  v.literal("45-54"),
  v.literal("55 plus")
);

export const InvestmentKnowledge = v.union(
  v.literal("novice"),
  v.literal("intermediate"),
  v.literal("advanced")
);

export const RiskAppetite = v.number();

/**
 * User profiles table - investment preferences and KYC data
 * One-to-one relationship with users table
 */
export const profiles = defineTable({
  user: v.id("users"),
  country: v.optional(v.id("countries")),
  kyc_passed: v.boolean(),
  age_group: v.optional(AgeGroup),
  
  // Stated properties
  stated_investment_horizon: v.optional(InvestmentHorizon),
  stated_risk_appetite: v.optional(RiskAppetite),
  stated_investment_knowledge: v.optional(InvestmentKnowledge),
  stated_financial_goals: v.optional(v.array(v.string())),
  other_investments: v.optional(v.array(v.string())),
  
  // Inferred properties
  inferred_investment_horizon: v.optional(InvestmentHorizon),
  inferred_risk_appetite: v.optional(RiskAppetite),
  inferred_investment_knowledge: v.optional(InvestmentKnowledge),
  inferred_financial_goals: v.optional(v.array(v.string())),
  inferred_investment_thesis: v.optional(v.string()),
  
  // User's preferred currency for display (ISO 4217 code, e.g., "USD", "CAD")
  preferred_currency: v.optional(v.string()),
  
  // Timezone for notification delivery windows (e.g., "America/New_York")
  timezone: v.optional(v.string()),
})
  .index("by_user", ["user"]); // For one-to-one lookup
