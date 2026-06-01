/**
 * DiDi Ride — Card Action Handler
 *
 * Handles button callbacks from DiDi ride interactive cards.
 * Called by monitor.js when action starts with "didi_".
 *
 * Key constraint: Feishu card.action.trigger has a 3-second timeout.
 * All DiDi API calls are executed asynchronously via setImmediate;
 * the synchronous path only returns a toast.
 *
 * Each action sends a NEW card message (not updating the original).
 *
 * Actions:
 *   didi_select_car → taxi_create_order → send waiting card
 *   didi_refresh     → taxi_query_order → send status card
 *   didi_cancel      → taxi_cancel_order → send cancelled card
 */
import { trace } from "../../core/trace.js";
import { sendCardFeishu } from "../../messaging/outbound/send.js";
import * as didi from "./client.js";
import {
    buildWaitingCard,
    buildDriverAcceptedCard,
    buildInTripCard,
    buildCompletedCard,
    buildErrorCard,
} from "./cards.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Send a new card message to the chat where the button was clicked.
 */
async function sendNewCard(cfg, accountId, chatId, openMessageId, card) {
    try {
        await sendCardFeishu({
            cfg,
            to: chatId,
            card,
            replyToMessageId: openMessageId,
            accountId,
        });
        trace.info(`didi-ride: new card sent to ${chatId}`);
    } catch (err) {
        const respData = err?.response?.data;
        trace.error(`didi-ride: failed to send card to ${chatId}: ${err}, response=${JSON.stringify(respData)}`);
    }
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

/**
 * Handle DiDi card button actions.
 *
 * @param {Object} data - Feishu card.action.trigger event data
 * @param {Object} cfg - OpenClaw configuration
 * @param {string} accountId - Feishu account ID
 * @returns {Object|undefined} Toast response for immediate display
 */
export async function handleDiDiCardAction(data, cfg, accountId) {
    const actionValue = data?.action?.value;
    if (!actionValue) return;

    const { action } = actionValue;
    trace.info(`didi-ride: card action "${action}" received`);

    const chatId = data?.context?.open_chat_id || data?.open_chat_id;
    const openMessageId = data?.context?.open_message_id || data?.open_message_id;
    if (!chatId) {
        trace.warn(`didi-ride: no chat_id found in event data`);
        return;
    }

    switch (action) {
        // -----------------------------------------------------------------
        // User selected a car type → create order → send waiting card
        // -----------------------------------------------------------------
        case "didi_select_car": {
            const { product_category, estimate_trace_id, car_name, from, to, price } = actionValue;

            setImmediate(async () => {
                try {
                    const result = await didi.createOrder(product_category, estimate_trace_id);
                    trace.info(`didi-ride: createOrder result: ${JSON.stringify(result)?.slice(0, 500)}`);

                    // Extract order_id from response (may be JSON object or text string)
                    const orderId = extractOrderId(result);

                    const card = buildWaitingCard({
                        from,
                        to,
                        carName: car_name,
                        orderId,
                    });

                    await sendNewCard(cfg, accountId, chatId, openMessageId, card);
                } catch (err) {
                    trace.error(`didi-ride: create order failed: ${err}`);
                    const errorCard = buildErrorCard({
                        from,
                        to,
                        message: `下单失败：${err.message || err}`,
                    });
                    await sendNewCard(cfg, accountId, chatId, openMessageId, errorCard);
                }
            });

            return {
                toast: {
                    type: "info",
                    content: `正在叫车：${car_name} ¥${price}...`,
                },
            };
        }

        // -----------------------------------------------------------------
        // Refresh order status → send updated status card
        // -----------------------------------------------------------------
        case "didi_refresh": {
            const { order_id, from, to, car_name } = actionValue;

            setImmediate(async () => {
                try {
                    const result = await didi.queryOrder(order_id);
                    trace.info(`didi-ride: queryOrder result: ${JSON.stringify(result)?.slice(0, 800)}`);

                    // Parse order info (may be text string or JSON object)
                    const orderInfo = parseOrderQueryResult(result);
                    trace.info(`didi-ride: parsed orderInfo: ${JSON.stringify(orderInfo)}`);

                    const status = orderInfo.status;
                    let card;

                    if (status === "completed" || status === "finished") {
                        card = buildCompletedCard({
                            from,
                            to,
                            carName: car_name,
                            status: "completed",
                            price: orderInfo.price,
                        });
                    } else if (status === "cancelled" || status === "canceled") {
                        card = buildCompletedCard({
                            from,
                            to,
                            carName: car_name,
                            status: "cancelled",
                        });
                    } else if (status === "in_trip" || status === "trip_start") {
                        card = buildInTripCard({
                            from,
                            to,
                            carName: car_name,
                            orderId: order_id,
                            driverName: orderInfo.driverName,
                            carPlate: orderInfo.carPlate,
                        });
                    } else if (status === "driver_accepted" || status === "arriving" || status === "wait_passenger") {
                        // Build ETA string combining distance + time
                        let etaStr = orderInfo.eta;
                        if (orderInfo.pickupDistance && !etaStr?.includes(orderInfo.pickupDistance)) {
                            etaStr = [orderInfo.pickupDistance, etaStr].filter(Boolean).join("，");
                        }

                        card = buildDriverAcceptedCard({
                            from,
                            to,
                            carName: orderInfo.carModel || car_name,
                            orderId: order_id,
                            driverName: orderInfo.driverName,
                            carPlate: orderInfo.carPlate,
                            phone: orderInfo.phone,
                            eta: etaStr,
                        });
                    } else if (status === "created" || status === "waiting" || status === "unknown") {
                        card = buildWaitingCard({
                            from,
                            to,
                            carName: car_name,
                            orderId: order_id,
                        });
                    } else {
                        // Unrecognized status — show raw info
                        card = buildWaitingCard({
                            from,
                            to,
                            carName: car_name,
                            orderId: order_id,
                        });
                    }

                    await sendNewCard(cfg, accountId, chatId, openMessageId, card);
                } catch (err) {
                    trace.error(`didi-ride: refresh order failed: ${err}`);
                    const errorCard = buildErrorCard({
                        from,
                        to,
                        message: `查询订单状态失败：${err.message || err}`,
                    });
                    await sendNewCard(cfg, accountId, chatId, openMessageId, errorCard);
                }
            });

            return {
                toast: {
                    type: "info",
                    content: "正在刷新订单状态...",
                },
            };
        }

        // -----------------------------------------------------------------
        // Cancel order → send cancelled card
        // -----------------------------------------------------------------
        case "didi_cancel": {
            const { order_id, from, to, car_name } = actionValue;

            setImmediate(async () => {
                try {
                    await didi.cancelOrder(order_id);

                    const card = buildCompletedCard({
                        from: from || "—",
                        to: to || "—",
                        carName: car_name || "—",
                        status: "cancelled",
                    });

                    await sendNewCard(cfg, accountId, chatId, openMessageId, card);
                } catch (err) {
                    trace.error(`didi-ride: cancel order failed: ${err}`);
                    const errorCard = buildErrorCard({
                        from,
                        to,
                        message: `取消订单失败：${err.message || err}`,
                    });
                    await sendNewCard(cfg, accountId, chatId, openMessageId, errorCard);
                }
            });

            return {
                toast: {
                    type: "info",
                    content: "正在取消订单...",
                },
            };
        }

        default:
            trace.warn(`didi-ride: unknown action "${action}"`);
            return;
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract order_id from taxi_create_order result.
 * Result may be a JSON object or a plain text string like:
 *   "订单ID: abc123" or "order_id: abc123"
 */
function extractOrderId(result) {
    if (!result) return "pending";

    // JSON object
    if (typeof result === "object") {
        if (result.order_id) return result.order_id;
        if (result.data?.order_id) return result.data.order_id;
        if (result.orderId) return result.orderId;
    }

    // Text format
    const text = typeof result === "string" ? result : JSON.stringify(result);
    const match = text.match(/(?:订单号|订单ID|order_id|orderId)[：:\s]+([^\s,\n]+)/i);
    if (match) return match[1];

    return "pending";
}

/**
 * Parse taxi_query_order result into structured order info.
 * DiDi MCP returns text like:
 *   "订单号：sy0HYbEa1mVFms\n状态：waiting_for_driver\n司机：张三\n车牌：京A12345\n电话：13800138000\n预计到达：5分钟"
 * Or JSON object with status/driver_name/etc fields.
 */
function parseOrderQueryResult(result) {
    const info = {
        status: "unknown",
        driverName: undefined,
        carPlate: undefined,
        phone: undefined,
        eta: undefined,
        price: undefined,
    };

    if (!result) return info;

    // JSON object format
    if (typeof result === "object") {
        info.status = result.status || result.order_status || result.data?.status || "unknown";
        info.driverName = result.driver_name || result.driver_info?.name;
        info.carPlate = result.car_plate || result.plate_number || result.driver_info?.plate_number;
        info.phone = result.driver_phone || result.driver_info?.phone;
        info.eta = result.eta || result.driver_info?.eta;
        info.price = result.price || result.actual_price || result.data?.price;
        return info;
    }

    // Text format — parse fields from text
    const text = String(result);

    // Status: infer from descriptive text
    if (text.match(/(?:状态|status)[：:\s]+([^\s,\n]+)/i)) {
        info.status = normalizeStatus(RegExp.$1);
    } else {
        // Infer status from descriptive phrases
        info.status = inferStatusFromText(text);
    }

    // Driver name: "称呼：靳师傅" or "司机：xxx" or "driver_name: xxx"
    const driverMatch = text.match(/(?:称呼|司机|driver|driver_name)[：:\s]+([^\s,\n•]+)/i);
    if (driverMatch) info.driverName = driverMatch[1];

    // Car plate
    const plateMatch = text.match(/(?:车牌|plate|plate_number)[：:\s]+([^\s,\n•]+)/i);
    if (plateMatch) info.carPlate = plateMatch[1];

    // Phone
    const phoneMatch = text.match(/(?:电话|phone|手机)[：:\s]+([^\s,\n•]+)/i);
    if (phoneMatch) info.phone = phoneMatch[1];

    // Car model: "车型：黑 · 红旗 · E-QM5"
    const carModelMatch = text.match(/(?:车型)[：:\s]+([^\n]+)/i);
    if (carModelMatch) info.carModel = carModelMatch[1].trim();

    // ETA: "约需3分钟到达" or "预计到达：5分钟"
    const etaMatch = text.match(/(?:约需|预计到达|eta|预计|到达时间)[：:\s]*([^\n,。]+?(?:分钟|小时|min)(?:到达)?)/i);
    if (etaMatch) info.eta = etaMatch[1].trim();

    // Distance to pickup: "师傅离上车点还有：1.3 公里"
    const distMatch = text.match(/离上车点还有[：:\s]*([^\n,，]+)/i);
    if (distMatch) info.pickupDistance = distMatch[1].trim();

    // Price: "已预付：18.90元" or "费用：¥18"
    const priceMatch = text.match(/(?:已预付|费用|价格|price|金额|实际费用)[：:\s]*¥?(\d+(?:\.\d+)?)\s*元?/i);
    if (priceMatch) info.price = priceMatch[1];

    return info;
}

/**
 * Normalize Chinese/English status strings to internal status codes.
 */
function normalizeStatus(raw) {
    if (!raw) return "unknown";
    return inferStatusFromText(raw);
}

/**
 * Infer order status from descriptive Chinese text.
 */
function inferStatusFromText(text) {
    if (!text) return "unknown";
    const s = text.toLowerCase();

    // Completed / finished
    if (s.includes("已完成") || s.includes("完成") || s.includes("结束") || s.includes("completed") || s.includes("finished")) return "completed";
    // Cancelled
    if (s.includes("已取消") || s.includes("取消") || s.includes("cancel")) return "cancelled";
    // In trip
    if (s.includes("行程中") || s.includes("进行中") || s.includes("出发") || s.includes("in_trip") || s.includes("trip_start") || s.includes("送往目的地")) return "in_trip";
    // Driver accepted / arriving — "匹配到司机" / "来接您" / "师傅离上车点"
    if (s.includes("匹配到司机") || s.includes("来接您") || s.includes("师傅离") || s.includes("已接单") || s.includes("接单") || s.includes("arriving") || s.includes("accepted") || s.includes("已到达上车点") || s.includes("等待乘客")) return "driver_accepted";
    // Created / waiting
    if (s.includes("created") || s.includes("创建") || s.includes("待接单") || s.includes("waiting") || s.includes("等待") || s.includes("正在匹配")) return "created";

    return "unknown";
}
