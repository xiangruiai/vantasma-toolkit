/**
 * DiDi Ride — OpenClaw Tool Registration
 *
 * Registers the `didi_ride` tool so the AI agent can:
 * 1. Query pricing → POI search → estimate → send interactive card
 * 2. Users click buttons → handler.js processes callbacks
 *
 * Multi-step flow for query_pricing:
 *   1. maps_textsearch(from, city) → origin coords
 *   2. maps_textsearch(to, city) → destination coords
 *   3. taxi_estimate(coords) → products + estimate_trace_id
 *   4. maps_direction_driving(origin, destination) → distance/duration (optional)
 *   5. Build card → createCardEntity → sendCardByCardId
 */
import { Type } from "@sinclair/typebox";
import { createToolContext, formatToolResult, formatToolError } from "../helpers.js";
import { getTraceContext } from "../../core/trace.js";
import { sendCardFeishu } from "../../messaging/outbound/send.js";
import * as didi from "./client.js";
import { buildSelectCarCard, buildErrorCard } from "./cards.js";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const DiDiRideSchema = Type.Object({
    action: Type.Union([
        Type.Literal("query_pricing"),
        Type.Literal("list_tools"),
    ], {
        description: "操作类型：query_pricing（查询价格并发送交互卡片）、list_tools（查看可用的滴滴 MCP 工具）",
    }),
    from: Type.Optional(Type.String({
        description: "起点地址（自然语言，如 太原西客站、朝阳区建国门外大街1号）。query_pricing 时必填",
    })),
    to: Type.Optional(Type.String({
        description: "终点地址（自然语言）。query_pricing 时必填",
    })),
    city: Type.Optional(Type.String({
        description: "城市名（如 太原、北京）。可选，帮助 POI 搜索更准确。如不提供则从地址推断",
    })),
});

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerDiDiRideTool(api) {
    if (!api.config) return;
    const cfg = api.config;
    const { log } = createToolContext(api, "didi_ride");

    api.registerTool({
        name: "didi_ride",
        label: "DiDi Ride",
        description:
            "滴滴打车工具。查询从起点到终点的车型和预估价格，自动发送飞书交互卡片。" +
            "用户可以在卡片上点击按钮选择车型下单、查看订单状态、取消订单。" +
            "\n\n使用方式：当用户说「帮我叫车从A到B」「打车多少钱」等打车相关请求时调用此工具。" +
            "\n\nActions:" +
            "\n- query_pricing：查询车型价格并发送交互式选车卡片（需要 from 和 to 参数，可选 city）" +
            "\n- list_tools：查看滴滴 MCP 提供的所有可用工具",

        parameters: DiDiRideSchema,

        async execute(_toolCallId, params) {
            const p = params;

            try {
                switch (p.action) {
                    // ---------------------------------------------------------
                    // List available DiDi MCP tools
                    // ---------------------------------------------------------
                    case "list_tools": {
                        const result = await didi.listTools();
                        return formatToolResult(result);
                    }

                    // ---------------------------------------------------------
                    // Query pricing → multi-step flow → interactive card
                    // ---------------------------------------------------------
                    case "query_pricing": {
                        if (!p.from || !p.to) {
                            return formatToolResult({
                                error: "缺少参数：from（起点）和 to（终点）都是必填的",
                            });
                        }

                        const traceCtx = getTraceContext();
                        if (!traceCtx?.chatId) {
                            return formatToolResult({
                                error: "无法获取当前会话信息，请在飞书对话中使用此工具",
                            });
                        }

                        const { chatId, messageId, accountId: traceAccountId, threadId } = traceCtx;
                        const acctId = traceAccountId || "default";
                        const city = p.city || "";

                        log.info(`querying pricing: ${p.from} → ${p.to} (city=${city || "auto"})`);

                        // --- Step 1: POI search for origin ---
                        let fromPoi;
                        try {
                            fromPoi = await didi.searchPlace(p.from, city);
                            log.info(`origin POI: ${JSON.stringify(fromPoi)?.slice(0, 200)}`);
                        } catch (err) {
                            log.error(`POI search failed for origin "${p.from}": ${err}`);
                            return sendErrorAndReturn({
                                cfg, acctId, chatId, messageId, threadId,
                                from: p.from, to: p.to,
                                message: `起点「${p.from}」搜索失败：${err.message || err}`,
                            });
                        }

                        const fromCoords = extractCoords(fromPoi);
                        if (!fromCoords) {
                            log.error(`No coords found for origin "${p.from}": ${JSON.stringify(fromPoi)?.slice(0, 500)}`);
                            return sendErrorAndReturn({
                                cfg, acctId, chatId, messageId, threadId,
                                from: p.from, to: p.to,
                                message: `未能解析起点「${p.from}」的坐标，请尝试更具体的地址`,
                            });
                        }

                        // --- Step 2: POI search for destination ---
                        let toPoi;
                        try {
                            toPoi = await didi.searchPlace(p.to, city);
                            log.info(`destination POI: ${JSON.stringify(toPoi)?.slice(0, 200)}`);
                        } catch (err) {
                            log.error(`POI search failed for destination "${p.to}": ${err}`);
                            return sendErrorAndReturn({
                                cfg, acctId, chatId, messageId, threadId,
                                from: p.from, to: p.to,
                                message: `终点「${p.to}」搜索失败：${err.message || err}`,
                            });
                        }

                        const toCoords = extractCoords(toPoi);
                        if (!toCoords) {
                            log.error(`No coords found for destination "${p.to}": ${JSON.stringify(toPoi)?.slice(0, 500)}`);
                            return sendErrorAndReturn({
                                cfg, acctId, chatId, messageId, threadId,
                                from: p.from, to: p.to,
                                message: `未能解析终点「${p.to}」的坐标，请尝试更具体的地址`,
                            });
                        }

                        const fromName = fromCoords.name || p.from;
                        const toName = toCoords.name || p.to;

                        // --- Step 3: Estimate pricing ---
                        let estimateResult;
                        try {
                            estimateResult = await didi.estimatePrice({
                                from_lng: fromCoords.lng,
                                from_lat: fromCoords.lat,
                                from_name: fromName,
                                to_lng: toCoords.lng,
                                to_lat: toCoords.lat,
                                to_name: toName,
                            });
                            log.info(`estimate result: ${JSON.stringify(estimateResult)?.slice(0, 500)}`);
                        } catch (err) {
                            log.error(`taxi_estimate failed: ${err}`);
                            return sendErrorAndReturn({
                                cfg, acctId, chatId, messageId, threadId,
                                from: fromName, to: toName,
                                message: `查询价格失败：${err.message || err}`,
                            });
                        }

                        // Parse products and trace_id
                        const estimate_trace_id = extractEstimateTraceId(estimateResult);
                        const cars = parseProducts(estimateResult);

                        if (cars.length === 0) {
                            log.warn(`No products parsed from estimate result`);
                            return sendErrorAndReturn({
                                cfg, acctId, chatId, messageId, threadId,
                                from: fromName, to: toName,
                                message: "未能获取可用车型，请稍后再试",
                            });
                        }

                        // --- Step 4: Driving directions (optional, for distance/duration) ---
                        let distance, duration;
                        try {
                            const origin = `${fromCoords.lng},${fromCoords.lat}`;
                            const destination = `${toCoords.lng},${toCoords.lat}`;
                            const dirResult = await didi.getDrivingDirection(origin, destination);
                            if (dirResult) {
                                distance = extractRouteField(dirResult, "distance");
                                duration = extractRouteField(dirResult, "duration");
                            }
                        } catch (err) {
                            // Non-critical, just skip
                            log.warn(`maps_direction_driving failed (non-critical): ${err.message || err}`);
                        }

                        // --- Step 5: Build and send interactive card ---
                        const card = buildSelectCarCard({
                            from: fromName,
                            to: toName,
                            cars,
                            estimate_trace_id,
                            distance,
                            duration,
                        });

                        const replyTo = messageId?.startsWith("om_") ? messageId : undefined;
                        await sendCardFeishu({
                            cfg,
                            to: chatId,
                            card,
                            replyToMessageId: replyTo,
                            replyInThread: Boolean(threadId),
                            accountId: acctId,
                        });

                        log.info(`interactive card sent, ${cars.length} car types`);

                        return formatToolResult({
                            success: true,
                            message: "交互卡片已发送到会话，无需再发文字回复。",
                            silent: true,
                        });
                    }

                    default:
                        return formatToolResult({ error: `未知操作: ${p.action}` });
                }
            } catch (err) {
                log.error(`didi_ride failed: ${err}`);
                return formatToolError(err);
            }
        },
    }, { name: "didi_ride" });

    api.logger?.info?.("didi_ride: Registered didi_ride tool");
}

// ---------------------------------------------------------------------------
// Helper: send error card and return tool result
// ---------------------------------------------------------------------------

async function sendErrorAndReturn({ cfg, acctId, chatId, messageId, threadId, from, to, message }) {
    try {
        const errorCard = buildErrorCard({ from, to, message });
        const replyTo = messageId?.startsWith("om_") ? messageId : undefined;
        await sendCardFeishu({
            cfg,
            to: chatId,
            card: errorCard,
            replyToMessageId: replyTo,
            replyInThread: Boolean(threadId),
            accountId: acctId,
        });
    } catch {
        // Best effort
    }

    return formatToolResult({
        success: false,
        error: message,
        from,
        to,
    });
}

// ---------------------------------------------------------------------------
// Result parsing helpers
// ---------------------------------------------------------------------------

/**
 * Extract lng/lat/name from a POI search result.
 * Handles various response shapes from maps_textsearch.
 */
function extractCoords(poi) {
    if (!poi) return null;

    // Direct fields
    if (poi.lng && poi.lat) {
        return { lng: String(poi.lng), lat: String(poi.lat), name: poi.name || poi.display_name || poi.title };
    }

    // Nested location
    if (poi.location) {
        const loc = poi.location;
        if (loc.lng && loc.lat) {
            return { lng: String(loc.lng), lat: String(loc.lat), name: poi.name || poi.display_name || poi.title };
        }
        // "lng,lat" string format
        if (typeof loc === "string" && loc.includes(",")) {
            const [lng, lat] = loc.split(",");
            return { lng, lat, name: poi.name || poi.display_name || poi.title };
        }
    }

    // Array of results — take the first one
    if (Array.isArray(poi)) {
        return extractCoords(poi[0]);
    }

    // Nested in pois/results/data array
    for (const key of ["pois", "results", "data", "items"]) {
        if (poi[key] && Array.isArray(poi[key]) && poi[key].length > 0) {
            return extractCoords(poi[key][0]);
        }
    }

    return null;
}

/**
 * Extract estimate_trace_id from taxi_estimate result.
 * The result may be a JSON object OR a plain text string.
 *
 * Text format example:
 *   "...预估流程ID: 0a4ac21769b798eb573644ad16715402\n"
 */
function extractEstimateTraceId(result) {
    if (!result) return "";

    // JSON object format
    if (typeof result === "object") {
        if (result.estimate_trace_id) return result.estimate_trace_id;
        if (result.trace_id) return result.trace_id;
        if (result.data?.estimate_trace_id) return result.data.estimate_trace_id;
    }

    // Text format: parse "预估流程ID: xxx" or "estimate_trace_id: xxx"
    const text = typeof result === "string" ? result : JSON.stringify(result);
    const match = text.match(/(?:预估流程ID|estimate_trace_id)[：:\s]+([a-f0-9]+)/i);
    if (match) return match[1];

    return "";
}

/**
 * Parse product list from taxi_estimate result.
 * The result may be a JSON object/array OR a plain text string.
 *
 * Text format example:
 *   "1. 特惠快车: 约 38 元 (品类代码: 201)\n2. 快车: 约 39 元 (品类代码: 1)"
 */
function parseProducts(result) {
    if (!result) return [];

    // --- Text format (taxi_estimate returns this) ---
    if (typeof result === "string") {
        return parseProductsFromText(result);
    }

    // --- JSON object format ---
    let products = null;
    for (const key of ["products", "product_list", "cars", "car_types", "estimates", "data"]) {
        const val = result[key];
        if (Array.isArray(val) && val.length > 0) {
            products = val;
            break;
        }
    }

    if (!products && Array.isArray(result)) {
        products = result;
    }

    if (!products && result.data && typeof result.data === "object") {
        for (const key of ["products", "product_list", "cars"]) {
            if (Array.isArray(result.data[key])) {
                products = result.data[key];
                break;
            }
        }
    }

    if (products && products.length > 0) {
        return products.map(normalizeProduct).filter(Boolean);
    }

    // Fallback: try text parsing on stringified result
    return parseProductsFromText(JSON.stringify(result));
}

/**
 * Parse car types from text like:
 *   "1. 特惠快车: 约 38 元 (品类代码: 201)"
 *   "特惠快车 (product_category: 201)"
 */
function parseProductsFromText(text) {
    const cars = [];
    // Match lines like: "特惠快车: 约 38 元 (品类代码: 201)" or "特惠快车: 约 38 元 (product_category: 201)"
    const regex = /(\S+?)[：:]\s*约?\s*(\d+)\s*元\s*\((?:品类代码|product_category)[：:\s]*(\d+)\)/g;
    let match;
    while ((match = regex.exec(text)) !== null) {
        cars.push({
            product_name: match[1],
            product_category: match[2 + 1], // group 3
            price: parseInt(match[2]),
        });
    }

    // Fallback: try simpler pattern without category code
    if (cars.length === 0) {
        const simpleRegex = /\d+\.\s*(\S+?)[：:]\s*约?\s*(\d+)\s*元/g;
        while ((match = simpleRegex.exec(text)) !== null) {
            cars.push({
                product_name: match[1],
                product_category: "unknown",
                price: parseInt(match[2]),
            });
        }
    }

    return cars;
}

function normalizeProduct(raw) {
    if (!raw || typeof raw !== "object") return null;

    const product_name = raw.product_name || raw.name || raw.car_name || raw.type_name || raw.label;
    const product_category = raw.product_category || raw.category || raw.type || raw.product_type || raw.id;
    const price = raw.price || raw.estimated_price || raw.estimate_price || raw.fee || raw.cost;

    if (!product_name && !product_category) return null;

    return {
        product_name: product_name || `车型${product_category}`,
        product_category: String(product_category || "unknown"),
        price: typeof price === "number" ? price : (parseFloat(price) || price || "查看"),
    };
}

/**
 * Extract distance or duration from driving direction result.
 * Actual response shape: { distance: { text: "31.43 km", value: 31426 }, duration: { text: "32分钟", value: 1969 } }
 */
function extractRouteField(result, field) {
    if (!result) return undefined;

    // Direct nested object with .text (actual DiDi API format)
    if (result[field] && typeof result[field] === "object" && result[field].text) {
        return result[field].text;
    }

    // Direct value
    let val = result[field];

    // Nested in route/paths
    if (val === undefined) {
        const route = result.route || result.routes?.[0] || result.paths?.[0] || result.data;
        if (route) {
            if (route[field] && typeof route[field] === "object" && route[field].text) {
                return route[field].text;
            }
            val = route[field];
        }
    }

    if (val === undefined) return undefined;

    // Numeric value → format
    if (typeof val === "number" || (typeof val === "string" && /^\d+$/.test(val))) {
        const num = Number(val);
        if (field === "distance") {
            return num >= 1000 ? `${(num / 1000).toFixed(1)}km` : `${Math.round(num)}m`;
        }
        if (field === "duration") {
            const minutes = Math.round(num / 60);
            return minutes >= 60 ? `${Math.floor(minutes / 60)}小时${minutes % 60}分钟` : `${minutes}分钟`;
        }
    }

    return String(val);
}
