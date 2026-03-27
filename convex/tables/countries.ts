import { defineTable } from "convex/server";
import { v } from "convex/values";

export const countries = defineTable({
  country_code: v.string(),
  country_name: v.string(),
  currency: v.optional(v.string()),
  utc_offset: v.number(),
  calling_code: v.string(),
  ofac_country_program: v.boolean(),
  eu_asset_freeze: v.boolean(),
  eu_financial_prohibition: v.boolean(),
  eu_tax_haven_blacklist: v.boolean(),
  ampersand_blocklist_full: v.boolean(),
  ampersand_blocklist_funding: v.boolean(),
  ampersand_additional_screening_required: v.boolean(),
}).index("by_country_code", ["country_code"]);
