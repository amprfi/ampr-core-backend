import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/**
 * Country record shape for bulk operations
 */
const countryRecord = v.object({
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
});

/**
 * Get all countries
 */
export const getCountries = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("countries").collect();
  },
});

/**
 * Get country by ISO 3166-1 alpha-3 code
 */
export const getCountryByCode = query({
  args: { country_code: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("countries")
      .withIndex("by_country_code", (q) => q.eq("country_code", args.country_code.toUpperCase()))
      .unique();
  },
});

/**
 * Get country by Convex document ID
 */
export const getCountryById = query({
  args: { id: v.id("countries") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Create a new country
 */
export const createCountry = mutation({
  args: countryRecord,
  handler: async (ctx, args) => {
    const upperCode = args.country_code.toUpperCase();

    const existing = await ctx.db
      .query("countries")
      .withIndex("by_country_code", (q) => q.eq("country_code", upperCode))
      .first();

    if (existing) {
      throw new Error(`Country with code "${upperCode}" already exists`);
    }

    const countryId = await ctx.db.insert("countries", {
      ...args,
      country_code: upperCode,
    });

    return await ctx.db.get(countryId);
  },
});

/**
 * Update an existing country
 */
export const updateCountry = mutation({
  args: {
    country_code: v.string(),
    country_name: v.optional(v.string()),
    currency: v.optional(v.string()),
    utc_offset: v.optional(v.number()),
    calling_code: v.optional(v.string()),
    ofac_country_program: v.optional(v.boolean()),
    eu_asset_freeze: v.optional(v.boolean()),
    eu_financial_prohibition: v.optional(v.boolean()),
    eu_tax_haven_blacklist: v.optional(v.boolean()),
    ampersand_blocklist_full: v.optional(v.boolean()),
    ampersand_blocklist_funding: v.optional(v.boolean()),
    ampersand_additional_screening_required: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    const upperCode = args.country_code.toUpperCase();

    const existing = await ctx.db
      .query("countries")
      .withIndex("by_country_code", (q) => q.eq("country_code", upperCode))
      .first();

    if (!existing) {
      throw new Error(`Country with code "${upperCode}" not found`);
    }

    const { country_code, ...updateFields } = args;

    const fieldsToUpdate: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(updateFields)) {
      if (value !== undefined) {
        fieldsToUpdate[key] = value;
      }
    }

    if (Object.keys(fieldsToUpdate).length === 0) {
      throw new Error("No fields to update");
    }

    await ctx.db.patch(existing._id, fieldsToUpdate);
    return await ctx.db.get(existing._id);
  },
});

/**
 * Bulk upsert countries - insert new records or update existing ones
 * Uses country_code as the unique key for matching
 */
export const bulkUpsertCountries = mutation({
  args: {
    countries: v.array(countryRecord),
  },
  handler: async (ctx, args) => {
    const results: { inserted: number; updated: number; errors: string[] } = {
      inserted: 0,
      updated: 0,
      errors: [],
    };

    for (const country of args.countries) {
      const upperCode = country.country_code.toUpperCase();

      try {
        const existing = await ctx.db
          .query("countries")
          .withIndex("by_country_code", (q) => q.eq("country_code", upperCode))
          .first();

        if (existing) {
          await ctx.db.patch(existing._id, {
            ...country,
            country_code: upperCode,
          });
          results.updated++;
        } else {
          await ctx.db.insert("countries", {
            ...country,
            country_code: upperCode,
          });
          results.inserted++;
        }
      } catch (error) {
        results.errors.push(`${upperCode}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    return results;
  },
});

/**
 * Delete a country by code
 */
export const deleteCountry = mutation({
  args: { country_code: v.string() },
  handler: async (ctx, args) => {
    const upperCode = args.country_code.toUpperCase();

    const existing = await ctx.db
      .query("countries")
      .withIndex("by_country_code", (q) => q.eq("country_code", upperCode))
      .first();

    if (!existing) {
      throw new Error(`Country with code "${upperCode}" not found`);
    }

    await ctx.db.delete(existing._id);
    return { deleted: true, country_code: upperCode };
  },
});
