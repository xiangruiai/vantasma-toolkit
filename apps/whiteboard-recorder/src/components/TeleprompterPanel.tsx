/*
 * Smart teleprompter adapter based on Voumellis/smart-teleprompter.
 * Copyright (c) 2025 Smart Teleprompter. Licensed under the MIT License.
 *
 * Local changes:
 * - Scoped the full-screen teleprompter into the Xiangrui whiteboard overlay.
 * - Reworked labels for this app's Chinese/English language switch.
 * - Kept Smart Teleprompter concepts: speech following, auto-scroll, word
 *   highlight, script library, file import, shortcuts, and display settings.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ChangeEvent,
  CSSProperties,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from 'react';
import type { LanguageCode } from '../i18n';

type TeleprompterPanelProps = {
  language: LanguageCode;
  value: string;
  position: { x: number; y: number };
  isDragging: boolean;
  frameWidth?: number;
  sidebarAvoidanceRight?: number;
  microphoneDeviceId?: string;
  onChange: (value: string) => void;
  onClose: () => void;
  onMouseDown: (event: ReactMouseEvent<HTMLDivElement>) => void;
};

type TextAlign = 'left' | 'center' | 'right';

type SmartTeleprompterSettings = {
  fontSize: number;
  lineHeight: number;
  scrollSpeed: number;
  textOpacity: number;
  uiOpacity: number;
  centerPadding: number;
  sidePadding: number;
  highlight: boolean;
  mirror: boolean;
  minimalMode: boolean;
  voiceFollow: boolean;
  align: TextAlign;
  speechLanguage: string;
  lookaheadWindow: number;
  panelHeight: number;
};

type SavedScript = {
  id: string;
  title: string;
  body: string;
  language: string;
  updatedAt: number;
};

type ScriptToken = {
  id: string;
  text: string;
  normalized: string;
  wordIndex: number | null;
  isCjk: boolean;
  marks?: ScriptTokenMarks;
};

type ScriptTokenMarks = {
  strong?: boolean;
  em?: boolean;
  code?: boolean;
  link?: boolean;
  strike?: boolean;
};

type ScriptBlockType = 'paragraph' | 'heading' | 'list' | 'quote' | 'code' | 'rule';

type ScriptLine = {
  id: string;
  tokens: ScriptToken[];
  empty: boolean;
  blockType: ScriptBlockType;
  headingLevel?: number;
  marker?: string;
};

type ScriptModel = {
  lines: ScriptLine[];
  words: Array<{ normalized: string; text: string }>;
};

type InlineMarkdownSegment = {
  text: string;
  marks?: ScriptTokenMarks;
};

type SpeechRecognitionAlternativeLike = {
  transcript?: string;
};

type SpeechRecognitionResultLike = {
  0?: SpeechRecognitionAlternativeLike;
  isFinal?: boolean;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
};

type SpeechRecognitionErrorEventLike = {
  error?: string;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  start: () => void;
  stop: () => void;
  abort?: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type PanelStyle = CSSProperties & {
  '--smart-teleprompter-ui-alpha': string;
  '--smart-teleprompter-text-alpha': string;
};

const SETTINGS_STORAGE_KEY = 'xiangrui_smart_teleprompter_settings_v1';
const SCRIPTS_STORAGE_KEY = 'xiangrui_smart_teleprompter_scripts_v1';
const MAX_SCRIPTS = 50;
const MAX_SPEECH_TOKENS = 18;

const clamp = (value: number, min: number, max: number) => (
  Math.min(Math.max(value, min), max)
);

const getCopy = (language: LanguageCode) => {
  if (language === 'en') {
    return {
      title: 'Teleprompter',
      play: 'Start',
      pause: 'Pause',
      voice: 'Voice follow',
      voiceOn: 'Following',
      edit: 'Script',
      library: 'Library',
      settings: 'Settings',
      reset: 'Reset',
      lightMode: 'Light mode',
      fullMode: 'Full mode',
      mirror: 'Mirror',
      close: 'Close teleprompter',
      placeholder: 'Paste your script here. This overlay is only for you and will not be rendered into the recording.',
      estimated: 'Est.',
      progress: 'Progress',
      save: 'Save script',
      import: 'Import',
      clear: 'Clear',
      load: 'Load',
      delete: 'Delete',
      noScripts: 'No saved scripts yet.',
      language: 'Speech language',
      lookahead: 'Lookahead',
      fontSize: 'Font size',
      lineHeight: 'Line height',
      speed: 'Auto-scroll speed',
      textOpacity: 'Text opacity',
      uiOpacity: 'Panel opacity',
      centerLine: 'Reading line',
      sidePadding: 'Side padding',
      highlight: 'Word highlight',
      align: 'Alignment',
      left: 'Left',
      center: 'Center',
      right: 'Right',
      unsupported: 'Speech recognition is not supported in this browser.',
      micError: 'Microphone is unavailable.',
      resize: 'Resize teleprompter',
    };
  }

  return {
    title: '提词器',
    play: '开始',
    pause: '暂停',
    voice: '语音跟随',
    voiceOn: '跟随中',
    edit: '讲稿',
    library: '脚本库',
    settings: '设置',
    reset: '回到开头',
    lightMode: '轻量模式',
    fullMode: '完整模式',
    mirror: '镜像',
    close: '关闭提词器',
    placeholder: '把讲稿粘贴到这里。这个浮层只给你看，不会被录进视频。',
    estimated: '预计',
    progress: '进度',
    save: '保存脚本',
    import: '导入',
    clear: '清空',
    load: '载入',
    delete: '删除',
    noScripts: '还没有保存脚本。',
    language: '识别语言',
    lookahead: '向前匹配',
    fontSize: '字号',
    lineHeight: '行高',
    speed: '滚动速度',
    textOpacity: '文字透明度',
    uiOpacity: '面板透明度',
    centerLine: '阅读线位置',
    sidePadding: '左右留白',
    highlight: '逐词高亮',
    align: '文字对齐',
    left: '左对齐',
    center: '居中',
    right: '右对齐',
    unsupported: '当前浏览器不支持语音识别。',
    micError: '麦克风暂不可用。',
    resize: '调整提词器高度',
  };
};

const speechLanguages = [
  { code: 'zh-CN', zh: '中文普通话', en: 'Chinese Mandarin' },
  { code: 'en-US', zh: '英语（美国）', en: 'English US' },
  { code: 'en-GB', zh: '英语（英国）', en: 'English UK' },
  { code: 'es-ES', zh: '西班牙语', en: 'Spanish' },
  { code: 'fr-FR', zh: '法语', en: 'French' },
  { code: 'de-DE', zh: '德语', en: 'German' },
  { code: 'it-IT', zh: '意大利语', en: 'Italian' },
  { code: 'pt-BR', zh: '葡萄牙语', en: 'Portuguese' },
  { code: 'nl-NL', zh: '荷兰语', en: 'Dutch' },
  { code: 'sv-SE', zh: '瑞典语', en: 'Swedish' },
  { code: 'no-NO', zh: '挪威语', en: 'Norwegian' },
  { code: 'da-DK', zh: '丹麦语', en: 'Danish' },
  { code: 'fi-FI', zh: '芬兰语', en: 'Finnish' },
  { code: 'pl-PL', zh: '波兰语', en: 'Polish' },
  { code: 'ru-RU', zh: '俄语', en: 'Russian' },
  { code: 'ja-JP', zh: '日语', en: 'Japanese' },
  { code: 'ko-KR', zh: '韩语', en: 'Korean' },
  { code: 'ar-SA', zh: '阿拉伯语', en: 'Arabic' },
  { code: 'hi-IN', zh: '印地语', en: 'Hindi' },
  { code: 'tr-TR', zh: '土耳其语', en: 'Turkish' },
];

const defaultSettings = (language: LanguageCode): SmartTeleprompterSettings => ({
  fontSize: language === 'zh-CN' ? 24 : 23,
  lineHeight: 1.72,
  scrollSpeed: 74,
  textOpacity: 90,
  uiOpacity: 18,
  centerPadding: 46,
  sidePadding: 24,
  highlight: true,
  mirror: false,
  minimalMode: false,
  voiceFollow: true,
  align: 'left',
  speechLanguage: language === 'zh-CN' ? 'zh-CN' : 'en-US',
  lookaheadWindow: 14,
  panelHeight: 310,
});

const readStoredSettings = (language: LanguageCode) => {
  const defaults = defaultSettings(language);

  try {
    const stored = window.localStorage.getItem(SETTINGS_STORAGE_KEY);

    if (!stored) {
      return defaults;
    }

    const parsed = JSON.parse(stored) as Partial<SmartTeleprompterSettings>;

    return {
      ...defaults,
      fontSize: clamp(Number(parsed.fontSize) || defaults.fontSize, 16, 72),
      lineHeight: clamp(Number(parsed.lineHeight) || defaults.lineHeight, 1.1, 2.3),
      scrollSpeed: clamp(Number(parsed.scrollSpeed) || defaults.scrollSpeed, 10, 200),
      textOpacity: clamp(Number(parsed.textOpacity) || defaults.textOpacity, 35, 100),
      uiOpacity: clamp(Number(parsed.uiOpacity) || defaults.uiOpacity, 0, 92),
      centerPadding: clamp(Number(parsed.centerPadding) || defaults.centerPadding, 22, 72),
      sidePadding: clamp(Number(parsed.sidePadding) || defaults.sidePadding, 8, 64),
      highlight: parsed.highlight !== false,
      mirror: parsed.mirror === true,
      minimalMode: parsed.minimalMode === true,
      voiceFollow: parsed.voiceFollow !== false,
      align: parsed.align === 'center' || parsed.align === 'right' ? parsed.align : defaults.align,
      speechLanguage: typeof parsed.speechLanguage === 'string' ? parsed.speechLanguage : defaults.speechLanguage,
      lookaheadWindow: clamp(Number(parsed.lookaheadWindow) || defaults.lookaheadWindow, 6, 28),
      panelHeight: clamp(Number(parsed.panelHeight) || defaults.panelHeight, 210, 560),
    };
  } catch {
    return defaults;
  }
};

const readStoredScripts = (): SavedScript[] => {
  try {
    const stored = window.localStorage.getItem(SCRIPTS_STORAGE_KEY);

    if (!stored) {
      return [];
    }

    const parsed = JSON.parse(stored) as Partial<SavedScript>[];

    return parsed
      .filter((script): script is SavedScript => (
        typeof script.id === 'string'
        && typeof script.title === 'string'
        && typeof script.body === 'string'
        && typeof script.language === 'string'
        && typeof script.updatedAt === 'number'
      ))
      .slice(0, MAX_SCRIPTS);
  } catch {
    return [];
  }
};

const getSpeechRecognitionConstructor = (): SpeechRecognitionConstructor | null => {
  const browserWindow = window as Window & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };

  return browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition ?? null;
};

const createId = () => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const normalizeWord = (input: string) => input
  .toLowerCase()
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/ς/g, 'σ')
  .replace(/[^\p{L}\p{N}\u3400-\u9fff]+/gu, '')
  .trim();

const tokenizeText = (input: string) => (
  input.match(/[\u3400-\u9fff]|\p{L}+(?:[-']\p{L}+)*|\p{N}+|\s+|[^\s]/gu) ?? []
);

const tokenizeSpeech = (input: string) => tokenizeText(input)
  .map(normalizeWord)
  .filter(Boolean);

const mergeMarks = (base: ScriptTokenMarks | undefined, next: ScriptTokenMarks): ScriptTokenMarks => ({
  ...(base ?? {}),
  ...next,
});

const parseInlineMarkdown = (input: string): InlineMarkdownSegment[] => {
  const segments: InlineMarkdownSegment[] = [];
  let index = 0;

  const pushSegment = (text: string, marks?: ScriptTokenMarks) => {
    if (!text) {
      return;
    }

    const last = segments[segments.length - 1];

    if (last && JSON.stringify(last.marks ?? {}) === JSON.stringify(marks ?? {})) {
      last.text += text;
      return;
    }

    segments.push({ text, marks });
  };

  while (index < input.length) {
    const rest = input.slice(index);
    const imageOrLink = /^!?\[([^\]]*)\]\(([^)]+)\)/.exec(rest);
    const code = /^`([^`]+)`/.exec(rest);
    const strong = /^(\*\*|__)(.+?)\1/.exec(rest);
    const strike = /^~~(.+?)~~/.exec(rest);
    const em = /^(\*|_)([^*_]+?)\1/.exec(rest);
    const escaped = /^\\([\\`*_[\]{}()#+\-.!])/.exec(rest);

    if (imageOrLink) {
      pushSegment(imageOrLink[1], { link: !rest.startsWith('!') });
      index += imageOrLink[0].length;
      continue;
    }

    if (code) {
      pushSegment(code[1], { code: true });
      index += code[0].length;
      continue;
    }

    if (strong) {
      parseInlineMarkdown(strong[2]).forEach((segment) => {
        pushSegment(segment.text, mergeMarks(segment.marks, { strong: true }));
      });
      index += strong[0].length;
      continue;
    }

    if (strike) {
      parseInlineMarkdown(strike[1]).forEach((segment) => {
        pushSegment(segment.text, mergeMarks(segment.marks, { strike: true }));
      });
      index += strike[0].length;
      continue;
    }

    if (em) {
      parseInlineMarkdown(em[2]).forEach((segment) => {
        pushSegment(segment.text, mergeMarks(segment.marks, { em: true }));
      });
      index += em[0].length;
      continue;
    }

    if (escaped) {
      pushSegment(escaped[1]);
      index += escaped[0].length;
      continue;
    }

    const nextSpecialIndex = rest.slice(1).search(/[\\`*_[~!]/);
    const plainLength = nextSpecialIndex >= 0 ? nextSpecialIndex + 1 : rest.length;
    pushSegment(rest.slice(0, plainLength));
    index += plainLength;
  }

  return segments;
};

const buildScriptModel = (text: string): ScriptModel => {
  let wordIndex = 0;
  const words: ScriptModel['words'] = [];
  let isInCodeBlock = false;
  const lines = text.split(/\r?\n/).map((line, lineIndex) => {
    const trimmedLine = line.trim();
    let blockType: ScriptBlockType = 'paragraph';
    let content = line;
    let headingLevel: number | undefined;
    let marker: string | undefined;

    if (/^```/.test(trimmedLine)) {
      isInCodeBlock = !isInCodeBlock;
      blockType = 'rule';
      content = '';
    } else if (isInCodeBlock) {
      blockType = 'code';
    } else {
      const headingMatch = /^(#{1,6})\s+(.+)$/.exec(line);
      const quoteMatch = /^>\s?(.+)$/.exec(line);
      const taskMatch = /^\s*[-*+]\s+\[([ xX])]\s+(.+)$/.exec(line);
      const unorderedMatch = /^\s*[-*+]\s+(.+)$/.exec(line);
      const orderedMatch = /^\s*(\d+)[.)]\s+(.+)$/.exec(line);

      if (/^([-*_])(?:\s*\1){2,}\s*$/.test(trimmedLine)) {
        blockType = 'rule';
        content = '';
      } else if (headingMatch) {
        blockType = 'heading';
        headingLevel = headingMatch[1].length;
        content = headingMatch[2];
      } else if (quoteMatch) {
        blockType = 'quote';
        content = quoteMatch[1];
      } else if (taskMatch) {
        blockType = 'list';
        marker = taskMatch[1].toLowerCase() === 'x' ? '✓' : '□';
        content = taskMatch[2];
      } else if (orderedMatch) {
        blockType = 'list';
        marker = `${orderedMatch[1]}.`;
        content = orderedMatch[2];
      } else if (unorderedMatch) {
        blockType = 'list';
        marker = '•';
        content = unorderedMatch[1];
      }
    }

    const inlineSegments = parseInlineMarkdown(content);
    let tokenIndex = 0;
    const tokens = inlineSegments.flatMap((segment) => (
      tokenizeText(segment.text).map((token) => {
        const normalized = normalizeWord(token);
        const currentWordIndex = normalized ? wordIndex : null;
        const modelToken: ScriptToken = {
          id: `${lineIndex}-${tokenIndex}`,
          text: token,
          normalized,
          wordIndex: currentWordIndex,
          isCjk: /[\u3400-\u9fff]/.test(token),
          marks: segment.marks,
        };

        tokenIndex += 1;

        if (normalized) {
          words.push({ normalized, text: token });
          wordIndex += 1;
        }

        return modelToken;
      })
    ));

    return {
      id: `${lineIndex}`,
      tokens,
      empty: tokens.length === 0,
      blockType,
      headingLevel,
      marker,
    };
  });

  return { lines, words };
};

const tokensEqual = (a: string | undefined, b: string | undefined) => (
  Boolean(a && b && a === b)
);

const tokensSoftMatch = (target: string | undefined, token: string | undefined) => {
  if (!target || !token) {
    return false;
  }

  if (target === token) {
    return true;
  }

  if (token.length >= 3 && (target.startsWith(token) || token.startsWith(target))) {
    return true;
  }

  if (token.length >= 4 && (target.includes(token) || token.includes(target))) {
    return true;
  }

  return false;
};

const formatDuration = (wordCount: number, language: LanguageCode) => {
  const wordsPerMinute = language === 'zh-CN' ? 240 : 150;
  const seconds = Math.max(1, Math.round((wordCount / wordsPerMinute) * 60));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;

  if (language === 'zh-CN') {
    return minutes > 0 ? `${minutes}分${rest}秒` : `${rest}秒`;
  }

  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
};

const titleFromScript = (body: string, language: LanguageCode) => {
  const firstLine = body.split(/\r?\n/).find((line) => line.trim())?.trim();

  if (!firstLine) {
    return language === 'zh-CN' ? '未命名脚本' : 'Untitled script';
  }

  return firstLine.length > 26 ? `${firstLine.slice(0, 26)}...` : firstLine;
};

const isEditableTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const tagName = target.tagName.toLowerCase();

  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable;
};

const Icon = ({ name }: { name: 'prompt' | 'play' | 'pause' | 'mic' | 'settings' | 'script' | 'library' | 'reset' | 'mirror' | 'minimal' | 'close' | 'import' | 'save' | 'trash' }) => {
  const paths = {
    prompt: (
      <>
        <rect x="5" y="4" width="14" height="13" rx="2.5" />
        <path d="M8 8h8" />
        <path d="M8 11h6.5" />
        <path d="M8 14h5" />
        <path d="M12 17v3" />
        <path d="M9 20h6" />
      </>
    ),
    play: <path d="M8 5v14l11-7-11-7z" />,
    pause: (
      <>
        <path d="M8 5v14" />
        <path d="M16 5v14" />
      </>
    ),
    mic: (
      <>
        <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" />
        <path d="M5 10v2a7 7 0 0 0 14 0v-2" />
        <path d="M12 19v3" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h9" />
        <path d="M17 7h3" />
        <path d="M4 17h3" />
        <path d="M11 17h9" />
        <circle cx="15" cy="7" r="2" />
        <circle cx="9" cy="17" r="2" />
      </>
    ),
    script: (
      <>
        <path d="M7 3h8l4 4v14H7z" />
        <path d="M15 3v5h5" />
        <path d="M10 12h6" />
        <path d="M10 16h6" />
      </>
    ),
    library: (
      <>
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        <path d="M8 6h8" />
      </>
    ),
    reset: (
      <>
        <path d="M3 12a9 9 0 1 0 3-6.7" />
        <path d="M3 4v6h6" />
      </>
    ),
    mirror: (
      <>
        <path d="M12 3v18" />
        <path d="M4 7h5v10H4z" />
        <path d="M15 7h5v10h-5z" />
      </>
    ),
    minimal: (
      <>
        <rect x="4" y="5" width="16" height="14" rx="3" />
        <path d="M8 10h8" />
        <path d="M8 14h5" />
      </>
    ),
    close: (
      <>
        <path d="M6 6l12 12" />
        <path d="M18 6 6 18" />
      </>
    ),
    import: (
      <>
        <path d="M12 3v12" />
        <path d="M7 10l5 5 5-5" />
        <path d="M5 21h14" />
      </>
    ),
    save: (
      <>
        <path d="M5 3h12l2 2v16H5z" />
        <path d="M8 3v6h8" />
        <path d="M8 17h8" />
      </>
    ),
    trash: (
      <>
        <path d="M4 7h16" />
        <path d="M10 11v6" />
        <path d="M14 11v6" />
        <path d="M6 7l1 14h10l1-14" />
        <path d="M9 7V4h6v3" />
      </>
    ),
  };

  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24">
      {paths[name]}
    </svg>
  );
};

export default function TeleprompterPanel({
  language,
  value,
  position,
  isDragging,
  frameWidth,
  sidebarAvoidanceRight = 0,
  microphoneDeviceId,
  onChange,
  onClose,
  onMouseDown,
}: TeleprompterPanelProps) {
  const copy = useMemo(() => getCopy(language), [language]);
  const panelRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const speechMicrophoneStreamRef = useRef<MediaStream | null>(null);
  const startRecognitionRef = useRef<() => void | Promise<void>>(() => undefined);
  const isListeningRef = useRef(false);
  const isPlayingRef = useRef(false);
  const currentWordIndexRef = useRef(-1);
  const resizeStartRef = useRef<{ y: number; height: number } | null>(null);
  const [settings, setSettings] = useState(() => readStoredSettings(language));
  const [savedScripts, setSavedScripts] = useState<SavedScript[]>(readStoredScripts);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<'idle' | 'listening' | 'unsupported' | 'error'>('idle');
  const [currentWordIndex, setCurrentWordIndex] = useState(-1);
  const [showEditor, setShowEditor] = useState(() => value.trim().length === 0);
  const [showLibrary, setShowLibrary] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [viewportSize, setViewportSize] = useState(() => ({
    width: typeof window === 'undefined' ? 1280 : window.innerWidth,
    height: typeof window === 'undefined' ? 720 : window.innerHeight,
  }));

  const scriptModel = useMemo(() => buildScriptModel(value), [value]);
  const desiredPanelWidth = useMemo(() => clamp(Math.round((frameWidth ?? 1280) * 0.32), 390, 560), [frameWidth]);
  const availableRight = Math.max(0, viewportSize.width - Math.max(0, sidebarAvoidanceRight));
  const panelWidth = clamp(
    desiredPanelWidth,
    320,
    Math.max(320, availableRight - 16),
  );
  const estimatedTime = useMemo(() => formatDuration(scriptModel.words.length, language), [language, scriptModel.words.length]);
  const progress = scriptModel.words.length > 0 && currentWordIndex >= 0
    ? Math.round(((currentWordIndex + 1) / scriptModel.words.length) * 100)
    : 0;
  const voiceAvailable = typeof window !== 'undefined' && getSpeechRecognitionConstructor() !== null;
  const safeLeft = clamp(position.x, 8, Math.max(8, availableRight - panelWidth - 8));
  const safeTop = clamp(position.y, 8, Math.max(8, viewportSize.height - 96));

  const panelStyle: PanelStyle = {
    left: `${safeLeft}px`,
    top: `${safeTop}px`,
    width: `${panelWidth}px`,
    '--smart-teleprompter-ui-alpha': `${settings.uiOpacity / 100}`,
    '--smart-teleprompter-text-alpha': `${settings.textOpacity / 100}`,
  };

  const updateSettings = useCallback(<Key extends keyof SmartTeleprompterSettings>(
    key: Key,
    nextValue: SmartTeleprompterSettings[Key],
  ) => {
    setSettings((current) => ({ ...current, [key]: nextValue }));
  }, []);

  const centerOnWord = useCallback((wordIndex: number, behavior: ScrollBehavior = 'smooth') => {
    const viewport = viewportRef.current;

    if (!viewport || wordIndex < 0) {
      return;
    }

    const target = viewport.querySelector<HTMLElement>(`[data-word-index="${wordIndex}"]`);

    if (!target) {
      return;
    }

    const viewportRect = viewport.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const anchorY = viewportRect.top + (viewportRect.height * settings.centerPadding) / 100;
    const nextTop = viewport.scrollTop + (targetRect.top + targetRect.height / 2 - anchorY);
    const maxTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight);

    viewport.scrollTo({
      top: clamp(nextTop, 0, maxTop),
      behavior,
    });
  }, [settings.centerPadding]);

  const setActiveWord = useCallback((wordIndex: number, behavior: ScrollBehavior = 'smooth') => {
    const nextIndex = clamp(wordIndex, 0, Math.max(0, scriptModel.words.length - 1));
    currentWordIndexRef.current = nextIndex;
    setCurrentWordIndex(nextIndex);
    window.requestAnimationFrame(() => centerOnWord(nextIndex, behavior));
  }, [centerOnWord, scriptModel.words.length]);

  const resetPosition = useCallback(() => {
    isPlayingRef.current = false;
    setIsPlaying(false);
    currentWordIndexRef.current = -1;
    setCurrentWordIndex(-1);

    if (viewportRef.current) {
      viewportRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, []);

  const tryAdvanceBySpeechTokens = useCallback((tokens: string[]) => {
    const candidates = tokens.filter(Boolean).slice(-8);

    if (!candidates.length) {
      return -1;
    }

    const normalizedWords = scriptModel.words.map((word) => word.normalized);
    const currentIndex = currentWordIndexRef.current;
    const searchStart = Math.max(0, currentIndex - 6);
    const idealStart = Math.max(0, currentIndex + 1);
    const searchEnd = Math.min(
      normalizedWords.length,
      Math.max(idealStart + settings.lookaheadWindow, idealStart + 34),
    );
    let bestIndex = -1;
    let bestScore = Number.NEGATIVE_INFINITY;

    for (let size = Math.min(8, candidates.length); size >= 2; size -= 1) {
      const sequence = candidates.slice(-size);

      for (let index = searchStart; index <= searchEnd - size; index += 1) {
        let score = size * 0.62;

        sequence.forEach((token, offset) => {
          const target = normalizedWords[index + offset];

          if (tokensEqual(target, token)) {
            score += 3;
          } else if (tokensSoftMatch(target, token)) {
            score += 1.55;
          } else {
            score -= 0.8;
          }
        });

        const jumpDistance = Math.abs(index - idealStart);
        score -= Math.min(2.6, jumpDistance * 0.08);

        if (index < currentIndex - 2) {
          score -= 2.5;
        }

        if (score > bestScore) {
          bestScore = score;
          bestIndex = index + size - 1;
        }
      }
    }

    const lastToken = candidates[candidates.length - 1];
    const bestThreshold = Math.max(4.2, Math.min(8, candidates.length) * 1.8);

    if (bestIndex >= 0 && bestScore >= bestThreshold) {
      return bestIndex;
    }

    if (/^[\u3400-\u9fff]$/.test(lastToken)) {
      return -1;
    }

    const softEnd = Math.min(searchEnd, idealStart + 5);

    for (let index = idealStart; index < softEnd; index += 1) {
      if (tokensEqual(normalizedWords[index], lastToken)) {
        return index;
      }
    }

    for (let index = idealStart; index < softEnd; index += 1) {
      if (tokensSoftMatch(normalizedWords[index], lastToken)) {
        return index;
      }
    }

    return -1;
  }, [scriptModel.words, settings.lookaheadWindow]);

  const handleSpeechResult = useCallback((event: SpeechRecognitionEventLike) => {
    if (!isPlayingRef.current || !settings.voiceFollow) {
      return;
    }

    let transcript = '';

    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      transcript += ` ${event.results[index]?.[0]?.transcript ?? ''}`;
    }

    const speechTokens = tokenizeSpeech(transcript).slice(-MAX_SPEECH_TOKENS);
    const nextIndex = tryAdvanceBySpeechTokens(speechTokens);

    if (nextIndex >= 0) {
      setActiveWord(nextIndex, 'smooth');
    }
  }, [setActiveWord, settings.voiceFollow, tryAdvanceBySpeechTokens]);

  const hardStopRecognition = useCallback(() => {
    const recognition = recognitionRef.current;

    if (recognition) {
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;

      try {
        recognition.abort?.();
      } catch {
        try {
          recognition.stop();
        } catch {
          // Ignore browser-specific microphone teardown errors.
        }
      }
    }

    recognitionRef.current = null;
    speechMicrophoneStreamRef.current?.getTracks().forEach((track) => track.stop());
    speechMicrophoneStreamRef.current = null;
  }, []);

  const prepareSpeechMicrophone = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('getUserMedia is not supported');
    }

    speechMicrophoneStreamRef.current?.getTracks().forEach((track) => track.stop());
    speechMicrophoneStreamRef.current = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: microphoneDeviceId ? { exact: microphoneDeviceId } : undefined,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
  }, [microphoneDeviceId]);

  const startRecognition = useCallback(async () => {
    const Recognition = getSpeechRecognitionConstructor();

    if (!Recognition) {
      setVoiceStatus('unsupported');
      isPlayingRef.current = false;
      setIsPlaying(false);
      setIsListening(false);
      isListeningRef.current = false;
      return;
    }

    hardStopRecognition();

    try {
      await prepareSpeechMicrophone();
    } catch {
      setVoiceStatus('error');
      isPlayingRef.current = false;
      setIsPlaying(false);
      setIsListening(false);
      isListeningRef.current = false;
      return;
    }

    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = settings.speechLanguage;
    recognition.onresult = handleSpeechResult;
    recognition.onerror = () => {
      setVoiceStatus('error');
      isPlayingRef.current = false;
      setIsPlaying(false);
      setIsListening(false);
      isListeningRef.current = false;
      hardStopRecognition();
    };
    recognition.onend = () => {
      if (isListeningRef.current && isPlayingRef.current) {
        window.setTimeout(() => {
          void startRecognitionRef.current();
        }, 240);
      } else {
        setVoiceStatus('idle');
      }
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
      setVoiceStatus('listening');
    } catch {
      setVoiceStatus('error');
      isPlayingRef.current = false;
      setIsPlaying(false);
      setIsListening(false);
      isListeningRef.current = false;
      speechMicrophoneStreamRef.current?.getTracks().forEach((track) => track.stop());
      speechMicrophoneStreamRef.current = null;
    }
  }, [handleSpeechResult, hardStopRecognition, prepareSpeechMicrophone, settings.speechLanguage]);

  const stopVoiceFollowing = useCallback(() => {
    isListeningRef.current = false;
    setIsListening(false);
    setVoiceStatus('idle');
    hardStopRecognition();
  }, [hardStopRecognition]);

  const startVoiceFollowing = useCallback(() => {
    if (!voiceAvailable) {
      setVoiceStatus('unsupported');
      isPlayingRef.current = false;
      setIsPlaying(false);
      return;
    }

    isListeningRef.current = true;
    setIsListening(true);
    void startRecognitionRef.current();
  }, [voiceAvailable]);

  const toggleVoiceFollow = useCallback(() => {
    const nextVoiceFollow = !settings.voiceFollow;

    if (nextVoiceFollow && !voiceAvailable) {
      setVoiceStatus('unsupported');
      return;
    }

    updateSettings('voiceFollow', nextVoiceFollow);

    if (!nextVoiceFollow) {
      if (isListeningRef.current) {
        stopVoiceFollowing();
      }
      return;
    }

    setVoiceStatus('idle');

    if (isPlayingRef.current) {
      startVoiceFollowing();
    }
  }, [settings.voiceFollow, startVoiceFollowing, stopVoiceFollowing, updateSettings, voiceAvailable]);

  const toggleAutoPlay = useCallback(() => {
    if (!value.trim()) {
      setShowEditor(true);
      return;
    }

    if (isPlayingRef.current) {
      isPlayingRef.current = false;
      setIsPlaying(false);
      if (isListeningRef.current) {
        stopVoiceFollowing();
      }
      return;
    }

    if (currentWordIndexRef.current < 0 && scriptModel.words.length > 0) {
      setActiveWord(0, 'auto');
    }

    setVoiceStatus('idle');
    isPlayingRef.current = true;
    setIsPlaying(true);

    if (settings.voiceFollow) {
      startVoiceFollowing();
    }
  }, [scriptModel.words.length, setActiveWord, settings.voiceFollow, startVoiceFollowing, stopVoiceFollowing, value]);

  const saveScripts = useCallback((scripts: SavedScript[]) => {
    setSavedScripts(scripts);

    try {
      window.localStorage.setItem(SCRIPTS_STORAGE_KEY, JSON.stringify(scripts));
    } catch {
      // Storage is optional; the current script still stays in the editor.
    }
  }, []);

  const saveCurrentScript = useCallback(() => {
    if (!value.trim()) {
      setShowEditor(true);
      return;
    }

    const script: SavedScript = {
      id: createId(),
      title: titleFromScript(value, language),
      body: value,
      language: settings.speechLanguage,
      updatedAt: Date.now(),
    };

    saveScripts([script, ...savedScripts].slice(0, MAX_SCRIPTS));
    setShowLibrary(true);
  }, [language, savedScripts, saveScripts, settings.speechLanguage, value]);

  const loadScript = useCallback((script: SavedScript) => {
    onChange(script.body);
    updateSettings('speechLanguage', script.language);
    resetPosition();
    setShowEditor(false);
    setShowLibrary(false);
  }, [onChange, resetPosition, updateSettings]);

  const deleteScript = useCallback((scriptId: string) => {
    saveScripts(savedScripts.filter((script) => script.id !== scriptId));
  }, [savedScripts, saveScripts]);

  const handleFileImport = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    try {
      const ext = file.name.split('.').pop()?.toLowerCase();

      if (ext === 'txt' || ext === 'md' || ext === 'markdown') {
        const body = await file.text();
        onChange(body);
        resetPosition();
        setShowEditor(true);
      }
    } finally {
      event.target.value = '';
    }
  }, [onChange, resetPosition]);

  const handleResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeStartRef.current = {
      y: event.clientY,
      height: settings.panelHeight,
    };
  }, [settings.panelHeight]);

  const handleResizeMove = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    const start = resizeStartRef.current;

    if (!start) {
      return;
    }

    updateSettings('panelHeight', clamp(start.height + (event.clientY - start.y), 210, 560));
  }, [updateSettings]);

  const handleResizeEnd = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    if (resizeStartRef.current) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }

    resizeStartRef.current = null;
  }, []);

  useEffect(() => {
    startRecognitionRef.current = startRecognition;
  }, [startRecognition]);

  useEffect(() => {
    if (!isListeningRef.current || !isPlayingRef.current) {
      return;
    }

    hardStopRecognition();
    void startRecognitionRef.current();
  }, [hardStopRecognition, microphoneDeviceId]);

  useEffect(() => {
    isListeningRef.current = isListening;
  }, [isListening]);

  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  useEffect(() => {
    currentWordIndexRef.current = currentWordIndex;
  }, [currentWordIndex]);

  useEffect(() => {
    if (!isPlaying && isListeningRef.current) {
      stopVoiceFollowing();
    }
  }, [isPlaying, stopVoiceFollowing]);

  useEffect(() => {
    const updateViewportSize = () => {
      setViewportSize({
        width: window.innerWidth,
        height: window.innerHeight,
      });
    };

    updateViewportSize();
    window.addEventListener('resize', updateViewportSize);

    return () => window.removeEventListener('resize', updateViewportSize);
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Browser storage can be disabled; the feature still works for this session.
    }
  }, [settings]);

  useEffect(() => {
    if (!isPlaying || isListening || settings.voiceFollow || scriptModel.words.length === 0) {
      return undefined;
    }

    let animationFrame = 0;
    let lastTick = performance.now();
    const intervalMs = 1320 - (settings.scrollSpeed / 200) * 1050;

    const step = (timestamp: number) => {
      if (timestamp - lastTick >= intervalMs) {
        const current = currentWordIndexRef.current < 0 ? 0 : currentWordIndexRef.current;
        const next = current + 1;

        if (next >= scriptModel.words.length) {
          isPlayingRef.current = false;
          setIsPlaying(false);
          return;
        }

        setActiveWord(next, 'smooth');
        lastTick = timestamp;
      }

      animationFrame = window.requestAnimationFrame(step);
    };

    animationFrame = window.requestAnimationFrame(step);

    return () => {
      window.cancelAnimationFrame(animationFrame);
    };
  }, [isListening, isPlaying, scriptModel.words.length, setActiveWord, settings.scrollSpeed, settings.voiceFollow]);

  useEffect(() => () => {
    isListeningRef.current = false;
    hardStopRecognition();
  }, [hardStopRecognition]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || event.isComposing) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === 'v') {
        event.preventDefault();
        toggleVoiceFollow();
      } else if (key === 'p') {
        event.preventDefault();
        toggleAutoPlay();
      } else if (key === 'h') {
        event.preventDefault();
        updateSettings('highlight', !settings.highlight);
      } else if (key === 'r') {
        event.preventDefault();
        resetPosition();
      } else if (key === 's') {
        event.preventDefault();
        setShowEditor((current) => !current);
      } else if (key === 'b') {
        event.preventDefault();
        setShowLibrary((current) => !current);
      } else if (key === 'e') {
        event.preventDefault();
        setShowSettings((current) => !current);
      } else if (key === 'm') {
        event.preventDefault();
        updateSettings('mirror', !settings.mirror);
      } else if (key === 'l') {
        event.preventDefault();
        updateSettings('minimalMode', !settings.minimalMode);
      } else if (event.key === 'Escape') {
        setShowSettings(false);
        setShowLibrary(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [resetPosition, settings.highlight, settings.minimalMode, settings.mirror, toggleAutoPlay, toggleVoiceFollow, updateSettings]);

  const renderScript = () => {
    if (!value.trim()) {
      return <div className="smart-teleprompter-placeholder">{copy.placeholder}</div>;
    }

    const renderToken = (token: ScriptToken) => {
      const markClasses = [
        token.marks?.strong ? 'strong' : '',
        token.marks?.em ? 'em' : '',
        token.marks?.code ? 'code' : '',
        token.marks?.link ? 'link' : '',
        token.marks?.strike ? 'strike' : '',
      ].filter(Boolean);

      if (!token.normalized) {
        return (
          <span className={['smart-teleprompter-plain', ...markClasses].join(' ')} key={token.id}>
            {token.text}
          </span>
        );
      }

      const isActive = token.wordIndex === currentWordIndex;
      const isPast = token.wordIndex !== null && token.wordIndex < currentWordIndex;
      const shouldHighlight = settings.highlight && isActive;

      return (
        <span
          className={[
            'smart-teleprompter-word',
            ...markClasses,
            token.isCjk ? 'cjk' : '',
            isPast ? 'past' : '',
            shouldHighlight ? 'active' : '',
          ].filter(Boolean).join(' ')}
          data-word-index={token.wordIndex ?? undefined}
          key={token.id}
        >
          {token.text}
        </span>
      );
    };

    const renderTokens = (line: ScriptLine) => line.tokens.map(renderToken);

    return scriptModel.lines.map((line) => {
      const className = [
        'smart-teleprompter-line',
        `smart-teleprompter-line-${line.blockType}`,
        line.empty ? 'empty' : '',
        line.headingLevel ? `level-${line.headingLevel}` : '',
      ].filter(Boolean).join(' ');

      if (line.blockType === 'rule') {
        return <hr className={className} key={line.id} />;
      }

      if (line.blockType === 'heading') {
        return (
          <p aria-level={line.headingLevel ?? 2} className={className} key={line.id} role="heading">
            {renderTokens(line)}
          </p>
        );
      }

      if (line.blockType === 'list') {
        return (
          <p className={className} key={line.id}>
            <span className="smart-teleprompter-list-marker">{line.marker}</span>
            <span>{renderTokens(line)}</span>
          </p>
        );
      }

      if (line.blockType === 'quote') {
        return (
          <blockquote className={className} key={line.id}>
            {renderTokens(line)}
          </blockquote>
        );
      }

      if (line.blockType === 'code') {
        return (
          <pre className={className} key={line.id}>
            <code>{renderTokens(line)}</code>
          </pre>
        );
      }

      return (
        <p className={className} key={line.id}>
          {line.empty ? '\u00A0' : renderTokens(line)}
        </p>
      );
    });
  };

  const renderSettings = () => (
    <div className="smart-teleprompter-popover smart-teleprompter-settings" data-teleprompter-control="true">
      <label>
        <span>{copy.language}</span>
        <select
          value={settings.speechLanguage}
          onChange={(event) => updateSettings('speechLanguage', event.target.value)}
        >
          {speechLanguages.map((item) => (
            <option key={item.code} value={item.code}>
              {language === 'zh-CN' ? item.zh : item.en}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>{copy.fontSize}<strong>{settings.fontSize}px</strong></span>
        <input type="range" min="16" max="72" value={settings.fontSize} onChange={(event) => updateSettings('fontSize', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.lineHeight}<strong>{settings.lineHeight.toFixed(1)}</strong></span>
        <input type="range" min="1.1" max="2.3" step="0.1" value={settings.lineHeight} onChange={(event) => updateSettings('lineHeight', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.speed}<strong>{settings.scrollSpeed}</strong></span>
        <input type="range" min="10" max="200" value={settings.scrollSpeed} onChange={(event) => updateSettings('scrollSpeed', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.textOpacity}<strong>{settings.textOpacity}%</strong></span>
        <input type="range" min="35" max="100" value={settings.textOpacity} onChange={(event) => updateSettings('textOpacity', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.uiOpacity}<strong>{settings.uiOpacity}%</strong></span>
        <input type="range" min="0" max="92" value={settings.uiOpacity} onChange={(event) => updateSettings('uiOpacity', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.centerLine}<strong>{settings.centerPadding}%</strong></span>
        <input type="range" min="22" max="72" value={settings.centerPadding} onChange={(event) => updateSettings('centerPadding', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.sidePadding}<strong>{settings.sidePadding}px</strong></span>
        <input type="range" min="8" max="64" value={settings.sidePadding} onChange={(event) => updateSettings('sidePadding', Number(event.target.value))} />
      </label>

      <label>
        <span>{copy.lookahead}<strong>{settings.lookaheadWindow}</strong></span>
        <input type="range" min="6" max="28" value={settings.lookaheadWindow} onChange={(event) => updateSettings('lookaheadWindow', Number(event.target.value))} />
      </label>

      <div className="smart-teleprompter-segment" aria-label={copy.align}>
        {(['left', 'center', 'right'] as TextAlign[]).map((align) => (
          <button
            className={settings.align === align ? 'active' : ''}
            key={align}
            onClick={() => updateSettings('align', align)}
            type="button"
          >
            {align === 'left' ? copy.left : align === 'center' ? copy.center : copy.right}
          </button>
        ))}
      </div>
    </div>
  );

  const renderLibrary = () => (
    <div className="smart-teleprompter-popover smart-teleprompter-library" data-teleprompter-control="true">
      <div className="smart-teleprompter-popover-header">
        <strong>{copy.library}</strong>
        <button onClick={saveCurrentScript} type="button">
          <Icon name="save" />
          {copy.save}
        </button>
      </div>
      {savedScripts.length === 0 ? (
        <div className="smart-teleprompter-empty">{copy.noScripts}</div>
      ) : (
        <div className="smart-teleprompter-script-list">
          {savedScripts.map((script) => (
            <article className="smart-teleprompter-script-card" key={script.id}>
              <div>
                <strong>{script.title}</strong>
                <span>{new Date(script.updatedAt).toLocaleDateString()}</span>
              </div>
              <div className="smart-teleprompter-script-actions">
                <button onClick={() => loadScript(script)} type="button">{copy.load}</button>
                <button onClick={() => deleteScript(script.id)} type="button" aria-label={copy.delete}>
                  <Icon name="trash" />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div
      className={`teleprompter smart-teleprompter ${isDragging ? 'dragging' : ''} ${isPlaying ? 'playing' : ''} ${settings.minimalMode ? 'minimal' : ''}`}
      data-recording-overlay="true"
      ref={panelRef}
      style={panelStyle}
    >
      <div className="teleprompter-header smart-teleprompter-header" onMouseDown={onMouseDown}>
        <div className="smart-teleprompter-title">
          <Icon name="prompt" />
          <strong>{copy.title}</strong>
        </div>
        <div className="smart-teleprompter-actions">
          <button
            className={settings.minimalMode ? 'active' : ''}
            data-tooltip={settings.minimalMode ? copy.fullMode : copy.lightMode}
            onClick={() => {
              updateSettings('minimalMode', !settings.minimalMode);
              setShowSettings(false);
              setShowLibrary(false);
              setShowEditor(false);
            }}
            type="button"
          >
            <Icon name="minimal" />
          </button>
          <button className={showSettings ? 'active' : ''} data-tooltip={copy.settings} onClick={() => setShowSettings((current) => !current)} type="button">
            <Icon name="settings" />
          </button>
          <button className={showLibrary ? 'active' : ''} data-tooltip={copy.library} onClick={() => setShowLibrary((current) => !current)} type="button">
            <Icon name="library" />
          </button>
          <button aria-label={copy.close} data-tooltip={copy.close} onClick={onClose} type="button">
            <Icon name="close" />
          </button>
        </div>
      </div>

      <div className="smart-teleprompter-toolbar" data-teleprompter-control="true">
        <button className={`smart-teleprompter-primary ${isPlaying ? 'active' : ''}`} onClick={toggleAutoPlay} type="button">
          <Icon name={isPlaying ? 'pause' : 'play'} />
          {isPlaying ? copy.pause : copy.play}
        </button>
        <button
          className={`smart-teleprompter-soft ${settings.voiceFollow ? 'active' : ''} ${isListening ? 'listening' : ''}`}
          onClick={toggleVoiceFollow}
          type="button"
        >
          <span className="smart-teleprompter-dot" />
          {isListening ? copy.voiceOn : copy.voice}
        </button>
        <span className="smart-teleprompter-stat">{copy.estimated}: {estimatedTime}</span>
        <span className="smart-teleprompter-stat">{progress}%</span>
      </div>

      {voiceStatus === 'unsupported' && (
        <div className="smart-teleprompter-message">{copy.unsupported}</div>
      )}
      {voiceStatus === 'error' && (
        <div className="smart-teleprompter-message error">{copy.micError}</div>
      )}

      {!settings.minimalMode && showEditor ? (
        <div className="smart-teleprompter-editor" data-teleprompter-control="true">
          <textarea
            aria-label={copy.edit}
            onChange={(event) => onChange(event.target.value)}
            placeholder={copy.placeholder}
            value={value}
          />
          <div className="smart-teleprompter-editor-actions">
            <button onClick={() => fileInputRef.current?.click()} type="button">
              <Icon name="import" />
              {copy.import}
            </button>
            <button onClick={saveCurrentScript} type="button">
              <Icon name="save" />
              {copy.save}
            </button>
            <button onClick={() => onChange('')} type="button">{copy.clear}</button>
          </div>
          <input
            accept=".txt,.md,.markdown,text/plain,text/markdown"
            hidden
            onChange={handleFileImport}
            ref={fileInputRef}
            type="file"
          />
        </div>
      ) : (
        <div
          className="smart-teleprompter-script"
          ref={viewportRef}
          style={{
            fontSize: `${settings.fontSize}px`,
            lineHeight: settings.lineHeight,
            minHeight: `${settings.panelHeight}px`,
            maxHeight: `${settings.panelHeight}px`,
            paddingInline: `${settings.sidePadding}px`,
            textAlign: settings.align,
          }}
        >
          <div
            className="smart-teleprompter-script-inner"
            style={{
              transform: settings.mirror ? 'scaleX(-1)' : undefined,
            }}
          >
            {renderScript()}
            <div className="smart-teleprompter-end-space" />
          </div>
        </div>
      )}

      {settings.minimalMode && (
        <>
          <div className="smart-teleprompter-minimal-drag-edge edge-top" onMouseDown={onMouseDown} />
          <div className="smart-teleprompter-minimal-drag-edge edge-right" onMouseDown={onMouseDown} />
          <div className="smart-teleprompter-minimal-drag-edge edge-bottom" onMouseDown={onMouseDown} />
          <div className="smart-teleprompter-minimal-drag-edge edge-left" onMouseDown={onMouseDown} />
        </>
      )}

      <div className="smart-teleprompter-footer" data-teleprompter-control="true">
        <button className={showEditor ? 'active' : ''} onClick={() => setShowEditor((current) => !current)} type="button">
          <Icon name="script" />
          {copy.edit}
        </button>
        <button className={settings.highlight ? 'active' : ''} onClick={() => updateSettings('highlight', !settings.highlight)} type="button">
          {copy.highlight}
        </button>
        <button className={settings.mirror ? 'active' : ''} onClick={() => updateSettings('mirror', !settings.mirror)} type="button">
          <Icon name="mirror" />
          {copy.mirror}
        </button>
        <button onClick={resetPosition} type="button">
          <Icon name="reset" />
          {copy.reset}
        </button>
      </div>

      {settings.minimalMode && (
        <button
          aria-label={copy.fullMode}
          className="smart-teleprompter-minimal-restore"
          data-teleprompter-control="true"
          data-tooltip={copy.fullMode}
          onClick={() => updateSettings('minimalMode', false)}
          type="button"
        >
          <Icon name="minimal" />
        </button>
      )}

      {!settings.minimalMode && showSettings && renderSettings()}
      {!settings.minimalMode && showLibrary && renderLibrary()}

      <button
        aria-label={copy.resize}
        className="smart-teleprompter-resize"
        data-teleprompter-control="true"
        onPointerCancel={handleResizeEnd}
        onPointerDown={handleResizeStart}
        onPointerMove={handleResizeMove}
        onPointerUp={handleResizeEnd}
        type="button"
      >
        <span />
      </button>
    </div>
  );
}
