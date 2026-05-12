/**
 * DiDi MCP JSON-RPC 2.0 HTTP Client
 *
 * Standalone client for the DiDi ride-hailing MCP service.
 * Endpoint and API key are read from environment variables.
 *
 * Tool name mapping (MCP actual API):
 *   maps_textsearch         — POI search (keywords + city → lng/lat)
 *   taxi_estimate            — estimate pricing (coords → products + trace_id)
 *   taxi_create_order        — create ride order (product_category + trace_id)
 *   taxi_query_order         — query order status
 *   taxi_cancel_order        — cancel order
 *   taxi_get_driver_location — driver real-time location
 *   taxi_generate_ride_app_link — deep link for DiDi app
 *   maps_direction_driving   — driving route (distance + duration)
 */
import { trace } from "../../core/trace.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DIDI_SANDBOX_URL = "https://mcp.didichuxing.com/mcp-servers-sandbox";
const DIDI_PROD_URL = "https://mcp.didichuxing.com/mcp-servers";

// Set to true to use sandbox (mock data, no real orders)
const DIDI_DEBUG_MODE = true;

function getDiDiEndpoint() {
    const key = process.env.DIDI_MCP_KEY?.trim();
    if (DIDI_DEBUG_MODE && key) {
        return `${DIDI_SANDBOX_URL}?key=${key}`;
    }
    if (key) {
        return `${DIDI_PROD_URL}?key=${key}`;
    }
    return DIDI_SANDBOX_URL;
}

// ---------------------------------------------------------------------------
// JSON-RPC transport
// ---------------------------------------------------------------------------

let rpcIdCounter = 1;

async function rpcCall(method, params) {
    const endpoint = getDiDiEndpoint();
    const id = String(rpcIdCounter++);
    const body = {
        jsonrpc: "2.0",
        id,
        method,
        params,
    };

    trace.info(`didi-mcp: → ${method} (id=${id})`);

    const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });

    const text = await res.text();
    if (!res.ok) {
        throw new Error(`DiDi MCP HTTP ${res.status}: ${text.slice(0, 2000)}`);
    }

    let data;
    try {
        data = JSON.parse(text);
    } catch {
        throw new Error(`DiDi MCP returned non-JSON: ${text.slice(0, 2000)}`);
    }

    if (data.error) {
        const err = data.error;
        throw new Error(`DiDi MCP error ${err.code}: ${err.message}`);
    }

    trace.info(`didi-mcp: ← ${method} OK`);
    return unwrapResult(data.result);
}

function unwrapResult(v) {
    if (v && typeof v === "object" && "jsonrpc" in v && "result" in v) {
        return unwrapResult(v.result);
    }
    return v;
}

// ---------------------------------------------------------------------------
// Generic MCP tool call
// ---------------------------------------------------------------------------

/**
 * List available DiDi MCP tools.
 */
export async function listTools() {
    return rpcCall("tools/list", {});
}

/**
 * Call a named DiDi MCP tool with the given arguments.
 * NOT exported — use the specific wrapper functions below, or the didi_ride registered tool.
 */
async function callTool(toolName, args) {
    return rpcCall("tools/call", { name: toolName, arguments: args });
}

// ---------------------------------------------------------------------------
// POI Search — maps_textsearch
// ---------------------------------------------------------------------------

/**
 * Search for a place by keyword + city, returns lng/lat and display name.
 * @param {string} keywords - e.g. "太原西客站"
 * @param {string} city - e.g. "太原"
 * @returns Parsed first POI result: { lng, lat, name, address }
 */
export async function searchPlace(keywords, city) {
    const raw = await callTool("maps_textsearch", { keywords, city });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Price Estimate — taxi_estimate
// ---------------------------------------------------------------------------

/**
 * Estimate pricing for a ride given origin/destination coordinates.
 * @returns { estimate_trace_id, products: [{product_category, product_name, price, ...}] }
 */
export async function estimatePrice({ from_lng, from_lat, from_name, to_lng, to_lat, to_name }) {
    const raw = await callTool("taxi_estimate", {
        from_lng, from_lat, from_name,
        to_lng, to_lat, to_name,
    });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Create Order — taxi_create_order
// ---------------------------------------------------------------------------

/**
 * Create a ride order.
 * @param {string} product_category - e.g. "201"
 * @param {string} estimate_trace_id - from estimatePrice result
 */
export async function createOrder(product_category, estimate_trace_id) {
    const raw = await callTool("taxi_create_order", {
        product_category,
        estimate_trace_id,
    });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Query Order — taxi_query_order
// ---------------------------------------------------------------------------

export async function queryOrder(orderId) {
    const raw = await callTool("taxi_query_order", { order_id: orderId });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Cancel Order — taxi_cancel_order
// ---------------------------------------------------------------------------

export async function cancelOrder(orderId) {
    const raw = await callTool("taxi_cancel_order", { order_id: orderId });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Driver Location — taxi_get_driver_location
// ---------------------------------------------------------------------------

export async function getDriverLocation(orderId) {
    const raw = await callTool("taxi_get_driver_location", { order_id: orderId });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Ride App Link — taxi_generate_ride_app_link
// ---------------------------------------------------------------------------

export async function generateRideLink({ from_lng, from_lat, to_lng, to_lat, product_category }) {
    const raw = await callTool("taxi_generate_ride_app_link", {
        from_lng, from_lat, to_lng, to_lat, product_category,
    });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Driving Directions — maps_direction_driving
// ---------------------------------------------------------------------------

/**
 * Get driving route info (distance + duration).
 * @param {string} origin - "lng,lat"
 * @param {string} destination - "lng,lat"
 */
export async function getDrivingDirection(origin, destination) {
    const raw = await callTool("maps_direction_driving", { origin, destination });
    return parseTextContent(raw);
}

// ---------------------------------------------------------------------------
// Response parsing helpers
// ---------------------------------------------------------------------------

/**
 * Parse MCP content format. The result is usually:
 *   { content: [{ type: "text", text: "{...json...}" }] }
 * This helper extracts and parses the JSON from the first text content.
 * Returns the parsed object, or the raw result if not in content format.
 */
function parseTextContent(result) {
    if (!result) return result;

    // MCP content format
    if (result.content && Array.isArray(result.content)) {
        for (const item of result.content) {
            if (item.type === "text" && item.text) {
                try {
                    return JSON.parse(item.text);
                } catch {
                    return item.text;
                }
            }
        }
    }

    // Already a plain object
    return result;
}
