/**
 * DiDi Ride — Feishu Interactive Card Templates (CardKit v2)
 *
 * Card states: querying, select_car, waiting, driver_accepted, in_trip, completed/cancelled, error.
 * All buttons use `value.action` prefixed with "didi_" for routing in monitor.js.
 */

// ---------------------------------------------------------------------------
// 1. Querying — "正在查询车型和价格..."
// ---------------------------------------------------------------------------

export function buildQueryingCard(from, to) {
    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: "🚗 正在查询车型和价格..." },
            template: "blue",
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: `**起点**：${from}\n**终点**：${to}\n\n正在为你查询可用车型和预估价格，请稍候...`,
                },
            ],
        },
    };
}

// ---------------------------------------------------------------------------
// 2. Select Car — route summary + car type list + price + buttons
// ---------------------------------------------------------------------------

/**
 * @param {Object} params
 * @param {string} params.from - Origin display name
 * @param {string} params.to - Destination display name
 * @param {Array<{product_name: string, product_category: string, price: number|string}>} params.cars
 * @param {string} params.estimate_trace_id - Required for creating orders
 * @param {string} [params.distance] - e.g. "18km"
 * @param {string} [params.duration] - e.g. "25分钟"
 */
export function buildSelectCarCard({ from, to, cars, estimate_trace_id, distance, duration }) {
    // Route summary line
    const routeParts = [`📍 ${from} → ${to}`];
    if (distance || duration) {
        const info = [distance, duration].filter(Boolean).join(" · ");
        routeParts.push(info);
    }
    const routeSummary = routeParts.join(" | 约");

    const carElements = cars.map((car) => {
        const priceText = typeof car.price === "number" ? `¥${car.price}` : `${car.price}`;

        return {
            tag: "column_set",
            flex_mode: "none",
            horizontal_spacing: "default",
            columns: [
                {
                    tag: "column",
                    width: "weighted",
                    weight: 3,
                    vertical_align: "center",
                    elements: [
                        {
                            tag: "markdown",
                            content: `**${car.product_name}**　${priceText}`,
                        },
                    ],
                },
                {
                    tag: "column",
                    width: "weighted",
                    weight: 1,
                    vertical_align: "center",
                    elements: [
                        {
                            tag: "button",
                            text: { tag: "plain_text", content: `叫车 ${priceText}` },
                            type: "primary",
                            value: {
                                action: "didi_select_car",
                                product_category: String(car.product_category),
                                estimate_trace_id,
                                car_name: car.product_name,
                                from,
                                to,
                                price: car.price,
                            },
                        },
                    ],
                },
            ],
        };
    });

    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: "🚗 选择车型" },
            template: "blue",
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: routeSummary,
                },
                { tag: "hr" },
                ...carElements,
            ],
        },
    };
}

// ---------------------------------------------------------------------------
// 3. Waiting — order created, waiting for driver
// ---------------------------------------------------------------------------

export function buildWaitingCard({ from, to, carName, orderId }) {
    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: "🚗 等待司机接单" },
            template: "orange",
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: `**车型**：${carName}\n**起点**：${from}\n**终点**：${to}\n\n订单已创建，正在为你匹配司机...`,
                },
                { tag: "hr" },
                {
                    tag: "column_set",
                    flex_mode: "none",
                    horizontal_spacing: "default",
                    columns: [
                        {
                            tag: "column",
                            width: "weighted",
                            weight: 1,
                            vertical_align: "center",
                            elements: [
                                {
                                    tag: "button",
                                    text: { tag: "plain_text", content: "刷新状态" },
                                    type: "default",
                                    value: {
                                        action: "didi_refresh",
                                        order_id: orderId,
                                        from,
                                        to,
                                        car_name: carName,
                                    },
                                },
                            ],
                        },
                        {
                            tag: "column",
                            width: "weighted",
                            weight: 1,
                            vertical_align: "center",
                            elements: [
                                {
                                    tag: "button",
                                    text: { tag: "plain_text", content: "取消订单" },
                                    type: "danger",
                                    value: {
                                        action: "didi_cancel",
                                        order_id: orderId,
                                        from,
                                        to,
                                        car_name: carName,
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    };
}

// ---------------------------------------------------------------------------
// 4. Driver Accepted — driver info + car plate + ETA
// ---------------------------------------------------------------------------

export function buildDriverAcceptedCard({ from, to, carName, orderId, driverName, carPlate, phone, eta }) {
    const infoLines = [
        `**车型**：${carName}`,
        driverName ? `**司机**：${driverName}` : null,
        carPlate ? `**车牌**：${carPlate}` : null,
        phone ? `**电话**：${phone}` : null,
        eta ? `**预计到达**：${eta}` : null,
    ].filter(Boolean).join("\n");

    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: "🚗 司机已接单" },
            template: "green",
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: `**起点**：${from}\n**终点**：${to}`,
                },
                { tag: "hr" },
                {
                    tag: "markdown",
                    content: infoLines,
                },
                { tag: "hr" },
                {
                    tag: "column_set",
                    flex_mode: "none",
                    horizontal_spacing: "default",
                    columns: [
                        {
                            tag: "column",
                            width: "weighted",
                            weight: 1,
                            vertical_align: "center",
                            elements: [
                                {
                                    tag: "button",
                                    text: { tag: "plain_text", content: "刷新状态" },
                                    type: "default",
                                    value: {
                                        action: "didi_refresh",
                                        order_id: orderId,
                                        from,
                                        to,
                                        car_name: carName,
                                    },
                                },
                            ],
                        },
                        {
                            tag: "column",
                            width: "weighted",
                            weight: 1,
                            vertical_align: "center",
                            elements: [
                                {
                                    tag: "button",
                                    text: { tag: "plain_text", content: "取消订单" },
                                    type: "danger",
                                    value: {
                                        action: "didi_cancel",
                                        order_id: orderId,
                                        from,
                                        to,
                                        car_name: carName,
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    };
}

// ---------------------------------------------------------------------------
// 5. In Trip — ongoing ride
// ---------------------------------------------------------------------------

export function buildInTripCard({ from, to, carName, orderId, driverName, carPlate }) {
    const infoLines = [
        `**车型**：${carName}`,
        driverName ? `**司机**：${driverName}` : null,
        carPlate ? `**车牌**：${carPlate}` : null,
    ].filter(Boolean).join("\n");

    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: "🚗 行程进行中" },
            template: "green",
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: `**起点**：${from}\n**终点**：${to}`,
                },
                { tag: "hr" },
                {
                    tag: "markdown",
                    content: infoLines,
                },
                { tag: "hr" },
                {
                    tag: "column_set",
                    flex_mode: "none",
                    horizontal_spacing: "default",
                    columns: [
                        {
                            tag: "column",
                            width: "weighted",
                            weight: 1,
                            vertical_align: "center",
                            elements: [
                                {
                                    tag: "button",
                                    text: { tag: "plain_text", content: "刷新状态" },
                                    type: "default",
                                    value: {
                                        action: "didi_refresh",
                                        order_id: orderId,
                                        from,
                                        to,
                                        car_name: carName,
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    };
}

// ---------------------------------------------------------------------------
// 6. Completed / Cancelled — final state
// ---------------------------------------------------------------------------

export function buildCompletedCard({ from, to, carName, status, price }) {
    const isCancel = status === "cancelled";
    const headerTitle = isCancel ? "🚗 订单已取消" : "🚗 行程已完成";
    const headerTemplate = isCancel ? "grey" : "green";
    const statusText = isCancel ? "已取消" : "已完成";
    const priceText = price ? `\n**费用**：¥${price}` : "";

    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: headerTitle },
            template: headerTemplate,
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: `**状态**：${statusText}\n**车型**：${carName}\n**起点**：${from}\n**终点**：${to}${priceText}`,
                },
            ],
        },
    };
}

// ---------------------------------------------------------------------------
// 7. Error card
// ---------------------------------------------------------------------------

export function buildErrorCard({ from, to, message }) {
    return {
        schema: "2.0",
        config: { wide_screen_mode: true },
        header: {
            title: { tag: "plain_text", content: "🚗 打车服务异常" },
            template: "red",
        },
        body: {
            elements: [
                {
                    tag: "markdown",
                    content: `**起点**：${from || "—"}\n**终点**：${to || "—"}\n\n${message}`,
                },
            ],
        },
    };
}
