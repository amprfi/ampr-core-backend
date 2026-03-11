import { v } from "convex/values";
import { query, mutation, internalQuery, internalMutation, action, internalAction } from "./_generated/server";
import { internal } from "./_generated/api";
import { SourceType } from "./tables/lenses";

// ============================================================================
// INGESTION HELPERS
// ============================================================================

const CHUNK_SIZE = 1024;
const CHUNK_OVERLAP = 128;
const EMBED_MODEL = "mistral-embed";

/**
 * Split markdown text into overlapping chunks, preferring splits at
 * heading (##) or blank-line (paragraph) boundaries.
 */
function chunkDocument(text: string): string[] {
  // Split into blocks on headings or double-newlines, preserving the delimiter.
  const blocks = text.split(/(?=^##\s)/m);
  const segments: string[] = [];
  for (const block of blocks) {
    // Further split large blocks on paragraph boundaries.
    const paragraphs = block.split(/\n\n+/);
    for (const p of paragraphs) {
      const trimmed = p.trim();
      if (trimmed.length > 0) {
        segments.push(trimmed);
      }
    }
  }

  const chunks: string[] = [];
  let current = "";

  for (const segment of segments) {
    // If adding this segment would exceed the limit, flush current chunk.
    if (current.length > 0 && current.length + segment.length + 1 > CHUNK_SIZE) {
      chunks.push(current);
      // Start next chunk with overlap from the tail of the previous chunk.
      const overlap = current.slice(-CHUNK_OVERLAP);
      current = overlap + "\n\n" + segment;
    } else {
      current = current.length > 0 ? current + "\n\n" + segment : segment;
    }
  }

  if (current.trim().length > 0) {
    chunks.push(current);
  }

  return chunks;
}

/**
 * Call the Mistral embeddings API to embed a batch of text chunks.
 * Returns one 1024-d vector per chunk, in the same order.
 */
async function embedChunks(chunks: string[]): Promise<number[][]> {
  const apiKey = process.env.MISTRAL_API_KEY;
  if (!apiKey) {
    throw new Error("MISTRAL_API_KEY environment variable not set");
  }

  const response = await fetch("https://api.mistral.ai/v1/embeddings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: EMBED_MODEL,
      input: chunks,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Mistral embed API error ${response.status}: ${body}`);
  }

  const json = (await response.json()) as {
    data: Array<{ index: number; embedding: number[] }>;
  };
  // The API returns data sorted by index, but sort explicitly to be safe.
  const sorted = json.data
    .sort((a, b) => a.index - b.index);
  return sorted.map((d) => d.embedding);
}

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

/**
 * Internal query to get a document by ID (used by ingestDocument action).
 */
export const getDocumentById = internalQuery({
  args: { id: v.id("lensDocuments") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

/**
 * Internal mutation to patch a document's originalText and storageId.
 * Called by importDocumentFromStorage action.
 */
export const patchDocumentText = internalMutation({
  args: {
    documentId: v.id("lensDocuments"),
    originalText: v.string(),
    storageId: v.id("_storage"),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.documentId, {
      originalText: args.originalText,
      storageId: args.storageId,
    });
  },
});

// ============================================================================
// ACTIONS
// ============================================================================

const vectorSearchArgs = {
  lensId: v.id("lenses"),
  embedding: v.array(v.float64()),
  limit: v.optional(v.number()),
};

type VectorSearchResult = {
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
};

async function runVectorSearch(
  ctx: { vectorSearch: any; runQuery: any },
  args: { lensId: any; embedding: number[]; limit?: number },
): Promise<VectorSearchResult> {
  const limit = args.limit ?? 10;

  const results = await ctx.vectorSearch("lensChunks", "by_embedding", {
    vector: args.embedding,
    limit,
    filter: (q: any) => q.eq("lens", args.lensId),
  });

  if (results.length === 0) {
    return { chunks: [], topDocuments: [] };
  }

  const chunkIds = results.map((r: any) => r._id);
  const { chunks, documents } = await ctx.runQuery(
    internal.lenses.getChunksWithDocuments,
    { ids: chunkIds },
  );

  // Build a score map from vector search results
  const scoreMap = new Map(results.map((r: any) => [r._id, r._score]));

  // Build a document lookup for enriching chunks
  const docMap = new Map(documents.map((d: any) => [d._id, d]));

  // Attach scores and document metadata to chunks
  const enrichedChunks = chunks.map((chunk: any) => {
    const doc = docMap.get(chunk.document) as any;
    return {
      _id: chunk._id,
      content: chunk.content,
      chunkIndex: chunk.chunkIndex,
      document: chunk.document,
      score: scoreMap.get(chunk._id) ?? 0,
      documentTitle: doc?.title as string | undefined,
      documentTags: doc?.tags as string[] | undefined,
      documentSourceType: doc?.sourceType as string | undefined,
    };
  });

  // Sort chunks by score descending
  enrichedChunks.sort((a: any, b: any) => b.score - a.score);

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
    .map((id) => documents.find((d: any) => d._id === id))
    .filter((d: any): d is NonNullable<typeof d> => d !== undefined);

  return { chunks: enrichedChunks, topDocuments };
}

/**
 * Vector search over content chunks within a lens (public).
 * Actions are required for vector search in Convex.
 */
export const vectorSearchChunks = action({
  args: vectorSearchArgs,
  handler: async (ctx, args) => runVectorSearch(ctx, args),
});

/**
 * Internal vector search (called by searchByText action).
 */
export const vectorSearchChunksInternal = internalAction({
  args: vectorSearchArgs,
  handler: async (ctx, args) => runVectorSearch(ctx, args),
});

/**
 * Search a lens by raw text query. Embeds the query via Mistral, then
 * delegates to the same vector search + document aggregation logic.
 */
export const searchByText = action({
  args: {
    lensId: v.id("lenses"),
    query: v.string(),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args): Promise<VectorSearchResult> => {
    const [embedding] = await embedChunks([args.query]);

    return await ctx.runAction(internal.lenses.vectorSearchChunksInternal, {
      lensId: args.lensId,
      embedding: embedding!,
      limit: args.limit,
    });
  },
});

/**
 * Import markdown content from a file in Convex storage into a document's
 * originalText field. Upload the .md file via the dashboard's file storage,
 * then call this action with the document ID and storage ID.
 */
export const importDocumentFromStorage = action({
  args: {
    documentId: v.id("lensDocuments"),
    storageId: v.id("_storage"),
  },
  handler: async (ctx, args) => {
    const blob = await ctx.storage.get(args.storageId);
    if (!blob) {
      throw new Error("File not found in storage");
    }

    const text = await blob.text();

    await ctx.runMutation(internal.lenses.patchDocumentText, {
      documentId: args.documentId,
      originalText: text,
      storageId: args.storageId,
    });

    return { success: true, length: text.length };
  },
});

/**
 * Ingest a document: chunk its originalText, embed via Mistral, and store
 * the chunks with their embeddings. Call this after a document has been
 * created (and its originalText populated) to make it searchable.
 *
 * Updates the document's chunkCount when finished.
 */
export const ingestDocument = action({
  args: {
    documentId: v.id("lensDocuments"),
  },
  handler: async (ctx, args) => {
    // 1. Fetch the document to get its text and parent lens.
    const doc = await ctx.runQuery(internal.lenses.getDocumentById, {
      id: args.documentId,
    });
    if (!doc) {
      throw new Error("Document not found");
    }
    if (!doc.originalText || doc.originalText.trim().length === 0) {
      throw new Error("Document has no originalText to ingest");
    }

    // 2. Chunk the text.
    const chunks = chunkDocument(doc.originalText);

    // 3. Embed all chunks via Mistral.
    const embeddings = await embedChunks(chunks);

    // 4. Write chunks + embeddings to the database.
    await ctx.runMutation(internal.lenses.createChunksBatch, {
      chunks: chunks.map((content, i) => ({
        lens: doc.lens,
        document: args.documentId,
        content,
        chunkIndex: i,
        embedding: embeddings[i]!,
      })),
    });

    // 5. Update the document's chunkCount.
    await ctx.runMutation(internal.lenses.patchChunkCount, {
      documentId: args.documentId,
      chunkCount: chunks.length,
    });

    return {
      success: true,
      chunksCreated: chunks.length,
    };
  },
});

/**
 * Import from storage + ingest in one step. Upload a .md file to Convex
 * storage, create a document record (with summary, title, etc.), then call
 * this action to populate originalText, chunk, embed, and store — all at once.
 */
export const importAndIngestDocument = action({
  args: {
    documentId: v.id("lensDocuments"),
    storageId: v.id("_storage"),
  },
  handler: async (ctx, args) => {
    // 1. Read file from storage.
    const blob = await ctx.storage.get(args.storageId);
    if (!blob) {
      throw new Error("File not found in storage");
    }
    const text = await blob.text();

    // 2. Save the text + storageId to the document.
    await ctx.runMutation(internal.lenses.patchDocumentText, {
      documentId: args.documentId,
      originalText: text,
      storageId: args.storageId,
    });

    // 3. Fetch the document to get the parent lens ID.
    const doc = await ctx.runQuery(internal.lenses.getDocumentById, {
      id: args.documentId,
    });
    if (!doc) {
      throw new Error("Document not found after patching text");
    }

    // 4. Chunk the text.
    const chunks = chunkDocument(text);

    // 5. Embed all chunks via Mistral.
    const embeddings = await embedChunks(chunks);

    // 6. Write chunks + embeddings to the database.
    await ctx.runMutation(internal.lenses.createChunksBatch, {
      chunks: chunks.map((content, i) => ({
        lens: doc.lens,
        document: args.documentId,
        content,
        chunkIndex: i,
        embedding: embeddings[i]!,
      })),
    });

    // 7. Update the document's chunkCount.
    await ctx.runMutation(internal.lenses.patchChunkCount, {
      documentId: args.documentId,
      chunkCount: chunks.length,
    });

    return {
      success: true,
      textLength: text.length,
      chunksCreated: chunks.length,
    };
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
    publisher: v.optional(v.string()),
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
    authorName: v.optional(v.string()),
    sourceType: SourceType,
    originalText: v.string(),
    summary: v.string(),
    chunkCount: v.number(),
    publishedAt: v.optional(v.number()),
    storageId: v.optional(v.id("_storage")),
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

/**
 * Internal batch create chunks (called by ingestDocument action).
 */
export const createChunksBatch = internalMutation({
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

/**
 * Internal mutation to update a document's chunkCount after ingestion.
 */
export const patchChunkCount = internalMutation({
  args: {
    documentId: v.id("lensDocuments"),
    chunkCount: v.number(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.documentId, {
      chunkCount: args.chunkCount,
    });
  },
});
