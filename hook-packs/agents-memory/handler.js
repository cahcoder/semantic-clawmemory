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
const CACHE_TTL = 30000;      // 30 seconds
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
        s.setTimeout(5000, () => {
            s.destroy();
            socket = null;
            socketPromise = null;
            reject(new Error("timeout"));
        });
    });
    return socketPromise;
}

function daemonCall(cmd, args) {
    return new Promise(async (resolve, reject) => {
        try {
            const s = await getSocket();
            const req = JSON.stringify({cmd, args});
            const data = [];
            
            s.write(req, () => {
                s.once("data", (chunk) => {
                    data.push(chunk);
                    try {
                        resolve(JSON.parse(data.join("")));
                    } catch {
                        reject(new Error("parse error"));
                    }
                });
            });
        } catch (e) {
            reject(e);
        }
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
    
    // Truncate to 200 chars (keep start + end for context)
    let query = msg;
    if (query.length > 200) {
        // Keep first 150 + last 50 (filename/identifier often at end)
        query = query.slice(0, 150) + "..." + query.slice(-50);
    }
    
    // Remove stopwords
    query = query.replace(/\b(\w+)\b/g, (match) => {
        return STOPWORDS.has(match.toLowerCase()) ? '' : match;
    });
    
    // Clean up multiple spaces
    query = query.replace(/\s+/g, ' ').trim();
    
    return query || msg.slice(0, 50);
}

// ───────────────────────────────────────────────────────────────
// IN-MEMORY STORE (persists across hook invocations)
// ───────────────────────────────────────────────────────────────
let lastUserMessage = null;
let lastAssistantResponse = null;
let messageCountSinceCompact = 0;

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
    
    // Track conversation for POST-LLM
    lastUserMessage = rawMsg;
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
            results = await daemonCall("search", {
                query: query,
                limit: 5,
                project: event.context && event.context.project
            });
            
            if (results && results.length) {
                setCache(cacheKey, results);
            }
        }
        
        if (results && results.length) {
            const context = results.slice(0, 3).map(r => {
                const col = r.collection || "memory";
                const content = (r.content || "").slice(0, 150);
                const sim = r.similarity ? ` sim=${r.similarity.toFixed(2)}` : "";
                return `[${col}${sim}] ${content}`;
            }).join("\n");
            
            event.messages.push({
                role: "system",
                content: "Relevant context:\n" + context
            });
            
            console.log("[agents-memory] Injected " + context.length + " chars, cache size=" + cache.size);
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
    
    if (!lastUserMessage || messageCountSinceCompact < 2) {
        console.log("[agents-memory] Skipping write - insufficient context");
        messageCountSinceCompact = 0;
        return;
    }
    
    try {
        const learning = {
            problem: lastUserMessage.slice(0, 200),
            solution: lastAssistantResponse || "(AI response captured in session)",
            type: "learning",
            messagesSinceCompact: messageCountSinceCompact
        };
        
        await daemonCall("write", {
            problem: learning.problem,
            solution: learning.solution,
            type: "learning"
        });
        
        console.log("[agents-memory] ✅ Stored learning:", learning.problem.slice(0, 50));
        
        // Reset after write
        lastUserMessage = null;
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
