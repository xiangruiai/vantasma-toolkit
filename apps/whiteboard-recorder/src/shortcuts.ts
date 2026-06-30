import type { LanguageCode } from './i18n';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';

export const SHORTCUT_STORAGE_KEY = 'excalicord_shortcuts';

export type ShortcutActionId =
  | 'toolSelection'
  | 'toolHand'
  | 'toolRectangle'
  | 'toolDiamond'
  | 'toolEllipse'
  | 'toolArrow'
  | 'toolLine'
  | 'toolDraw'
  | 'toolText'
  | 'toolImage'
  | 'toolEraser'
  | 'toolFrame'
  | 'toolEmbeddable'
  | 'toolLaser'
  | 'record'
  | 'cancelPreview'
  | 'pauseResume'
  | 'stopRecording'
  | 'openSettings'
  | 'openShortcutSettings'
  | 'openLibrary'
  | 'toggleTeleprompter'
  | 'toggleCursor'
  | 'toggleCamera'
  | 'toolLock'
  | 'toggleGrid'
  | 'objectsSnap'
  | 'zenMode'
  | 'viewMode'
  | 'arrowBinding'
  | 'properties';

export type ShortcutSettings = Record<ShortcutActionId, string>;

export type ShortcutGroupId = 'tools' | 'recording' | 'panels' | 'editor';

export const SHORTCUT_GROUPS: Array<{
  id: ShortcutGroupId;
  actions: ShortcutActionId[];
}> = [
  {
    id: 'tools',
    actions: [
      'toolSelection',
      'toolHand',
      'toolRectangle',
      'toolDiamond',
      'toolEllipse',
      'toolArrow',
      'toolLine',
      'toolDraw',
      'toolText',
      'toolImage',
      'toolEraser',
      'toolFrame',
      'toolEmbeddable',
      'toolLaser',
    ],
  },
  {
    id: 'recording',
    actions: [
      'record',
      'cancelPreview',
      'pauseResume',
      'stopRecording',
    ],
  },
  {
    id: 'panels',
    actions: [
      'openSettings',
      'openShortcutSettings',
      'openLibrary',
      'toggleTeleprompter',
      'toggleCursor',
      'toggleCamera',
    ],
  },
  {
    id: 'editor',
    actions: [
      'toolLock',
      'toggleGrid',
      'objectsSnap',
      'zenMode',
      'viewMode',
      'arrowBinding',
      'properties',
    ],
  },
];

export const DEFAULT_SHORTCUTS: ShortcutSettings = {
  toolSelection: 'V',
  toolHand: 'H',
  toolRectangle: 'R',
  toolDiamond: 'D',
  toolEllipse: 'O',
  toolArrow: 'A',
  toolLine: 'L',
  toolDraw: 'P',
  toolText: 'T',
  toolImage: '9',
  toolEraser: 'E',
  toolFrame: 'F',
  toolEmbeddable: 'Alt+Shift+W',
  toolLaser: 'K',
  record: 'Alt+Shift+R',
  cancelPreview: 'Escape',
  pauseResume: 'Alt+Shift+P',
  stopRecording: 'Alt+Shift+S',
  openSettings: 'Alt+Comma',
  openShortcutSettings: 'Alt+Shift+Comma',
  openLibrary: 'Alt+Shift+L',
  toggleTeleprompter: 'Alt+Shift+T',
  toggleCursor: 'Alt+Shift+C',
  toggleCamera: 'Alt+Shift+V',
  toolLock: 'Q',
  toggleGrid: 'Mod+Quote',
  objectsSnap: 'Alt+S',
  zenMode: 'Alt+Z',
  viewMode: 'Alt+R',
  arrowBinding: 'Alt+B',
  properties: 'Alt+Slash',
};

const SYSTEM_KEY_LABELS: Record<string, string> = {
  Backspace: 'Backspace',
  Delete: 'Delete',
  Enter: 'Enter',
  Escape: 'Esc',
  Space: 'Space',
  Tab: 'Tab',
  ArrowUp: '↑',
  ArrowDown: '↓',
  ArrowLeft: '←',
  ArrowRight: '→',
  Comma: ',',
  Period: '.',
  Slash: '/',
  Backslash: '\\',
  Quote: "'",
  Semicolon: ';',
  BracketLeft: '[',
  BracketRight: ']',
  Minus: '-',
  Equal: '=',
  Backquote: '`',
};

const KEY_ALIASES: Record<string, string> = {
  ' ': 'Space',
  Esc: 'Escape',
  ',': 'Comma',
  '.': 'Period',
  '/': 'Slash',
  '\\': 'Backslash',
  "'": 'Quote',
  ';': 'Semicolon',
  '[': 'BracketLeft',
  ']': 'BracketRight',
  '-': 'Minus',
  '=': 'Equal',
  '`': 'Backquote',
};

const normalizeKey = (key: string) => {
  if (KEY_ALIASES[key]) {
    return KEY_ALIASES[key];
  }

  if (key.length === 1) {
    return key.toUpperCase();
  }

  return key;
};

export const getInitialShortcuts = (): ShortcutSettings => {
  try {
    const stored = window.localStorage.getItem(SHORTCUT_STORAGE_KEY);
    if (!stored) {
      return DEFAULT_SHORTCUTS;
    }

    const parsed = JSON.parse(stored) as Partial<ShortcutSettings>;

    return {
      ...DEFAULT_SHORTCUTS,
      ...Object.fromEntries(
        Object.entries(parsed).filter(([, value]) => typeof value === 'string'),
      ),
    };
  } catch {
    return DEFAULT_SHORTCUTS;
  }
};

export const saveShortcuts = (shortcuts: ShortcutSettings) => {
  try {
    window.localStorage.setItem(SHORTCUT_STORAGE_KEY, JSON.stringify(shortcuts));
  } catch {
    // Storage can fail in private mode. Shortcuts still work for the session.
  }
};

export const shortcutFromKeyboardEvent = (event: KeyboardEvent | ReactKeyboardEvent) => {
  if (event.key === 'Meta' || event.key === 'Control' || event.key === 'Alt' || event.key === 'Shift') {
    return '';
  }

  const keys: string[] = [];

  if (event.metaKey || event.ctrlKey) {
    keys.push('Mod');
  }
  if (event.altKey) {
    keys.push('Alt');
  }
  if (event.shiftKey) {
    keys.push('Shift');
  }

  keys.push(normalizeKey(event.key));

  return keys.join('+');
};

export const matchesShortcut = (event: KeyboardEvent, shortcut: string) => {
  if (!shortcut) {
    return false;
  }

  return shortcutFromKeyboardEvent(event) === shortcut;
};

export const formatShortcut = (shortcut: string, language: LanguageCode) => {
  if (!shortcut) {
    return language === 'zh-CN' ? '未设置' : 'Not set';
  }

  return shortcut
    .split('+')
    .map((part) => {
      if (part === 'Mod') return '⌘';
      if (part === 'Alt') return '⌥';
      if (part === 'Shift') return '⇧';
      if (part === 'Ctrl') return '⌃';

      return SYSTEM_KEY_LABELS[part] || part;
    })
    .join('');
};

export const isEditableShortcutTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return Boolean(
    target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]'),
  );
};
