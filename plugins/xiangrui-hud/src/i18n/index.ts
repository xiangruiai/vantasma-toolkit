import type { Language, MessageKey, Messages } from "./types.js";
import { en } from "./en.js";
import { zh } from "./zh.js";

export type { Language, MessageKey, Messages };

const locales: Record<Language, Messages> = { en, zh };

let currentLanguage: Language = "en";

export function setLanguage(lang: Language): void {
  currentLanguage = lang;
}

export function getLanguage(): Language {
  return currentLanguage;
}

export function t(key: MessageKey): string {
  return locales[currentLanguage][key] ?? locales.en[key] ?? key;
}
