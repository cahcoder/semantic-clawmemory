/**
 * agents-memory Managed Hook (CommonJS)
 * Events: message:preprocessed, session:compact:after
 * 
 * Optimizations:
 * - LRU cache with TTL
 * - Query optimization (truncation + stopword removal)
 * - Connection keep-alive
 */

const net = require("net");
const path = require("path");

const SOCKET = process.env.HOME + "/.memory/agents-memory/daemon.sock";
const MEMORY_DIR = process.env.HOME + "/.memory/agents-memory";

// ───────────────────────────────────────────────────────────────
// CACHE (LRU with TTL)
// ───────────────────────────────────────────────────────────────
const CACHE_TTL = 300000;     // 5 minutes (300s) — conversations span longer than 30s
const CACHE_MAX = 100;        // Max entries
const cache = new Map();

function getCacheKey(query, limit) {
    return `${query.slice(0, 100)}:${limit}`;
}

function getCached(key) {
    const entry = cache.get(key);
    if (!entry) return null;
    if (Date.now() - entry.ts > CACHE_TTL) {
        cache.delete(key);
        return null;
    }
    return entry.data;
}

function setCache(key, data) {
    // Evict oldest if at capacity
    if (cache.size >= CACHE_MAX) {
        let oldestKey = null;
        let oldestTs = Infinity;
        for (const [k, v] of cache) {
            if (v.ts < oldestTs) {
                oldestTs = v.ts;
                oldestKey = k;
            }
        }
        if (oldestKey) cache.delete(oldestKey);
    }
    cache.set(key, { data, ts: Date.now() });
}

// ───────────────────────────────────────────────────────────────
// SOCKET CONNECTION (persistent)
// ───────────────────────────────────────────────────────────────
let socket = null;
let socketPromise = null;

function getSocket() {
    if (socketPromise) return socketPromise;
    
    socketPromise = new Promise((resolve, reject) => {
        const s = net.createConnection(SOCKET, () => {
            socket = s;
            socketPromise = null;
            resolve(s);
        });
        s.on("error", (err) => {
            socket = null;
            socketPromise = null;
            reject(err);
        });
        s.on("close", () => {
            socket = null;
            socketPromise = null;
        });
        s.setTimeout(15000, () => {
            s.destroy();
            socket = null;
            socketPromise = null;
            reject(new Error("timeout"));
        });
    });
    return socketPromise;
}

function daemonCall(cmd, args, retries = 2) {
    return new Promise(async (resolve, reject) => {
        let lastError = null;
        
        for (let attempt = 0; attempt <= retries; attempt++) {
            try {
                const s = await getSocket();
                const req = JSON.stringify({cmd, args});
                const data = [];
                
                s.write(req, () => {
                    s.once("data", (chunk) => {
                        data.push(chunk);
                        try {
                            const result = JSON.parse(data.join(""));
                            // Check for daemon-level errors
                            if (result && result.error) {
                                reject(new Error(result.error));
                            } else {
                                resolve(result);
                            }
                        } catch (e) {
                            reject(new Error("parse error"));
                        }
                    });
                });
                return;  // Success, exit retry loop
                
            } catch (e) {
                lastError = e;
                // On socket error, force reconnection on next attempt
                socket = null;
                socketPromise = null;
                
                if (attempt < retries) {
                    // Wait before retry (exponential backoff)
                    await new Promise(r => setTimeout(r, 100 * Math.pow(2, attempt)));
                }
            }
        }
        
        // All retries failed
        console.warn(`[agents-memory] daemonCall failed after ${retries + 1} attempts:`, lastError?.message);
        reject(lastError || new Error("daemon unavailable"));
    });
}

// ───────────────────────────────────────────────────────────────
// QUERY OPTIMIZATION
// ───────────────────────────────────────────────────────────────
const STOPWORDS = new Set([
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'to', 'of', 'and', 'or', 'but', 'in', 'on', 'at', 'by', 'for',
    'with', 'about', 'against', 'between', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'from', 'up', 'down', 'out',
    'off', 'over', 'under', 'again', 'further', 'then', 'once',
    'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
    'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
    'can', 'will', 'just', 'don', 'now'
]);

function optimizeQuery(msg) {
    if (!msg || msg.length < 3) return msg;
    
    // Truncate to 200 chars at WORD BOUNDARIES (not mid-word)
    let query = msg;
    if (query.length > 200) {
        // Find last space before char 180 to avoid breaking words
        const cutoff = query.lastIndexOf(' ', 180);
        const startCut = cutoff > 100 ? cutoff : 180;
        // Keep first part + last 50 chars (filename/identifier often at end)
        query = query.slice(0, startCut) + "..." + query.slice(-50);
    }
    
    // Remove stopwords (only if query is long enough to not lose meaning)
    if (query.length > 50) {
        query = query.replace(/\b(\w+)\b/g, (match) => {
            return STOPWORDS.has(match.toLowerCase()) ? '' : match;
        });
    }
    
    // Clean up multiple spaces
    query = query.replace(/\s+/g, ' ').trim();
    
    return query || msg.slice(0, 50);
}

// ───────────────────────────────────────────────────────────────
// IN-MEMORY STORE (persists across hook invocations)
// ───────────────────────────────────────────────────────────────
let conversationHistory = [];   // Array of {role, content} objects
let lastAssistantResponse = null;
let messageCountSinceCompact = 0;

// Commands that should NOT be stored as conversation content
const COMMAND_PATTERNS = /^\/(compact|reset|clear|prune|help|status|memory|search|write|gc|stats|exit|quit)/i;
const isCommand = (msg) => COMMAND_PATTERNS.test(msg?.trim() || "");

// ───────────────────────────────────────────────────────────────
// SMART SNIPPET EXTRACTION (context-aware, not arbitrary truncation)
// ───────────────────────────────────────────────────────────────

/**
 * Extract the most relevant snippet from a memory entry.
 * Strategy:
 * 1. Always include problem statement (first line)
 * 2. Find sentence(s) most relevant to query
 * 3. Cap at ~500 chars total
 * 
 * Fixes:
 * - URL-safe splitting (don't break on http:// URLs)
 * - No hardcoded domain-specific boosts
 */
function extractSnippet(entry, query) {
    const content = entry.content || "";
    const collection = entry.collection || "memory";
    const score = entry.score ? entry.score.toFixed(2) : "";
    const prefix = `[${collection} score=${score}]`;
    
    // If entry is short enough, return full content
    if (content.length <= 450) {
        return { text: `${prefix} ${content}`, full: true };
    }
    
    // Split into sentences (URL-safe: only split on sentence-ending punctuation NOT followed by alphanumeric)
    // This avoids breaking URLs like http://example.com/path?query=1
    const sentences = content.split(/(?<=[.!?])\s+(?=[A-Z])/g);
    
    // Also split on newlines for entries with line breaks
    const lines = content.split('\n');
    const segments = sentences.length > 1 || sentences[0].length > 200 ? sentences : lines;
    
    // Query words for relevance matching (exclude short/common words)
    const stopwords = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'to', 'of', 'and', 'or', 'but', 'in', 'on', 'at', 'by', 'for', 'with',
        'this', 'that', 'these', 'those', 'it', 'its', 'from', 'have', 'has', 'had']);
    const queryWords = query.toLowerCase().split(/\s+/)
        .filter(w => w.length > 2 && !stopwords.has(w));
    
    // Score each segment by relevance to query
    const scoredSegments = segments.map((segment, idx) => {
        const lower = segment.toLowerCase();
        let relevance = 0;
        
        // Count query word matches
        for (const word of queryWords) {
            if (lower.includes(word)) relevance += 2;
        }
        
        // Boost first segment (problem statement)
        if (idx === 0) relevance += 3;
        
        // Boost segments with technical content (code, paths, commands)
        if (/[`\-$<>]/.test(segment)) relevance += 1;
        
        return { segment: segment.trim(), relevance, isFirst: idx === 0 };
    });
    
    // Sort by relevance (highest first)
    scoredSegments.sort((a, b) => b.relevance - a.relevance);
    
    // Build snippet: problem statement + most relevant segments
    const problemStatement = scoredSegments[0].isFirst 
        ? scoredSegments[0].segment 
        : segments[0];
    
    let snippet = problemStatement;
    
    // Add most relevant segment(s) until we hit limit
    for (const scored of scoredSegments) {
        if (scored.isFirst) continue;  // Already added
        if (snippet.length + scored.segment.length > 420) break;
        snippet += " " + scored.segment;
    }
    
    // Clean up and add prefix
    snippet = snippet.replace(/\s+/g, ' ').trim();
    if (!snippet.endsWith('.') && !snippet.endsWith('!') && !snippet.endsWith('?')) {
        snippet += '...';
    }
    
    return { text: `${prefix} ${snippet}`, full: false };
}

// ───────────────────────────────────────────────────────────────
// MESSAGE EXTRACTION
// ───────────────────────────────────────────────────────────────
function getMessageBody(event) {
    const ctx = event && event.context;
    if (!ctx) return null;
    return ctx.bodyForAgent || ctx.body || null;
}

function extractTextContent(content) {
    if (!content) return null;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
        return content.map(extractTextContent).filter(Boolean).join(" ");
    }
    if (content && content.type === "text") return content.text;
    return null;
}

// ───────────────────────────────────────────────────────────────
// PRE-LLM: Query memory + track conversation
// ───────────────────────────────────────────────────────────────
async function messagePreprocessed(event) {
    const rawMsg = getMessageBody(event);
    if (!rawMsg || rawMsg.length < 3) return;
    
    // Track conversation for POST-LLM (skip commands - they pollute learning)
    if (!isCommand(rawMsg)) {
        conversationHistory.push({ role: "user", content: rawMsg });
    }
    lastAssistantResponse = null;
    messageCountSinceCompact++;
    
    try {
        const originalQuery = rawMsg.slice(0, 100);
        const query = optimizeQuery(rawMsg);
        const cacheKey = getCacheKey(query, 5);
        
        // Check cache first
        const cached = getCached(cacheKey);
        let results;
        
        if (cached) {
            console.log("[agents-memory] Cache hit:", originalQuery.slice(0, 30) + "...");
            results = cached;
        } else {
            console.log("[agents-memory] Query:", originalQuery.slice(0, 30) + "...");
            const response = await daemonCall("search", {
                query: query,
                limit: 5,
                project: event.context && event.context.project
            });
            results = response && response.data && response.data.data;
            
            if (results && results.length) {
                setCache(cacheKey, results);
            }
        }
        
        // Filter results: only inject if score >= 0 (passed threshold)
        const validResults = (results || []).filter(r => (r.score || 0) >= 0);
        
        if (!validResults.length) {
            console.log("[agents-memory] No results above threshold — skipping injection");
            return;
        }
        
        // Calculate token budget (estimate ~4 chars per token, leave room for response)
        const MAX_INJECT_CHARS = 1500;  // ~375 tokens budget for memory context
        
        // Extract smart snippets from entries
        const snippets = validResults.slice(0, 3).map(r => {
            return extractSnippet(r, rawMsg);
        });
        
        // Build context respecting token budget
        let totalChars = 0;
        let contextParts = [];
        
        for (let i = 0; i < snippets.length; i++) {
            const snippet = snippets[i];
            // Check if adding this snippet would exceed budget
            if (totalChars + snippet.text.length + 50 > MAX_INJECT_CHARS) {
                // If first entry and we still have room, add truncated version
                if (i === 0 && totalChars < MAX_INJECT_CHARS - 100) {
                    const remaining = MAX_INJECT_CHARS - totalChars - 50;
                    contextParts.push(snippet.text.slice(0, remaining) + "...");
                    totalChars += remaining + 50;
                }
                break;  // Stop adding more
            }
            contextParts.push(snippet.text);
            totalChars += snippet.text.length + 50;
        }
        
        if (contextParts.length) {
            const context = contextParts.join("\n");
            event.messages.push({
                role: "system",
                content: "Relevant context:\n" + context
            });
            console.log(`[agents-memory] Injected ${contextParts.length} snippets (${context.length} chars, budget=${MAX_INJECT_CHARS})`);
        }
    } catch (e) {
        console.warn("[agents-memory] Error:", e.message);
    }
}

// ───────────────────────────────────────────────────────────────
// POST-LLM: Store learning after compaction
// ───────────────────────────────────────────────────────────────
async function sessionCompactAfter(event) {
    console.log("[agents-memory] Session compacted, checking for learnings...");
    
    // Need meaningful conversation (skip if only commands were said)
    if (conversationHistory.length < 1 || messageCountSinceCompact < 2) {
        console.log("[agents-memory] Skipping write - insufficient context");
        messageCountSinceCompact = 0;
        return;
    }
    
    try {
        // Build problem from conversation context
        const userMessages = conversationHistory
            .filter(m => m.role === "user")
            .map(m => m.content)
            .slice(-5);  // Last 5 user messages max
        
        const problem = userMessages.join(" | ") || "(conversation)";
        const solution = lastAssistantResponse || "(AI response captured in session)";
        
        await daemonCall("write", {
            problem: problem.slice(0, 200),
            solution: solution.slice(0, 500),
            type: "learning"
        });
        
        console.log("[agents-memory] ✅ Stored learning:", problem.slice(0, 50));
        console.log("[agents-memory] 📚 Conversation size:", conversationHistory.length, "messages");
        
        // Reset after write
        conversationHistory = [];
        lastAssistantResponse = null;
        messageCountSinceCompact = 0;
        
    } catch (e) {
        console.warn("[agents-memory] POST-LLM write error:", e.message);
    }
}

// ───────────────────────────────────────────────────────────────
// DISPATCHER
// ───────────────────────────────────────────────────────────────
async function handler(event) {
    const hook = event && event.type && event.action 
        ? (event.type + ":" + event.action) 
        : undefined;
    
    if (hook === "message:preprocessed") {
        return messagePreprocessed(event);
    } else if (hook === "session:compact:after") {
        return sessionCompactAfter(event);
    }
}

module.exports = handler;
module.exports.default = handler;
module.exports.messagePreprocessed = messagePreprocessed;
module.exports.sessionCompactAfter = sessionCompactAfter;
module.exports.optimizeQuery = optimizeQuery;
module.exports.getCacheStats = () => ({ size: cache.size, max: CACHE_MAX });
