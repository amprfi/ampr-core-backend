import { defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Enum validator for document source type
 */
export const SourceType = v.union(
  v.literal("blog"),
  v.literal("newsletter"),
  v.literal("report"),
  v.literal("podcast")
);

/**
 * Lenses table - author metadata for RAG-powered financial content agents
 */
export const lenses = defineTable({
  name: v.string(),
  authorName: v.string(),
  description: v.string(),
  systemPrompt: v.string(),
  url: v.optional(v.string()),
  createdBy: v.id("users"),
})
  .index("by_name", ["name"])
  .index("by_createdBy", ["createdBy"]);

/**
 * Lens documents table - source document metadata
 * Each document belongs to a lens and contains the original markdown text,
 * a summary (for full-text search), and chunk tracking.
 */
export const lensDocuments = defineTable({
  lens: v.id("lenses"),
  title: v.string(),
  sourceType: SourceType,
  originalText: v.string(),
  summary: v.string(),
  chunkCount: v.number(),
  publishedAt: v.optional(v.number()),
  storageId: v.optional(v.id("_storage")),
  tags: v.optional(v.array(v.string())),
})
  .index("by_lens", ["lens"]);

/**
 * Lens chunks table - embedded content chunks for vector search
 * Each chunk belongs to a document and lens, with a 1024-dim embedding
 * from mistral-embed for cosine similarity search.
 */
export const lensChunks = defineTable({
  lens: v.id("lenses"),
  document: v.id("lensDocuments"),
  content: v.string(),
  chunkIndex: v.number(),
  embedding: v.array(v.float64()),
})
  .index("by_document", ["document"])
  .index("by_lens", ["lens"])
  .vectorIndex("by_embedding", {
    vectorField: "embedding",
    dimensions: 1024,
    filterFields: ["lens"],
  });
