import { yellow, green, label } from "./colors.js";
import { t } from "../i18n/index.js";
export function renderTodosLine(ctx) {
    const { todos } = ctx.transcript;
    const colors = ctx.config?.colors;
    if (!todos || todos.length === 0) {
        return null;
    }
    const inProgress = todos.find((todo) => todo.status === "in_progress");
    const completed = todos.filter((todo) => todo.status === "completed").length;
    const total = todos.length;
    if (!inProgress) {
        if (completed === total && total > 0) {
            return `${green("✓")} ${t("status.allTodosComplete")} ${label(`(${completed}/${total})`, colors)}`;
        }
        return null;
    }
    const content = truncateContent(inProgress.content);
    const progress = label(`(${completed}/${total})`, colors);
    return `${yellow("▸")} ${content} ${progress}`;
}
function truncateContent(content, maxLen = 50) {
    if (content.length <= maxLen)
        return content;
    return content.slice(0, maxLen - 3) + "...";
}
//# sourceMappingURL=todos-line.js.map