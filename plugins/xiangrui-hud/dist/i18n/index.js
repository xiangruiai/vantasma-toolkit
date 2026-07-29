import { en } from "./en.js";
import { zh } from "./zh.js";
const locales = { en, zh };
let currentLanguage = "en";
export function setLanguage(lang) {
    currentLanguage = lang;
}
export function getLanguage() {
    return currentLanguage;
}
export function t(key) {
    return locales[currentLanguage][key] ?? locales.en[key] ?? key;
}
//# sourceMappingURL=index.js.map