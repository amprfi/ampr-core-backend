import { v } from "convex/values";
import { query, mutation, internalQuery, action } from "./_generated/server";
import { internal } from "./_generated/api";
import { SourceType } from "./tables/lenses";

// ============================================================================
// QUERIES
// ============================================================================

/**
 * Get a lens by ID.
 */
export const getLens = query({
  args: { id: v.id("lenses") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Get a lens by name.
 */
export const getLensByName = query({
  args: { name: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("lenses")
      .withIndex("by_name", (q) => q.eq("name", args.name))
      .first();
  },
});

/**
 * Get all lenses created by a specific user.
 */
export const getLensesByUser = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("lenses")
      .withIndex("by_createdBy", (q) => q.eq("createdBy", args.userId))
      .collect();
  },
});

/**
 * Get all documents for a lens.
 */
export const getDocumentsByLens = query({
  args: { lensId: v.id("lenses") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("lensDocuments")
      .withIndex("by_lens", (q) => q.eq("lens", args.lensId))
      .collect();
  },
});

/**
 * Get a document by ID.
 */
export const getDocument = query({
  args: { id: v.id("lensDocuments") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Internal query to fetch chunks and their parent documents
 * (called by vector search action).
 *
 * Returns chunks (without embeddings) and all unique parent documents
 * (including originalText) so the action can aggregate scores and
 * select top documents in a single round trip.
 */
export const getChunksWithDocuments = internalQuery({
  args: { ids: v.array(v.id("lensChunks")) },
  handler: async (ctx, args) => {
    const chunks = [];
    const seenDocIds = new Set<string>();
    const documents = [];

    for (const id of args.ids) {
      const chunk = await ctx.db.get(id);
      if (!chunk) continue;

      chunks.push({
        _id: chunk._id,
        content: chunk.content,
        chunkIndex: chunk.chunkIndex,
        document: chunk.document,
        lens: chunk.lens,
      });

      const docId = chunk.document as string;
      if (!seenDocIds.has(docId)) {
        seenDocIds.add(docId);
        const doc = await ctx.db.get(chunk.document);
        if (doc) {
          documents.push({
            _id: doc._id,
            title: doc.title,
            sourceType: doc.sourceType,
            summary: doc.summary,
            originalText: doc.originalText,
            publishedAt: doc.publishedAt,
            tags: doc.tags,
          });
        }
      }
    }

    return { chunks, documents };
  },
});

// ============================================================================
// ACTIONS
// ============================================================================

/**
 * Vector search over content chunks within a lens.
 * Actions are required for vector search in Convex.
 *
 * Returns:
 * - chunks: ranked chunks with scores and parent document metadata
 * - topDocuments: the top 2 documents by aggregate chunk score,
 *   including originalText and summary for full document context
 */
export const vectorSearchChunks = action({
  args: {
    lensId: v.id("lenses"),
    embedding: v.array(v.float64()),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args): Promise<{
    chunks: Array<{
      _id: string;
      content: string;
      chunkIndex: number;
      document: string;
      score: number;
      documentTitle?: string;
      documentTags?: string[];
      documentSourceType?: string;
    }>;
    topDocuments: Array<{
      _id: string;
      title: string;
      sourceType: string;
      summary: string;
      originalText: string;
      tags?: string[];
    }>;
  }> => {
    const limit = args.limit ?? 10;

    const results = await ctx.vectorSearch("lensChunks", "by_embedding", {
      vector: args.embedding,
      limit,
      filter: (q) => q.eq("lens", args.lensId),
    });

    if (results.length === 0) {
      return { chunks: [], topDocuments: [] };
    }

    const chunkIds = results.map((r) => r._id);
    const { chunks, documents } = await ctx.runQuery(
      internal.lenses.getChunksWithDocuments,
      { ids: chunkIds },
    );

    // Build a score map from vector search results
    const scoreMap = new Map(results.map((r) => [r._id, r._score]));

    // Build a document lookup for enriching chunks
    const docMap = new Map(documents.map((d) => [d._id, d]));

    // Attach scores and document metadata to chunks
    const enrichedChunks = chunks.map((chunk) => {
      const doc = docMap.get(chunk.document);
      return {
        _id: chunk._id,
        content: chunk.content,
        chunkIndex: chunk.chunkIndex,
        document: chunk.document,
        score: scoreMap.get(chunk._id) ?? 0,
        documentTitle: doc?.title,
        documentTags: doc?.tags,
        documentSourceType: doc?.sourceType,
      };
    });

    // Sort chunks by score descending
    enrichedChunks.sort((a, b) => b.score - a.score);

    // Aggregate scores by document to find the top 2
    const docScores = new Map<string, number>();
    for (const chunk of enrichedChunks) {
      docScores.set(chunk.document, (docScores.get(chunk.document) ?? 0) + chunk.score);
    }

    const topDocIds = [...docScores.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([id]) => id);

    const topDocuments = topDocIds
      .map((id) => documents.find((d) => d._id === id))
      .filter((d): d is NonNullable<typeof d> => d !== undefined);

    return { chunks: enrichedChunks, topDocuments };
  },
});

// ============================================================================
// MUTATIONS
// ============================================================================

/**
 * Create a new lens.
 */
export const createLens = mutation({
  args: {
    name: v.string(),
    authorName: v.string(),
    description: v.string(),
    systemPrompt: v.string(),
    url: v.optional(v.string()),
    createdBy: v.id("users"),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("lenses")
      .withIndex("by_name", (q) => q.eq("name", args.name))
      .first();

    if (existing) {
      throw new Error(`Lens with name "${args.name}" already exists`);
    }

    const id = await ctx.db.insert("lenses", args);
    return await ctx.db.get(id);
  },
});

/**
 * Create a document for a lens.
 */
export const createDocument = mutation({
  args: {
    lens: v.id("lenses"),
    title: v.string(),
    sourceType: SourceType,
    originalText: v.string(),
    summary: v.string(),
    chunkCount: v.number(),
    publishedAt: v.optional(v.number()),
    tags: v.optional(v.array(v.string())),
  },
  handler: async (ctx, args) => {
    const lens = await ctx.db.get(args.lens);
    if (!lens) {
      throw new Error("Lens not found");
    }

    const id = await ctx.db.insert("lensDocuments", args);
    return await ctx.db.get(id);
  },
});

/**
 * Create a chunk for a document.
 */
export const createChunk = mutation({
  args: {
    lens: v.id("lenses"),
    document: v.id("lensDocuments"),
    content: v.string(),
    chunkIndex: v.number(),
    embedding: v.array(v.float64()),
  },
  handler: async (ctx, args) => {
    const id = await ctx.db.insert("lensChunks", args);
    return id;
  },
});

/**
 * Batch create chunks for a document.
 */
export const createChunks = mutation({
  args: {
    chunks: v.array(
      v.object({
        lens: v.id("lenses"),
        document: v.id("lensDocuments"),
        content: v.string(),
        chunkIndex: v.number(),
        embedding: v.array(v.float64()),
      })
    ),
  },
  handler: async (ctx, args) => {
    const ids = [];
    for (const chunk of args.chunks) {
      const id = await ctx.db.insert("lensChunks", chunk);
      ids.push(id);
    }
    return ids;
  },
});
