/**
 * Excalidraw Recorder - Record whiteboard + webcam videos
 *
 * Features:
 * - Customizable aspect ratios (16:9, 4:3, 9:16, 1:1, custom)
 * - Gradient backgrounds
 * - Adjustable webcam size
 * - Canvas padding
 * - Recording area overlay
 */

import { useState, useRef, useCallback, useEffect, useMemo, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import {
  CaptureUpdateAction,
  Excalidraw,
  MainMenu,
  TTDDialogTrigger,
  WelcomeScreen,
  convertToExcalidrawElements,
  isElementLink,
  sceneCoordsToViewportCoords,
  useHandleLibrary,
  viewportCoordsToSceneCoords,
} from '@excalidraw/excalidraw';
import { FilesetResolver, ImageSegmenter } from '@mediapipe/tasks-vision';
import '@excalidraw/excalidraw/index.css';
import WebcamBubble from './components/WebcamBubble';
import RecordingControls from './components/RecordingControls';
import SettingsPanel, {
  ASPECT_RATIOS,
  CAMERA_SIZE_MAX,
  CAMERA_SIZE_MIN,
  type SettingsPanelScope,
} from './components/SettingsPanel';
import MobileLanding from './components/MobileLanding';
import WelcomeModal from './components/WelcomeModal';
import LibraryBrowserPanel from './components/LibraryBrowserPanel';
import SlideStrip, { type SlideFrameItem } from './components/SlideStrip';
import GlobalTooltip from './components/GlobalTooltip';
import AboutDialog from './components/AboutDialog';
import GuideDialog from './components/GuideDialog';
import ExcalidrawHelpCloseButton from './components/ExcalidrawHelpCloseButton';
import TeleprompterPanel from './components/TeleprompterPanel';
import type { DevicePermissionState, DevicePermissionStatus, MediaDeviceOption, RecordingSettings } from './components/SettingsPanel';
import type { AppState, ExcalidrawImperativeAPI, ToolType } from '@excalidraw/excalidraw/types';
import type { ExcalidrawFrameElement, OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types';
import type { LibraryPersistenceAdapter } from '@excalidraw/excalidraw/data/library';
import {
  formatShortcut,
  getInitialShortcuts,
  isEditableShortcutTarget,
  matchesShortcut,
  saveShortcuts,
  type ShortcutActionId,
  type ShortcutSettings,
} from './shortcuts';
import { initAnalytics, trackPageView, trackRecordingStarted, trackRecordingCompleted, trackRecordingCancelled, trackTeleprompterUsed, trackSettingsChanged } from './utils/analytics';
import { WebCodecsRecorder, isWebCodecsSupported } from './utils/webCodecsRecorder';
import { normalizeRecordingDimensions, toEvenRecordingDimension } from './utils/recordingDimensions';
import { LANGUAGE_STORAGE_KEY, UI_TEXT, getExcalidrawLanguage, getInitialLanguage, type LanguageCode } from './i18n';
import './App.css';

// Initialize analytics once when module loads
initAnalytics();

const LibraryMenuIcon = () => (
  <svg className="excalicord-menu-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M4.5 5.75c0-.97.78-1.75 1.75-1.75h12.5c.41 0 .75.34.75.75v14.5c0 .41-.34.75-.75.75H6.25a1.75 1.75 0 0 1-1.75-1.75V5.75Z" />
    <path d="M4.5 17.75c0-.97.78-1.75 1.75-1.75H19.5" />
    <path d="M8 7.75h7.5" />
    <path d="M8 10.75h5.5" />
  </svg>
);

const ShortcutSettingsMenuIcon = () => (
  <svg className="excalicord-menu-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M5 6.5h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z" />
    <path d="M7 10h.01" />
    <path d="M10 10h.01" />
    <path d="M13 10h.01" />
    <path d="M16 10h1" />
    <path d="M7 14h6" />
    <path d="M16 14h1" />
  </svg>
);

const AboutMenuIcon = () => (
  <svg className="excalicord-menu-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />
    <path d="M12 10.75v5" />
    <path d="M12 7.5h.01" />
  </svg>
);

const LIBRARY_STORAGE_KEY = 'excalicord_library_items';
const LIBRARY_WINDOW_NAME_STORAGE_KEY = 'excalicord_library_window_name';
const APPEARANCE_STORAGE_KEY = 'excalicord_appearance_mode';
const TELEPROMPTER_TEXT_STORAGE_KEY = 'excalicord_teleprompter_text';
const EXCALIDRAW_LIBRARY_ORIGIN = 'https://libraries.excalidraw.com';
const EXCALIDRAW_LIBRARY_URL = `${EXCALIDRAW_LIBRARY_ORIGIN}/`;
const XIANGRUI_WEBSITE_URL = 'https://www.xiangruiai.com';
const MEDIAPIPE_WASM_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm';
const SELFIE_SEGMENTER_MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite';
type AppearanceMode = 'light' | 'dark' | 'system';
type ResolvedTheme = 'light' | 'dark';
type EditorPreferenceState = {
  gridModeEnabled: boolean;
  zenModeEnabled: boolean;
  viewModeEnabled: boolean;
  objectsSnapModeEnabled: boolean;
  toolLocked: boolean;
  arrowBindingEnabled: boolean;
  statsOpen: boolean;
};

type RecordingFrame = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type RecordingSizeSettings = Pick<RecordingSettings, 'aspectRatio' | 'customWidth' | 'customHeight'>;
type SlideFrame = Pick<ExcalidrawFrameElement, 'id' | 'x' | 'y' | 'width' | 'height' | 'name'>;
type PreferencesSubmenuPosition = {
  top: number;
  left: number;
};
type NativeDialogState = {
  title: string;
  message: string;
  detail?: string;
};
type ContextMenuTextReplacement = {
  label: string;
  shortcut?: string;
};

const DEFAULT_EDITOR_PREFERENCE_STATE: EditorPreferenceState = {
  gridModeEnabled: false,
  zenModeEnabled: false,
  viewModeEnabled: false,
  objectsSnapModeEnabled: false,
  toolLocked: false,
  arrowBindingEnabled: true,
  statsOpen: false,
};

const PREFERENCES_SUBMENU_WIDTH = 264;
const PREFERENCES_SUBMENU_HEIGHT = 278;
const PREFERENCES_SUBMENU_GAP = 8;
const PREFERENCES_SUBMENU_VIEWPORT_PADDING = 8;

const CONTEXT_MENU_ZH_REPLACEMENTS: Record<string, ContextMenuTextReplacement> = {
  Paste: { label: '粘贴', shortcut: '⌘V' },
  'Paste as plaintext': { label: '粘贴为纯文本', shortcut: '⌘⇧V' },
  'Paste charts': { label: '粘贴图表' },
  Cut: { label: '剪切', shortcut: '⌘X' },
  Copy: { label: '复制', shortcut: '⌘C' },
  Duplicate: { label: '复制副本', shortcut: '⌘D' },
  Delete: { label: '删除', shortcut: 'Delete' },
  'Copy to clipboard as PNG': { label: '复制为 PNG 到剪贴板', shortcut: '⇧⌥C' },
  'Copy to clipboard as SVG': { label: '复制为 SVG 到剪贴板' },
  'Copy to clipboard as text': { label: '复制文本到剪贴板' },
  'Copy source to clipboard': { label: '复制源内容到剪贴板' },
  'Select all': { label: '全部选中', shortcut: '⌘A' },
  'Copy styles': { label: '复制样式', shortcut: '⌘⌥C' },
  'Paste styles': { label: '粘贴样式', shortcut: '⌘⌥V' },
  'Bring forward': { label: '上移一层', shortcut: '⌘]' },
  'Send backward': { label: '下移一层', shortcut: '⌘[' },
  'Bring to front': { label: '置于顶层', shortcut: '⌘⇧]' },
  'Send to back': { label: '置于底层', shortcut: '⌘⇧[' },
  'Group selection': { label: '组合', shortcut: '⌘G' },
  'Ungroup selection': { label: '取消组合', shortcut: '⌘⇧G' },
  'Wrap selection in frame': { label: '用画框包裹选区' },
  'Add to library': { label: '添加到素材库中' },
  'Remove from library': { label: '从素材库移除' },
  Lock: { label: '锁定', shortcut: '⌘⇧L' },
  Unlock: { label: '解锁' },
  'Lock all': { label: '全部锁定' },
  'Unlock all': { label: '全部解锁' },
  'Create link': { label: '新建链接', shortcut: '⌘K' },
  'Add link': { label: '添加链接' },
  'Edit link': { label: '编辑链接' },
  'Edit embeddable link': { label: '编辑嵌入链接' },
  'Copy link to object': { label: '复制对象链接' },
  'Link to object': { label: '链接到对象' },
  'Flip horizontal': { label: '水平翻转', shortcut: '⇧H' },
  'Flip vertical': { label: '垂直翻转', shortcut: '⇧V' },
  '水平翻转': { label: '水平翻转', shortcut: '⇧H' },
  '垂直翻转': { label: '垂直翻转', shortcut: '⇧V' },
  '新建链接': { label: '新建链接', shortcut: '⌘K' },
  '复制对象链接': { label: '复制对象链接' },
  '添加到素材库中': { label: '添加到素材库中' },
  '锁定': { label: '锁定', shortcut: '⌘⇧L' },
  'Toggle grid': { label: '切换网格显示', shortcut: "⌘'" },
  'Snap to objects': { label: '吸附至对象', shortcut: '⌥S' },
  'Zen mode': { label: '禅模式', shortcut: '⌥Z' },
  'View mode': { label: '查看模式', shortcut: '⌥R' },
  'Canvas & Shape properties': { label: '画布与形状属性', shortcut: '⌥/' },
  'Arrow binding': { label: '箭头绑定' },
};

const getEditorPreferenceState = (appState: AppState): EditorPreferenceState => ({
  gridModeEnabled: appState.gridModeEnabled,
  zenModeEnabled: appState.zenModeEnabled,
  viewModeEnabled: appState.viewModeEnabled,
  objectsSnapModeEnabled: appState.objectsSnapModeEnabled,
  toolLocked: appState.activeTool.locked,
  arrowBindingEnabled: appState.isBindingEnabled,
  statsOpen: appState.stats.open,
});

const getIsWelcomeScreenActive = (appState: AppState, hasCanvasContent: boolean) => (
  !appState.isLoading &&
  appState.showWelcomeScreen &&
  appState.activeTool.type === 'selection' &&
  !appState.zenModeEnabled &&
  !hasCanvasContent
);

const getRecordingDimensionsForSettings = (settings: RecordingSizeSettings) => {
  if (settings.aspectRatio === 'custom') {
    return normalizeRecordingDimensions({
      width: settings.customWidth,
      height: settings.customHeight,
    });
  }

  const ratio = ASPECT_RATIOS.find((item) => item.id === settings.aspectRatio);

  return ratio
    ? normalizeRecordingDimensions({ width: ratio.width, height: ratio.height })
    : { width: 1920, height: 1080 };
};

const SLIDE_FRAME_GAP = 160;
const SLIDE_FRAME_MIN_WIDTH = 640;
const SLIDE_FRAME_DEFAULT_WIDTH = 960;
const SLIDE_FRAME_VIEWPORT_RATIO = 0.7;
const SLIDE_FRAME_ASPECT_TOLERANCE = 0.025;
const SLIDE_SWIPE_THRESHOLD = 80;
const SLIDE_SWIPE_COOLDOWN_MS = 420;
const SLIDE_SWIPE_RESET_MS = 180;

const isSlideFrameElement = (
  element: OrderedExcalidrawElement,
): element is OrderedExcalidrawElement & ExcalidrawFrameElement => (
  element.type === 'frame' && !element.isDeleted
);

const getSlideFramesFromElements = (elements: readonly OrderedExcalidrawElement[]): SlideFrame[] => (
  elements
    .filter(isSlideFrameElement)
    .map((element) => ({
      id: element.id,
      x: element.x,
      y: element.y,
      width: element.width,
      height: element.height,
      name: element.name ?? null,
    }))
    .sort((first, second) => first.x - second.x)
);

const areSlideFramesEqual = (first: readonly SlideFrame[], second: readonly SlideFrame[]) => (
  first.length === second.length &&
  first.every((frame, index) => {
    const otherFrame = second[index];
    return (
      otherFrame &&
      frame.id === otherFrame.id &&
      frame.name === otherFrame.name &&
      Math.round(frame.x) === Math.round(otherFrame.x) &&
      Math.round(frame.y) === Math.round(otherFrame.y) &&
      Math.round(frame.width) === Math.round(otherFrame.width) &&
      Math.round(frame.height) === Math.round(otherFrame.height)
    );
  })
);

const getSlideFrameLabel = (index: number, language: LanguageCode) => (
  language === 'zh-CN' ? `幻灯片 ${index}` : `Slide ${index}`
);

const getRecordingSizeFromSlideAspect = (frame: Pick<SlideFrame, 'width' | 'height'>) => {
  const frameAspect = frame.width / frame.height;
  const matchingRatio = ASPECT_RATIOS.find((ratio) => {
    if (ratio.id === 'custom') {
      return false;
    }

    const ratioAspect = ratio.width / ratio.height;
    return Math.abs(frameAspect - ratioAspect) / ratioAspect <= SLIDE_FRAME_ASPECT_TOLERANCE;
  });

  if (matchingRatio) {
    return {
      aspectRatio: matchingRatio.id,
      customWidth: matchingRatio.width,
      customHeight: matchingRatio.height,
    };
  }

  const customSize = frameAspect >= 1
    ? normalizeRecordingDimensions({
        width: 1920,
        height: 1920 / frameAspect,
      })
    : normalizeRecordingDimensions({
        width: 1920 * frameAspect,
        height: 1920,
      });

  return {
    aspectRatio: 'custom',
    customWidth: customSize.width,
    customHeight: customSize.height,
  };
};

const getSceneBounds = (elements: readonly OrderedExcalidrawElement[]) => {
  const drawableElements = elements.filter((element) => !element.isDeleted && element.type !== 'frame');

  if (drawableElements.length === 0) {
    return null;
  }

  return drawableElements.reduce(
    (bounds, element) => ({
      minX: Math.min(bounds.minX, element.x),
      minY: Math.min(bounds.minY, element.y),
      maxX: Math.max(bounds.maxX, element.x + element.width),
      maxY: Math.max(bounds.maxY, element.y + element.height),
    }),
    {
      minX: Number.POSITIVE_INFINITY,
      minY: Number.POSITIVE_INFINITY,
      maxX: Number.NEGATIVE_INFINITY,
      maxY: Number.NEGATIVE_INFINITY,
    },
  );
};

const getLanguageOptions = (language: LanguageCode): Array<{ code: LanguageCode; label: string }> => (
  language === 'zh-CN'
    ? [
        { code: 'zh-CN', label: '中文' },
        { code: 'en', label: '英文' },
      ]
    : [
        { code: 'zh-CN', label: 'Chinese' },
        { code: 'en', label: 'English' },
      ]
);

const getErrorDetail = (error: unknown) => {
  if (!error) {
    return '';
  }

  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
};

const formatChineseShortcut = (shortcut: string) => shortcut
  .replace(/CtrlOrCmd\+/g, '⌘')
  .replace(/Cmd\+Shift\+/g, '⌘⇧')
  .replace(/Shift\+Option\+/g, '⇧⌥')
  .replace(/Shift\+Alt\+/g, '⇧⌥')
  .replace(/Shift\+Cmd\+/g, '⇧⌘')
  .replace(/⌘Shift\+/g, '⌘⇧')
  .replace(/Cmd\+/g, '⌘')
  .replace(/Option\+/g, '⌥')
  .replace(/Alt\+/g, '⌥')
  .replace(/Ctrl\+/g, '⌃')
  .replace(/Shift\+/g, '⇧')
  .replace(/\s+/g, '');

const updateContextMenuScrollState = (menu: HTMLElement) => {
  const isScrollable = menu.scrollHeight > menu.clientHeight + 1;
  const isAtBottom = menu.scrollTop + menu.clientHeight >= menu.scrollHeight - 2;

  menu.classList.toggle('excalicord-context-menu-scrollable', isScrollable);
  menu.classList.toggle('excalicord-context-menu-at-bottom', !isScrollable || isAtBottom);
};

const syncContextMenuLanguage = (root: ParentNode, language: LanguageCode) => {
  root.querySelectorAll<HTMLElement>('.context-menu').forEach((menu) => {
    updateContextMenuScrollState(menu);

    if (!menu.dataset.excalicordScrollListener) {
      menu.dataset.excalicordScrollListener = 'true';
      menu.addEventListener('scroll', () => updateContextMenuScrollState(menu), { passive: true });
    }
  });

  if (language !== 'zh-CN') {
    return;
  }

  root.querySelectorAll<HTMLElement>('.context-menu-item').forEach((item) => {
    const labelElement = item.querySelector<HTMLElement>('.context-menu-item__label');
    const shortcutElement = item.querySelector<HTMLElement>('.context-menu-item__shortcut');
    const label = labelElement?.textContent?.replace(/\s+/g, ' ').trim();

    if (!labelElement || !label) {
      return;
    }

    const replacement = CONTEXT_MENU_ZH_REPLACEMENTS[label];

    if (replacement && labelElement.textContent !== replacement.label) {
      labelElement.textContent = replacement.label;
    }

    if (shortcutElement) {
      const nextShortcut = replacement?.shortcut || formatChineseShortcut(shortcutElement.textContent || '');

      if (nextShortcut && shortcutElement.textContent !== nextShortcut) {
        shortcutElement.textContent = nextShortcut;
      }
    }
  });
};

const isAppearanceMode = (value: string | null): value is AppearanceMode => {
  return value === 'light' || value === 'dark' || value === 'system';
};

const getSystemTheme = (): ResolvedTheme => {
  if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }

  return 'light';
};

const getInitialAppearanceMode = (): AppearanceMode => {
  try {
    const storedAppearance = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    return isAppearanceMode(storedAppearance) ? storedAppearance : 'system';
  } catch {
    return 'system';
  }
};

// Detect if user is on a mobile device
const isMobileDevice = () => {
  // Primary check: screen width (works in DevTools device mode)
  const isSmallScreen = window.innerWidth < 768;

  // Secondary check: mobile user agent
  const mobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

  // Show mobile landing if screen is small OR it's a mobile browser
  return isSmallScreen || mobileUA;
};

// Default settings
const DEFAULT_SETTINGS: RecordingSettings = {
  aspectRatio: '16:9',
  customWidth: 1920,
  customHeight: 1080,
  background: '#ffffff',
  backgroundId: 'none',
  backgroundType: 'solid',
  backgroundScale: 1,
  backgroundOffsetX: 0,
  backgroundOffsetY: 0,
  webcamSize: 180,
  webcamShape: 'circle',
  padding: 60,
  cornerRadius: 16,
  showCursor: true,
  cursorColor: '#ef4444',
  showCamera: true,
  useMicrophone: true,
  enableSound: true,
  cameraDeviceId: '',
  microphoneDeviceId: '',
  audioOutputDeviceId: '',
  cameraPersonCenter: false,
  cameraPortrait: false,
  cameraStudioLight: false,
  cameraEdgeLight: false,
  cameraEdgeLightMode: 'auto',
  cameraEdgeLightIntensity: 72,
  cameraEdgeLightSize: 84,
  cameraEdgeLightColor: 'warm',
  cameraReactions: false,
  cameraBackground: false,
  cameraBackgroundMode: 'blur',
  cameraMattingThreshold: 58,
  cameraMattingSoftness: 18,
  cameraDeskView: false,
  microphoneMode: 'standard',
};

const disableCameraEffects = (settings: RecordingSettings): RecordingSettings => {
  if (
    !settings.cameraPersonCenter &&
    !settings.cameraPortrait &&
    !settings.cameraStudioLight &&
    !settings.cameraEdgeLight &&
    !settings.cameraReactions &&
    !settings.cameraBackground &&
    !settings.cameraDeskView
  ) {
    return settings;
  }

  return {
    ...settings,
    cameraPersonCenter: false,
    cameraPortrait: false,
    cameraStudioLight: false,
    cameraEdgeLight: false,
    cameraReactions: false,
    cameraBackground: false,
    cameraDeskView: false,
  };
};

const WEBCAM_BUBBLE_MARGIN = 24;
const WEBCAM_BUBBLE_BOTTOM_OFFSET = 64;
const WEBCAM_BUBBLE_RIGHT_RATIO = 0.2;
const WEBCAM_BUBBLE_SIDEBAR_RIGHT_RATIO = 0.26;
const WEBCAM_QUICK_PANEL_WIDTH = 236;
const WEBCAM_QUICK_PANEL_HEIGHT = 164;
const WEBCAM_QUICK_PANEL_MARGIN = 16;
const EXPORT_WATERMARK_PREFIX = 'TO';
const EXPORT_WATERMARK_TEXT = '李祥瑞 · 万涂幻象';
const TELEPROMPTER_MIN_WIDTH = 360;
const TELEPROMPTER_MAX_WIDTH = 560;
const TELEPROMPTER_FRAME_MARGIN = 22;
const TELEPROMPTER_VIEWPORT_MARGIN = 16;
const TELEPROMPTER_MIN_VISIBLE_HEIGHT = 260;

const getBubbleViewport = () => {
  if (typeof window === 'undefined') {
    return { width: 1280, height: 720 };
  }

  const container = document.querySelector('.excalidraw-container');
  const rect = container?.getBoundingClientRect();

  return {
    width: rect?.width || window.innerWidth,
    height: rect?.height || window.innerHeight,
  };
};

const clampBubblePosition = (
  position: { x: number; y: number },
  size: number,
  rightInset = 0,
) => {
  const { width, height } = getBubbleViewport();
  const availableWidth = Math.max(size + WEBCAM_BUBBLE_MARGIN * 2, width - Math.max(0, rightInset));
  const maxX = Math.max(WEBCAM_BUBBLE_MARGIN, availableWidth - size - WEBCAM_BUBBLE_MARGIN);
  const maxY = Math.max(WEBCAM_BUBBLE_MARGIN, height - size - WEBCAM_BUBBLE_MARGIN);

  return {
    x: Math.round(Math.min(Math.max(position.x, WEBCAM_BUBBLE_MARGIN), maxX)),
    y: Math.round(Math.min(Math.max(position.y, WEBCAM_BUBBLE_MARGIN), maxY)),
  };
};

const getDefaultBubblePosition = (size: number, rightInset = 0) => {
  const { width, height } = getBubbleViewport();
  const availableWidth = Math.max(size + WEBCAM_BUBBLE_MARGIN * 2, width - Math.max(0, rightInset));
  const rightRatio = rightInset > 0 ? WEBCAM_BUBBLE_SIDEBAR_RIGHT_RATIO : WEBCAM_BUBBLE_RIGHT_RATIO;
  const rightOffset = Math.max(128, availableWidth * rightRatio);

  return clampBubblePosition({
    x: availableWidth - size - rightOffset,
    y: height - size - WEBCAM_BUBBLE_BOTTOM_OFFSET,
  }, size, rightInset);
};

const isLegacyBubblePosition = (position: { x: number; y: number }) => (
  position.x <= 32 && position.y <= 120
);

const getTeleprompterWidth = (frame?: RecordingFrame | null) => (
  frame ? Math.min(Math.max(frame.width - TELEPROMPTER_FRAME_MARGIN * 2, TELEPROMPTER_MIN_WIDTH), TELEPROMPTER_MAX_WIDTH) : TELEPROMPTER_MIN_WIDTH
);

const clampTeleprompterPosition = (
  position: { x: number; y: number },
  width: number,
  rightInset = 0,
) => ({
  x: Math.round(clampNumber(
    position.x,
    TELEPROMPTER_VIEWPORT_MARGIN,
    Math.max(
      TELEPROMPTER_VIEWPORT_MARGIN,
      window.innerWidth - Math.max(0, rightInset) - width - TELEPROMPTER_VIEWPORT_MARGIN,
    ),
  )),
  y: Math.round(clampNumber(
    position.y,
    TELEPROMPTER_VIEWPORT_MARGIN,
    Math.max(TELEPROMPTER_VIEWPORT_MARGIN, window.innerHeight - TELEPROMPTER_MIN_VISIBLE_HEIGHT),
  )),
});

const getDefaultTeleprompterPosition = (
  frame?: RecordingFrame | null,
  rightInset = 0,
) => {
  const width = getTeleprompterWidth(frame);

  if (frame) {
    return clampTeleprompterPosition({
      x: frame.x + frame.width / 2 - width / 2,
      y: frame.y + TELEPROMPTER_FRAME_MARGIN,
    }, width, rightInset);
  }

  if (rightInset > 0) {
    return clampTeleprompterPosition({
      x: 96,
      y: clampNumber(Math.round(window.innerHeight * 0.28), 190, 280),
    }, width, rightInset);
  }

  return clampTeleprompterPosition({
    x: window.innerWidth - width - 28,
    y: 80,
  }, width, rightInset);
};

const readStoredTeleprompterText = () => {
  try {
    return window.localStorage.getItem(TELEPROMPTER_TEXT_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
};

type CameraSourceRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type CameraFocusPoint = {
  x: number;
  y: number;
};

const clampNumber = (value: number, min: number, max: number) => (
  Math.min(Math.max(value, min), max)
);

type WatermarkBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const drawExportWatermark = (ctx: CanvasRenderingContext2D, bounds: WatermarkBounds) => {
  const scale = clampNumber(Math.min(bounds.width, bounds.height) / 1080, 0.72, 1.25);
  const fontFamily = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Noto Sans SC", "Segoe UI", sans-serif';
  const textFontSize = Math.round(20 * scale);
  const prefixFontSize = Math.round(12 * scale);
  const pillHeight = Math.round(44 * scale);
  const outerPaddingX = Math.round(12 * scale);
  const gap = Math.round(10 * scale);
  const margin = Math.round(28 * scale);

  ctx.save();
  ctx.textBaseline = 'middle';

  ctx.font = `650 ${textFontSize}px ${fontFamily}`;
  const textWidth = ctx.measureText(EXPORT_WATERMARK_TEXT).width;
  ctx.font = `750 ${prefixFontSize}px ${fontFamily}`;
  const prefixTextWidth = ctx.measureText(EXPORT_WATERMARK_PREFIX).width;

  const prefixWidth = Math.round(prefixTextWidth + 22 * scale);
  const prefixHeight = Math.round(24 * scale);
  const pillWidth = Math.round(outerPaddingX * 2 + prefixWidth + gap + textWidth + 4 * scale);
  const pillX = bounds.x + bounds.width - pillWidth - margin;
  const pillY = bounds.y + bounds.height - pillHeight - margin;
  const radius = Math.round(14 * scale);

  ctx.shadowColor = 'rgba(15, 23, 42, 0.18)';
  ctx.shadowBlur = Math.round(18 * scale);
  ctx.shadowOffsetY = Math.round(5 * scale);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.82)';
  ctx.beginPath();
  ctx.roundRect(pillX, pillY, pillWidth, pillHeight, radius);
  ctx.fill();

  ctx.shadowColor = 'transparent';
  ctx.lineWidth = Math.max(1, scale);
  ctx.strokeStyle = 'rgba(15, 23, 42, 0.10)';
  ctx.stroke();

  const prefixX = pillX + outerPaddingX;
  const prefixY = pillY + (pillHeight - prefixHeight) / 2;

  ctx.fillStyle = '#6c63e6';
  ctx.beginPath();
  ctx.roundRect(prefixX, prefixY, prefixWidth, prefixHeight, Math.round(9 * scale));
  ctx.fill();

  ctx.fillStyle = '#ffffff';
  ctx.font = `750 ${prefixFontSize}px ${fontFamily}`;
  ctx.textAlign = 'center';
  ctx.fillText(
    EXPORT_WATERMARK_PREFIX,
    prefixX + prefixWidth / 2,
    pillY + pillHeight / 2 + Math.round(0.5 * scale),
  );

  ctx.fillStyle = '#1f2933';
  ctx.font = `650 ${textFontSize}px ${fontFamily}`;
  ctx.textAlign = 'left';
  ctx.fillText(
    EXPORT_WATERMARK_TEXT,
    prefixX + prefixWidth + gap,
    pillY + pillHeight / 2 + Math.round(0.5 * scale),
  );

  ctx.restore();
};

const getStudioFilter = (settings: RecordingSettings) => (
  settings.cameraStudioLight ? 'brightness(1.12) contrast(1.1) saturate(1.06)' : 'none'
);

const getCameraSourceRect = (
  videoWidth: number,
  videoHeight: number,
  focus: CameraFocusPoint | null,
  zoom: number,
): CameraSourceRect => {
  const safeZoom = Math.max(1, zoom);
  const sourceWidth = videoWidth / safeZoom;
  const sourceHeight = videoHeight / safeZoom;
  const centerX = (focus?.x ?? 0.5) * videoWidth;
  const centerY = (focus?.y ?? 0.5) * videoHeight;

  return {
    x: clampNumber(centerX - sourceWidth / 2, 0, Math.max(0, videoWidth - sourceWidth)),
    y: clampNumber(centerY - sourceHeight / 2, 0, Math.max(0, videoHeight - sourceHeight)),
    width: sourceWidth,
    height: sourceHeight,
  };
};

const drawCameraSourceFrame = (
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  width: number,
  height: number,
  sourceRect: CameraSourceRect,
  filter: string,
) => {
  ctx.save();
  ctx.filter = filter;
  ctx.drawImage(
    video,
    sourceRect.x,
    sourceRect.y,
    sourceRect.width,
    sourceRect.height,
    0,
    0,
    width,
    height,
  );
  ctx.restore();
};

const drawCameraVirtualBackground = (
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  mode: RecordingSettings['cameraBackgroundMode'],
  width: number,
  height: number,
  sourceRect: CameraSourceRect,
) => {
  if (mode === 'blur') {
    ctx.save();
    ctx.filter = 'blur(18px) saturate(0.94) brightness(0.98)';
    ctx.drawImage(
      video,
      sourceRect.x,
      sourceRect.y,
      sourceRect.width,
      sourceRect.height,
      -24,
      -24,
      width + 48,
      height + 48,
    );
    ctx.restore();
    return;
  }

  if (mode === 'studio') {
    const gradient = ctx.createRadialGradient(width * 0.5, height * 0.34, width * 0.08, width * 0.5, height * 0.48, width * 0.72);
    gradient.addColorStop(0, '#44403c');
    gradient.addColorStop(1, '#171412');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    return;
  }

  if (mode === 'gradient') {
    const gradient = ctx.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, '#7c3aed');
    gradient.addColorStop(0.48, '#2563eb');
    gradient.addColorStop(1, '#06b6d4');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    return;
  }

  if (mode === 'accent') {
    const gradient = ctx.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, '#ede9fe');
    gradient.addColorStop(0.55, '#a78bfa');
    gradient.addColorStop(1, '#6c63e6');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    return;
  }

  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, '#fce7f3');
  gradient.addColorStop(0.55, '#dbeafe');
  gradient.addColorStop(1, '#fef3c7');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
};

const smoothstep = (edge0: number, edge1: number, value: number) => {
  const x = Math.min(1, Math.max(0, (value - edge0) / (edge1 - edge0)));
  return x * x * (3 - 2 * x);
};

const getMatteConfidence = (
  maskData: Uint8Array | Float32Array,
  index: number,
  options: {
    isConfidenceMask: boolean;
    invertConfidenceMask: boolean;
    personCategoryIndex: number;
    backgroundCategoryIndex: number;
  },
) => {
  if (options.isConfidenceMask) {
    const confidence = Number(maskData[index]);
    return options.invertConfidenceMask ? 1 - confidence : confidence;
  }

  const category = maskData[index];
  const isPerson = options.personCategoryIndex >= 0
    ? category === options.personCategoryIndex
    : options.backgroundCategoryIndex >= 0
      ? category !== options.backgroundCategoryIndex
      : category === 0;

  return isPerson ? 1 : 0;
};

const getMatteFocusPoint = (
  maskData: Uint8Array | Float32Array,
  maskWidth: number,
  maskHeight: number,
  options: {
    isConfidenceMask: boolean;
    invertConfidenceMask: boolean;
    personCategoryIndex: number;
    backgroundCategoryIndex: number;
    threshold: number;
  },
): CameraFocusPoint | null => {
  const threshold = Math.min(0.82, Math.max(0.28, options.threshold / 100));
  let minX = maskWidth;
  let minY = maskHeight;
  let maxX = 0;
  let maxY = 0;
  let hits = 0;

  for (let i = 0; i < maskData.length; i += 1) {
    if (getMatteConfidence(maskData, i, options) < threshold) {
      continue;
    }

    const x = i % maskWidth;
    const y = Math.floor(i / maskWidth);
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
    hits += 1;
  }

  if (hits < maskData.length * 0.015) {
    return null;
  }

  return {
    x: clampNumber((minX + maxX) / 2 / maskWidth, 0.15, 0.85),
    y: clampNumber((minY + maxY) / 2 / maskHeight, 0.18, 0.82),
  };
};

const drawPersonWithMatte = (
  outputCtx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  maskData: Uint8Array | Float32Array,
  maskWidth: number,
  maskHeight: number,
  width: number,
  height: number,
  options: {
    isConfidenceMask: boolean;
    invertConfidenceMask: boolean;
    personCategoryIndex: number;
    backgroundCategoryIndex: number;
    threshold: number;
    softness: number;
    previousAlphaMask: Float32Array | null;
    sourceRect: CameraSourceRect;
    filter: string;
  },
  maskCanvas: HTMLCanvasElement,
  personCanvas: HTMLCanvasElement,
): Float32Array | null => {
  maskCanvas.width = maskWidth;
  maskCanvas.height = maskHeight;
  personCanvas.width = width;
  personCanvas.height = height;

  const maskCtx = maskCanvas.getContext('2d');
  const personCtx = personCanvas.getContext('2d');

  if (!maskCtx || !personCtx) {
    outputCtx.drawImage(video, 0, 0, width, height);
    return null;
  }

  const maskImageData = maskCtx.createImageData(maskWidth, maskHeight);
  const nextAlphaMask = new Float32Array(maskData.length);
  const threshold = Math.min(0.82, Math.max(0.28, options.threshold / 100));
  const softness = Math.min(0.22, Math.max(0.018, options.softness / 200));
  const maskSourceRect = {
    x: options.sourceRect.x / video.videoWidth * maskWidth,
    y: options.sourceRect.y / video.videoHeight * maskHeight,
    width: options.sourceRect.width / video.videoWidth * maskWidth,
    height: options.sourceRect.height / video.videoHeight * maskHeight,
  };
  const previousAlphaMask = options.previousAlphaMask?.length === maskData.length
    ? options.previousAlphaMask
    : null;

  for (let i = 0; i < maskData.length; i += 1) {
    const confidence = getMatteConfidence(maskData, i, options);
    let alpha = smoothstep(threshold - softness, threshold + softness, confidence);

    if (previousAlphaMask) {
      alpha = alpha * 0.72 + previousAlphaMask[i] * 0.28;
    }

    if (alpha < 0.035) {
      alpha = 0;
    } else if (alpha > 0.985) {
      alpha = 1;
    }

    nextAlphaMask[i] = alpha;

    const offset = i * 4;
    maskImageData.data[offset] = 255;
    maskImageData.data[offset + 1] = 255;
    maskImageData.data[offset + 2] = 255;
    maskImageData.data[offset + 3] = Math.round(alpha * 255);
  }

  maskCtx.clearRect(0, 0, maskWidth, maskHeight);
  maskCtx.putImageData(maskImageData, 0, 0);
  personCtx.clearRect(0, 0, width, height);
  drawCameraSourceFrame(personCtx, video, width, height, options.sourceRect, options.filter);
  personCtx.globalCompositeOperation = 'destination-in';
  personCtx.imageSmoothingEnabled = true;
  personCtx.drawImage(
    maskCanvas,
    maskSourceRect.x,
    maskSourceRect.y,
    maskSourceRect.width,
    maskSourceRect.height,
    0,
    0,
    width,
    height,
  );
  personCtx.globalCompositeOperation = 'source-over';
  outputCtx.drawImage(personCanvas, 0, 0, width, height);

  return nextAlphaMask;
};

function App() {
  // Check for mobile device - show landing page instead of app
  const [isMobile] = useState(() => isMobileDevice());
  const [language, setLanguage] = useState<LanguageCode>(getInitialLanguage);
  const [appearanceMode, setAppearanceMode] = useState<AppearanceMode>(getInitialAppearanceMode);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme);
  const text = UI_TEXT[language];
  const editorTheme: ResolvedTheme = appearanceMode === 'system' ? systemTheme : appearanceMode;
  const languageOptions = getLanguageOptions(language);

  // Track page view on mount
  useEffect(() => {
    trackPageView(isMobile);
  }, [isMobile]);

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = text.documentTitle;
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    } catch {
      // Ignore storage failures. The current session still updates immediately.
    }
  }, [language, text.documentTitle]);

  useEffect(() => {
    try {
      window.localStorage.setItem(APPEARANCE_STORAGE_KEY, appearanceMode);
    } catch {
      // Ignore storage failures. Appearance still updates for this session.
    }
  }, [appearanceMode]);

  useEffect(() => {
    const mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)');

    if (!mediaQuery) {
      return;
    }

    const updateSystemTheme = () => {
      setSystemTheme(mediaQuery.matches ? 'dark' : 'light');
    };

    updateSystemTheme();
    mediaQuery.addEventListener('change', updateSystemTheme);

    return () => {
      mediaQuery.removeEventListener('change', updateSystemTheme);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.excalicordTheme = editorTheme;
    document.documentElement.style.colorScheme = editorTheme;
  }, [editorTheme]);

  useEffect(() => {
    try {
      let libraryWindowName = window.sessionStorage.getItem(LIBRARY_WINDOW_NAME_STORAGE_KEY);

      if (!libraryWindowName) {
        libraryWindowName = `excalicord${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
        window.sessionStorage.setItem(LIBRARY_WINDOW_NAME_STORAGE_KEY, libraryWindowName);
      }

      window.name = libraryWindowName;
    } catch {
      window.name = 'excalicord';
    }
  }, []);

  // State
  const [isRecording, setIsRecording] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false); // Preview mode before recording
  const [isPaused, setIsPaused] = useState(false); // Pause state during recording
  const [isConverting, setIsConverting] = useState(false);
  const [convertingMessage, setConvertingMessage] = useState('');
  const [webcamStream, setWebcamStream] = useState<MediaStream | null>(null);
  const [, setProcessedWebcamStream] = useState<MediaStream | null>(null);
  const [devicePermissions, setDevicePermissions] = useState<DevicePermissionStatus>({
    camera: 'checking',
    microphone: 'checking',
  });
  const [mediaDevices, setMediaDevices] = useState<MediaDeviceOption[]>([]);
  const [audioOutputSupported] = useState(() => (
    typeof HTMLMediaElement !== 'undefined' && 'setSinkId' in HTMLMediaElement.prototype
  ));
  const [bubblePosition, setBubblePosition] = useState(() => getDefaultBubblePosition(DEFAULT_SETTINGS.webcamSize));
  const [hasBubbleCustomPosition, setHasBubbleCustomPosition] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsScope, setSettingsScope] = useState<SettingsPanelScope>('recording');
  const [showLibraryBrowser, setShowLibraryBrowser] = useState(false);
  const [isLibraryBrowserPinned, setIsLibraryBrowserPinned] = useState(false);
  const [showAboutDialog, setShowAboutDialog] = useState(false);
  const [showGuideDialog, setShowGuideDialog] = useState(false);
  const [showWebcamQuickControls, setShowWebcamQuickControls] = useState(false);
  const [sidebarAvoidanceRight, setSidebarAvoidanceRight] = useState(0);
  const [hasCanvasContent, setHasCanvasContent] = useState(false);
  const [settings, setSettings] = useState<RecordingSettings>(() => disableCameraEffects(DEFAULT_SETTINGS));
  const [shortcuts, setShortcuts] = useState<ShortcutSettings>(() => getInitialShortcuts());
  const [recordingFrame, setRecordingFrame] = useState<RecordingFrame | null>(null);
  const [slideFrames, setSlideFrames] = useState<SlideFrame[]>([]);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(-1);
  const [showTeleprompter, setShowTeleprompter] = useState(false);
  const [teleprompterText, setTeleprompterText] = useState(readStoredTeleprompterText);
  const [teleprompterPosition, setTeleprompterPosition] = useState(() => getDefaultTeleprompterPosition(null));
  const [hasTeleprompterCustomPosition, setHasTeleprompterCustomPosition] = useState(false);
  const [isTeleprompterDragging, setIsTeleprompterDragging] = useState(false);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [excalidrawApi, setExcalidrawApi] = useState<ExcalidrawImperativeAPI | null>(null);
  const [editorPreferenceState, setEditorPreferenceState] = useState<EditorPreferenceState>(DEFAULT_EDITOR_PREFERENCE_STATE);
  const [showPreferencesSubmenu, setShowPreferencesSubmenu] = useState(false);
  const [preferencesSubmenuPosition, setPreferencesSubmenuPosition] = useState<PreferencesSubmenuPosition>({ top: 0, left: 0 });
  const [nativeDialog, setNativeDialog] = useState<NativeDialogState | null>(null);
  const [isWelcomeViewActive, setIsWelcomeViewActive] = useState(false);

  // Refs
  const appContainerRef = useRef<HTMLDivElement | null>(null);
  const webcamVideoRef = useRef<HTMLVideoElement | null>(null);
  const webcamStreamRef = useRef<MediaStream | null>(null);
  const rawCameraVideoRef = useRef<HTMLVideoElement | null>(null);
  const processedCameraCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const maskCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const personCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const previousAlphaMaskRef = useRef<Float32Array | null>(null);
  const processedWebcamStreamRef = useRef<MediaStream | null>(null);
  const imageSegmenterRef = useRef<ImageSegmenter | null>(null);
  const imageSegmenterPromiseRef = useRef<Promise<ImageSegmenter> | null>(null);
  const segmentationAnimationFrameRef = useRef<number | null>(null);
  const lastSegmentationFrameRef = useRef(0);
  const audioOutputProbeRef = useRef<HTMLAudioElement | null>(null);
  const compositeCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const webCodecsRecorderRef = useRef<WebCodecsRecorder | null>(null);

  // Refs for animation loop
  const isRecordingRef = useRef(false);
  const bubblePositionRef = useRef(bubblePosition);
  const settingsRef = useRef(settings);
  const recordingFrameRef = useRef<RecordingFrame | null>(null);
  const mousePositionRef = useRef({ x: 0, y: 0 });
  const backgroundImageRef = useRef<HTMLImageElement | null>(null);
  const backgroundImageLoadedRef = useRef(false);
  const recordingStartTimeRef = useRef<number | null>(null);
  const usedTeleprompterRef = useRef(false);
  const usedPauseRef = useRef(false);
  const slideSwipeDeltaRef = useRef(0);
  const slideSwipeLastNavigationRef = useRef(0);
  const slideSwipeResetTimeoutRef = useRef<number | null>(null);
  const isPreviewingRef = useRef(false);
  const currentSlideIndexRef = useRef(-1);
  const activeSlideIdRef = useRef<string | null>(null);

  useEffect(() => {
    const root = appContainerRef.current;

    if (!root) {
      return;
    }

    const updateThemeLabels = () => {
      root
        .querySelectorAll<HTMLElement>('.excalicord-theme-menu-item [aria-label]')
        .forEach((element) => {
          const label = element.getAttribute('aria-label') || '';
          let nextLabel = label;

          if (/Light mode|浅色模式/.test(label)) {
            nextLabel = language === 'zh-CN' ? '浅色模式 - ⇧⌥D' : 'Light mode - Shift+Option+D';
          } else if (/Dark mode|深色模式/.test(label)) {
            nextLabel = language === 'zh-CN' ? '深色模式 - ⇧⌥D' : 'Dark mode - Shift+Option+D';
          } else if (/System mode|跟随系统/.test(label)) {
            nextLabel = language === 'zh-CN' ? '跟随系统 - ⇧⌥D' : 'System mode - Shift+Option+D';
          }

          if (nextLabel !== label) {
            element.setAttribute('aria-label', nextLabel);
          }
        });
    };

    updateThemeLabels();

    const observer = new MutationObserver(updateThemeLabels);
    observer.observe(root, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['aria-label'],
    });

    return () => {
      observer.disconnect();
    };
  }, [language]);

  useEffect(() => {
    const root = document.body;

    let frameId: number | null = null;
    const timeoutIds: number[] = [];
    const scheduleSync = () => {
      if (frameId !== null) {
        return;
      }

      frameId = window.requestAnimationFrame(() => {
        frameId = null;
        syncContextMenuLanguage(root, language);
      });

      timeoutIds.push(window.setTimeout(() => {
        syncContextMenuLanguage(root, language);
      }, 40));
      timeoutIds.push(window.setTimeout(() => {
        syncContextMenuLanguage(root, language);
      }, 140));
    };

    scheduleSync();

    const observer = new MutationObserver(scheduleSync);
    observer.observe(root, {
      subtree: true,
      childList: true,
      characterData: true,
    });
    root.addEventListener('contextmenu', scheduleSync, true);
    root.addEventListener('pointerup', scheduleSync, true);

    return () => {
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
      }
      timeoutIds.forEach((timeoutId) => window.clearTimeout(timeoutId));
      observer.disconnect();
      root.removeEventListener('contextmenu', scheduleSync, true);
      root.removeEventListener('pointerup', scheduleSync, true);
    };
  }, [language]);

  useEffect(() => { isRecordingRef.current = isRecording; }, [isRecording]);
  useEffect(() => { isPreviewingRef.current = isPreviewing; }, [isPreviewing]);
  useEffect(() => { currentSlideIndexRef.current = currentSlideIndex; }, [currentSlideIndex]);
  useEffect(() => { bubblePositionRef.current = bubblePosition; }, [bubblePosition]);
  useEffect(() => { settingsRef.current = settings; }, [settings]);
  useEffect(() => { recordingFrameRef.current = recordingFrame; }, [recordingFrame]);

  useEffect(() => {
    try {
      window.localStorage.setItem(TELEPROMPTER_TEXT_STORAGE_KEY, teleprompterText);
    } catch {
      // Script autosave is best effort.
    }
  }, [teleprompterText]);

  useEffect(() => {
    if (!showTeleprompter || hasTeleprompterCustomPosition) {
      return;
    }

    setTeleprompterPosition(getDefaultTeleprompterPosition(recordingFrame, sidebarAvoidanceRight));
  }, [hasTeleprompterCustomPosition, recordingFrame, showTeleprompter, sidebarAvoidanceRight]);

  useEffect(() => {
    if (!excalidrawApi) {
      return;
    }

    const syncInitialCanvasState = () => {
      const appState = excalidrawApi.getAppState();
      const elements = excalidrawApi.getSceneElements() as readonly OrderedExcalidrawElement[];
      const nextHasCanvasContent = elements.some((element) => !element.isDeleted);
      const nextSlideFrames = getSlideFramesFromElements(elements);
      const nextIsWelcomeViewActive = getIsWelcomeScreenActive(appState, nextHasCanvasContent);

      setHasCanvasContent((currentHasCanvasContent) => (
        currentHasCanvasContent === nextHasCanvasContent ? currentHasCanvasContent : nextHasCanvasContent
      ));
      setSlideFrames((currentSlideFrames) => (
        areSlideFramesEqual(currentSlideFrames, nextSlideFrames) ? currentSlideFrames : nextSlideFrames
      ));
      setIsWelcomeViewActive((currentIsWelcomeViewActive) => (
        currentIsWelcomeViewActive === nextIsWelcomeViewActive
          ? currentIsWelcomeViewActive
          : nextIsWelcomeViewActive
      ));
    };

    const frameId = window.requestAnimationFrame(syncInitialCanvasState);
    const timeoutId = window.setTimeout(syncInitialCanvasState, 240);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.clearTimeout(timeoutId);
    };
  }, [excalidrawApi]);

  useEffect(() => {
    saveShortcuts(shortcuts);
  }, [shortcuts]);

  useEffect(() => {
    setSettings((currentSettings) => disableCameraEffects(currentSettings));
  }, []);

  const showNativeErrorDialog = useCallback((message: string, error?: unknown) => {
    const detail = getErrorDetail(error);

    setNativeDialog({
      title: text.alerts.errorTitle,
      message,
      detail: detail && detail !== message ? detail : undefined,
    });
  }, [text.alerts.errorTitle]);

  useEffect(() => {
    if (!nativeDialog) {
      return;
    }

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setNativeDialog(null);
      }
    };

    window.addEventListener('keydown', closeOnEscape);

    return () => {
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [nativeDialog]);

  useEffect(() => {
    const handleUnhandledError = (event: ErrorEvent) => {
      if (!event.error && !event.message) {
        return;
      }

      showNativeErrorDialog(text.alerts.unexpectedError, event.error || event.message);
    };

    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      showNativeErrorDialog(text.alerts.unexpectedError, event.reason);
    };

    window.addEventListener('error', handleUnhandledError);
    window.addEventListener('unhandledrejection', handleUnhandledRejection);

    return () => {
      window.removeEventListener('error', handleUnhandledError);
      window.removeEventListener('unhandledrejection', handleUnhandledRejection);
    };
  }, [showNativeErrorDialog, text.alerts.unexpectedError]);

  useEffect(() => {
    setBubblePosition((currentPosition) => (
      isLegacyBubblePosition(currentPosition) || !hasBubbleCustomPosition
        ? getDefaultBubblePosition(settings.webcamSize, sidebarAvoidanceRight)
        : clampBubblePosition(currentPosition, settings.webcamSize, sidebarAvoidanceRight)
    ));
  }, [hasBubbleCustomPosition, settings.webcamSize, sidebarAvoidanceRight, webcamStream]);

  useEffect(() => {
    const handleResize = () => {
      setBubblePosition((currentPosition) => (
        hasBubbleCustomPosition
          ? clampBubblePosition(currentPosition, settingsRef.current.webcamSize, sidebarAvoidanceRight)
          : getDefaultBubblePosition(settingsRef.current.webcamSize, sidebarAvoidanceRight)
      ));
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [hasBubbleCustomPosition, sidebarAvoidanceRight]);

  const normalizePermissionState = useCallback((state: PermissionState): DevicePermissionState => {
    if (state === 'granted' || state === 'prompt' || state === 'denied') {
      return state;
    }

    return 'unsupported';
  }, []);

  const refreshDevicePermissions = useCallback(async () => {
    if (!navigator.permissions?.query) {
      setDevicePermissions({ camera: 'unsupported', microphone: 'unsupported' });
      return;
    }

    const queryPermission = async (name: 'camera' | 'microphone') => {
      try {
        const permissionStatus = await navigator.permissions.query({ name: name as PermissionName });

        setDevicePermissions((current) => ({
          ...current,
          [name]: normalizePermissionState(permissionStatus.state),
        }));

        permissionStatus.onchange = () => {
          setDevicePermissions((current) => ({
            ...current,
            [name]: normalizePermissionState(permissionStatus.state),
          }));
        };
      } catch {
        setDevicePermissions((current) => ({
          ...current,
          [name]: 'unsupported',
        }));
      }
    };

    await Promise.all([
      queryPermission('camera'),
      queryPermission('microphone'),
    ]);
  }, [normalizePermissionState]);

  useEffect(() => {
    void refreshDevicePermissions();
  }, [refreshDevicePermissions]);

  const refreshMediaDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      setMediaDevices([]);
      return;
    }

    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setMediaDevices(devices.map((device) => ({
        deviceId: device.deviceId,
        groupId: device.groupId,
        kind: device.kind,
        label: device.label,
      })));
    } catch (error) {
      console.error('Failed to enumerate media devices:', error);
      setMediaDevices([]);
    }
  }, []);

  useEffect(() => {
    void refreshMediaDevices();

    if (!navigator.mediaDevices?.addEventListener) {
      return;
    }

    navigator.mediaDevices.addEventListener('devicechange', refreshMediaDevices);

    return () => {
      navigator.mediaDevices.removeEventListener('devicechange', refreshMediaDevices);
    };
  }, [refreshMediaDevices]);

  const setManagedWebcamStream = useCallback((stream: MediaStream | null) => {
    webcamStreamRef.current = stream;
    setWebcamStream(stream);
  }, []);

  const stopWebcamStream = useCallback(() => {
    webcamStreamRef.current?.getTracks().forEach((track) => track.stop());
    setManagedWebcamStream(null);
  }, [setManagedWebcamStream]);

  const requestMediaStream = useCallback(async (options?: { showAlert?: boolean }) => {
    const currentSettings = settingsRef.current;
    const needsVideo = currentSettings.showCamera;
    const needsAudio = currentSettings.useMicrophone;
    const videoDeviceId = currentSettings.cameraDeviceId;
    const audioDeviceId = currentSettings.microphoneDeviceId;

    if (!navigator.mediaDevices?.getUserMedia) {
      setDevicePermissions({
        camera: 'unsupported',
        microphone: 'unsupported',
      });
      if (options?.showAlert) {
        showNativeErrorDialog(text.alerts.cameraAccess);
      }
      return;
    }

    if (!needsVideo && !needsAudio) {
      stopWebcamStream();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: needsVideo ? {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          facingMode: videoDeviceId ? undefined : 'user',
          deviceId: videoDeviceId ? { exact: videoDeviceId } : undefined,
        } : false,
        audio: needsAudio ? {
          deviceId: audioDeviceId ? { exact: audioDeviceId } : undefined,
          echoCancellation: true,
          noiseSuppression: true,
        } : false,
      });

      webcamStreamRef.current?.getTracks().forEach((track) => track.stop());
      setManagedWebcamStream(stream);
      void refreshMediaDevices();
      setDevicePermissions((current) => ({
        camera: needsVideo ? 'granted' : current.camera,
        microphone: needsAudio ? 'granted' : current.microphone,
      }));
    } catch (err) {
      console.error('Failed to access media devices:', err);
      setDevicePermissions((current) => ({
        camera: needsVideo ? 'denied' : current.camera,
        microphone: needsAudio ? 'denied' : current.microphone,
      }));
      if (options?.showAlert) {
        showNativeErrorDialog(text.alerts.cameraAccess, err);
      }
    }
  }, [refreshMediaDevices, setManagedWebcamStream, showNativeErrorDialog, stopWebcamStream, text.alerts.cameraAccess]);

  useEffect(() => {
    if (settings.showCamera || settings.useMicrophone) {
      void requestMediaStream();
      return;
    }

    stopWebcamStream();
  }, [
    requestMediaStream,
    settings.cameraDeviceId,
    settings.microphoneDeviceId,
    settings.showCamera,
    settings.useMicrophone,
    stopWebcamStream,
  ]);

  useEffect(() => {
    return () => stopWebcamStream();
  }, [stopWebcamStream]);

  useEffect(() => {
    if (!audioOutputSupported || !settings.enableSound) {
      return;
    }

    if (!audioOutputProbeRef.current) {
      audioOutputProbeRef.current = new Audio();
      audioOutputProbeRef.current.muted = true;
    }

    const outputElement = audioOutputProbeRef.current as HTMLAudioElement & {
      setSinkId?: (sinkId: string) => Promise<void>;
    };

    void outputElement.setSinkId?.(settings.audioOutputDeviceId || 'default').catch((error) => {
      console.error('Failed to set audio output device:', error);
    });
  }, [audioOutputSupported, settings.audioOutputDeviceId, settings.enableSound]);

  const ensureImageSegmenter = useCallback(async () => {
    if (imageSegmenterRef.current) {
      return imageSegmenterRef.current;
    }

    if (!imageSegmenterPromiseRef.current) {
      imageSegmenterPromiseRef.current = (async () => {
        const vision = await FilesetResolver.forVisionTasks(MEDIAPIPE_WASM_URL);
        const segmenter = await ImageSegmenter.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: SELFIE_SEGMENTER_MODEL_URL,
            delegate: 'GPU',
          },
          runningMode: 'VIDEO',
          outputCategoryMask: true,
          outputConfidenceMasks: true,
        });

        imageSegmenterRef.current = segmenter;
        return segmenter;
      })();
    }

    return imageSegmenterPromiseRef.current;
  }, []);

  useEffect(() => {
    const cameraEngineEnabled = false;
    const shouldProcessCamera = cameraEngineEnabled && settings.showCamera && webcamStream?.getVideoTracks().some((track) => track.readyState === 'live');

    if (!shouldProcessCamera) {
      if (segmentationAnimationFrameRef.current) {
        cancelAnimationFrame(segmentationAnimationFrameRef.current);
        segmentationAnimationFrameRef.current = null;
      }
      processedWebcamStreamRef.current?.getTracks().forEach((track) => track.stop());
      processedWebcamStreamRef.current = null;
      previousAlphaMaskRef.current = null;
      setProcessedWebcamStream(null);
      return;
    }

    let isCancelled = false;
    let frameStream: MediaStream | null = null;

    const rawVideo = rawCameraVideoRef.current ?? document.createElement('video');
    rawCameraVideoRef.current = rawVideo;
    rawVideo.muted = true;
    rawVideo.playsInline = true;
    rawVideo.srcObject = webcamStream;
    void rawVideo.play().catch(() => undefined);

    const outputCanvas = processedCameraCanvasRef.current ?? document.createElement('canvas');
    const maskCanvas = maskCanvasRef.current ?? document.createElement('canvas');
    const personCanvas = personCanvasRef.current ?? document.createElement('canvas');
    processedCameraCanvasRef.current = outputCanvas;
    maskCanvasRef.current = maskCanvas;
    personCanvasRef.current = personCanvas;

    const outputCtx = outputCanvas.getContext('2d', { willReadFrequently: true });
    if (!outputCtx) {
      setProcessedWebcamStream(null);
      return;
    }

    frameStream = outputCanvas.captureStream(30);
    processedWebcamStreamRef.current?.getTracks().forEach((track) => track.stop());
    processedWebcamStreamRef.current = frameStream;
    setProcessedWebcamStream(frameStream);

    const paintFallbackFrame = (width: number, height: number) => {
      const sourceRect = getCameraSourceRect(rawVideo.videoWidth || width, rawVideo.videoHeight || height, null, 1);
      drawCameraSourceFrame(outputCtx, rawVideo, width, height, sourceRect, getStudioFilter(settingsRef.current));
    };

    const renderProcessedCamera = async (timestamp: number) => {
      if (isCancelled) {
        return;
      }

      const width = rawVideo.videoWidth || 1280;
      const height = rawVideo.videoHeight || 720;

      if (outputCanvas.width !== width || outputCanvas.height !== height) {
        outputCanvas.width = width;
        outputCanvas.height = height;
      }

      if (rawVideo.readyState < 2 || !rawVideo.videoWidth || !rawVideo.videoHeight) {
        outputCtx.fillStyle = '#1c1917';
        outputCtx.fillRect(0, 0, width, height);
        segmentationAnimationFrameRef.current = requestAnimationFrame(renderProcessedCamera);
        return;
      }

      if (timestamp - lastSegmentationFrameRef.current < 55) {
        segmentationAnimationFrameRef.current = requestAnimationFrame(renderProcessedCamera);
        return;
      }

      lastSegmentationFrameRef.current = timestamp;

      try {
        const currentSettings = settingsRef.current;
        const needsSegmentation = currentSettings.cameraBackground || currentSettings.cameraPortrait || currentSettings.cameraPersonCenter;
        const defaultSourceRect = getCameraSourceRect(
          rawVideo.videoWidth,
          rawVideo.videoHeight,
          null,
          currentSettings.cameraPersonCenter ? 1.12 : 1,
        );
        const studioFilter = getStudioFilter(currentSettings);

        if (!needsSegmentation) {
          previousAlphaMaskRef.current = null;
          drawCameraSourceFrame(outputCtx, rawVideo, width, height, defaultSourceRect, studioFilter);
          segmentationAnimationFrameRef.current = requestAnimationFrame(renderProcessedCamera);
          return;
        }

        const segmenter = await ensureImageSegmenter();

        if (isCancelled) {
          return;
        }

        const result = segmenter.segmentForVideo(rawVideo, timestamp);
        const categoryMask = result.categoryMask;
        const confidenceMasks = result.confidenceMasks || [];
        const labels = segmenter.getLabels().map((label) => label.toLowerCase());
        const backgroundCategoryIndex = labels.findIndex((label) => label.includes('background'));
        const detectedPersonCategoryIndex = labels.findIndex((label) => (
          label.includes('person') ||
          label.includes('human') ||
          label.includes('foreground')
        ));
        const personCategoryIndex = detectedPersonCategoryIndex >= 0
          ? detectedPersonCategoryIndex
          : backgroundCategoryIndex >= 0
            ? -1
            : confidenceMasks.length > 1
              ? 1
              : 0;
        let matteMask = personCategoryIndex >= 0
          ? confidenceMasks[personCategoryIndex]
          : undefined;
        let invertConfidenceMask = false;

        if (!matteMask && backgroundCategoryIndex >= 0) {
          matteMask = confidenceMasks[backgroundCategoryIndex];
          invertConfidenceMask = true;
        }

        if (!matteMask && confidenceMasks.length > 0) {
          matteMask = confidenceMasks[0];
        }

        const matteOptions = matteMask
          ? {
              isConfidenceMask: true,
              invertConfidenceMask,
              personCategoryIndex,
              backgroundCategoryIndex,
            }
          : categoryMask
            ? {
                isConfidenceMask: false,
                invertConfidenceMask: false,
                personCategoryIndex,
                backgroundCategoryIndex,
              }
            : null;
        const focusPoint = currentSettings.cameraPersonCenter && matteOptions
          ? getMatteFocusPoint(
            matteMask ? matteMask.getAsFloat32Array() : categoryMask!.getAsUint8Array(),
            matteMask?.width ?? categoryMask!.width,
            matteMask?.height ?? categoryMask!.height,
            {
              ...matteOptions,
              threshold: currentSettings.cameraMattingThreshold,
            },
          )
          : null;
        const sourceRect = getCameraSourceRect(
          rawVideo.videoWidth,
          rawVideo.videoHeight,
          focusPoint,
          currentSettings.cameraPersonCenter ? 1.16 : 1,
        );

        if (currentSettings.cameraBackground || currentSettings.cameraPortrait) {
          drawCameraVirtualBackground(
            outputCtx,
            rawVideo,
            currentSettings.cameraBackground ? currentSettings.cameraBackgroundMode : 'blur',
            width,
            height,
            sourceRect,
          );
        } else {
          drawCameraSourceFrame(outputCtx, rawVideo, width, height, sourceRect, studioFilter);
        }

        if (matteMask) {
          previousAlphaMaskRef.current = drawPersonWithMatte(
            outputCtx,
            rawVideo,
            matteMask.getAsFloat32Array(),
            matteMask.width,
            matteMask.height,
            width,
            height,
            {
              isConfidenceMask: true,
              invertConfidenceMask,
              personCategoryIndex,
              backgroundCategoryIndex,
              threshold: currentSettings.cameraMattingThreshold,
              softness: currentSettings.cameraMattingSoftness,
              previousAlphaMask: previousAlphaMaskRef.current,
              sourceRect,
              filter: studioFilter,
            },
            maskCanvas,
            personCanvas,
          );
        } else if (categoryMask) {
          previousAlphaMaskRef.current = drawPersonWithMatte(
            outputCtx,
            rawVideo,
            categoryMask.getAsUint8Array(),
            categoryMask.width,
            categoryMask.height,
            width,
            height,
            {
              isConfidenceMask: false,
              invertConfidenceMask: false,
              personCategoryIndex,
              backgroundCategoryIndex,
              threshold: currentSettings.cameraMattingThreshold,
              softness: currentSettings.cameraMattingSoftness,
              previousAlphaMask: previousAlphaMaskRef.current,
              sourceRect,
              filter: studioFilter,
            },
            maskCanvas,
            personCanvas,
          );
        } else {
          previousAlphaMaskRef.current = null;
          drawCameraSourceFrame(outputCtx, rawVideo, width, height, sourceRect, studioFilter);
        }

        result.close();
      } catch (error) {
        console.error('Failed to render virtual camera background:', error);
        paintFallbackFrame(width, height);
      }

      segmentationAnimationFrameRef.current = requestAnimationFrame(renderProcessedCamera);
    };

    segmentationAnimationFrameRef.current = requestAnimationFrame(renderProcessedCamera);

    return () => {
      isCancelled = true;
      if (segmentationAnimationFrameRef.current) {
        cancelAnimationFrame(segmentationAnimationFrameRef.current);
        segmentationAnimationFrameRef.current = null;
      }
      frameStream?.getTracks().forEach((track) => track.stop());
      if (processedWebcamStreamRef.current === frameStream) {
        processedWebcamStreamRef.current = null;
        previousAlphaMaskRef.current = null;
        setProcessedWebcamStream(null);
      }
    };
  }, [
    ensureImageSegmenter,
    settings.cameraBackground,
    settings.cameraBackgroundMode,
    settings.cameraPersonCenter,
    settings.cameraPortrait,
    settings.cameraStudioLight,
    settings.showCamera,
    webcamStream,
  ]);

  useEffect(() => {
    return () => {
      if (segmentationAnimationFrameRef.current) {
        cancelAnimationFrame(segmentationAnimationFrameRef.current);
      }
      processedWebcamStreamRef.current?.getTracks().forEach((track) => track.stop());
      imageSegmenterRef.current?.close();
    };
  }, []);

  const libraryPersistenceAdapter = useMemo<LibraryPersistenceAdapter>(() => ({
    load: () => {
      try {
        const storedLibrary = window.localStorage.getItem(LIBRARY_STORAGE_KEY);
        return storedLibrary ? { libraryItems: JSON.parse(storedLibrary) } : null;
      } catch (error) {
        console.error('Failed to load Excalidraw library', error);
        return null;
      }
    },
    save: ({ libraryItems }) => {
      try {
        window.localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(libraryItems));
      } catch (error) {
        console.error('Failed to save Excalidraw library', error);
        throw error;
      }
    },
  }), []);

  useHandleLibrary({
    excalidrawAPI: excalidrawApi,
    adapter: libraryPersistenceAdapter,
    validateLibraryUrl: (libraryUrl) => {
      try {
        const parsedUrl = new URL(libraryUrl);
        return parsedUrl.origin === EXCALIDRAW_LIBRARY_ORIGIN && parsedUrl.pathname.startsWith('/libraries/');
      } catch {
        return false;
      }
    },
  });

  const libraryBrowserUrl = useMemo(() => {
    const url = new URL(EXCALIDRAW_LIBRARY_URL);
    url.searchParams.set('target', window.name || '_blank');
    url.searchParams.set('referrer', `${window.location.origin}${window.location.pathname}`);
    url.searchParams.set('useHash', 'true');
    url.searchParams.set('token', excalidrawApi?.id || window.name || 'excalicord');
    url.searchParams.set('theme', editorTheme);
    url.searchParams.set('version', '2');
    url.searchParams.set('sort', 'default');
    return url.toString();
  }, [excalidrawApi?.id, editorTheme]);

  const openLibrary = useCallback(() => {
    setShowLibraryBrowser(true);
  }, []);

  const closeLibraryBrowser = useCallback(() => {
    setShowLibraryBrowser(false);
    setIsLibraryBrowserPinned(false);
  }, []);

  useEffect(() => {
    const interceptNativeLibraryBrowse = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const browseButton = target?.closest<HTMLAnchorElement>('.library-menu-browse-button');

      if (!browseButton) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      setShowLibraryBrowser(true);
    };

    document.addEventListener('click', interceptNativeLibraryBrowse, true);

    return () => {
      document.removeEventListener('click', interceptNativeLibraryBrowse, true);
    };
  }, []);

  const addPublicLibrary = useCallback(async (source: string) => {
    if (!excalidrawApi) {
      throw new Error('Excalidraw API is not ready');
    }

    const libraryResponse = await fetch(`${EXCALIDRAW_LIBRARY_ORIGIN}/libraries/${source}`);
    if (!libraryResponse.ok) {
      throw new Error(`Failed to load library: ${source}`);
    }

    await excalidrawApi.updateLibrary({
      libraryItems: await libraryResponse.blob(),
      merge: true,
      defaultStatus: 'published',
      openLibraryMenu: true,
    });
    if (!isLibraryBrowserPinned) {
      setShowLibraryBrowser(false);
    }
  }, [excalidrawApi, isLibraryBrowserPinned]);

  useEffect(() => {
    const closeOnLibraryImport = () => {
      if (
        !isLibraryBrowserPinned &&
        (window.location.hash.includes('addLibrary') || window.location.search.includes('addLibrary'))
      ) {
        setShowLibraryBrowser(false);
      }
    };

    closeOnLibraryImport();
    window.addEventListener('hashchange', closeOnLibraryImport);
    window.addEventListener('popstate', closeOnLibraryImport);

    return () => {
      window.removeEventListener('hashchange', closeOnLibraryImport);
      window.removeEventListener('popstate', closeOnLibraryImport);
    };
  }, [isLibraryBrowserPinned]);

  useEffect(() => {
    const updateSidebarAvoidance = () => {
      const sidebars = document.querySelectorAll<HTMLElement>('.library-browser-panel, .excalidraw-container .default-sidebar');
      let nextAvoidance = 0;

      sidebars.forEach((sidebar) => {
        const rect = sidebar.getBoundingClientRect();
        const style = window.getComputedStyle(sidebar);
        const isVisible =
          style.display !== 'none' &&
          style.visibility !== 'hidden' &&
          rect.width > 1 &&
          rect.height > 1 &&
          rect.left < window.innerWidth - 1 &&
          rect.right > 1;

        if (isVisible) {
          nextAvoidance = Math.max(nextAvoidance, Math.ceil(window.innerWidth - rect.left + 12));
        }
      });

      setSidebarAvoidanceRight((current) => (
        current === nextAvoidance ? current : nextAvoidance
      ));
    };

    updateSidebarAvoidance();

    const observer = new MutationObserver(updateSidebarAvoidance);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'aria-hidden'],
    });

    const intervalId = window.setInterval(updateSidebarAvoidance, 400);
    window.addEventListener('resize', updateSidebarAvoidance);

    return () => {
      observer.disconnect();
      window.clearInterval(intervalId);
      window.removeEventListener('resize', updateSidebarAvoidance);
    };
  }, []);

  // Track mouse position for cursor effect during recording
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      mousePositionRef.current = { x: e.clientX, y: e.clientY };
      // Also update state for live visual indicator (only during recording to avoid unnecessary renders)
      if (isRecordingRef.current) {
        setMousePosition({ x: e.clientX, y: e.clientY });
      }
    };
    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  // Load background image when settings change
  useEffect(() => {
    if (settings.backgroundType === 'image' && settings.background.includes('url(')) {
      // Extract URL from url() wrapper
      const urlMatch = settings.background.match(/url\(['"]?([^'"]+)['"]?\)/);
      if (urlMatch && urlMatch[1]) {
        backgroundImageLoadedRef.current = false;
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
          backgroundImageRef.current = img;
          backgroundImageLoadedRef.current = true;
        };
        img.onerror = () => {
          console.error('Failed to load background image');
          backgroundImageRef.current = null;
          backgroundImageLoadedRef.current = false;
        };
        img.src = urlMatch[1];
      }
    } else {
      backgroundImageRef.current = null;
      backgroundImageLoadedRef.current = false;
    }
  }, [settings.background, settings.backgroundType]);

  // Calculate recording frame dimensions to fit in viewport while maintaining aspect ratio.
  const calculateRecordingFrameForDimensions = useCallback((
    dimensions: { width: number; height: number },
    anchorFrame?: RecordingFrame | null,
  ): RecordingFrame | null => {
    const container = document.querySelector('.excalidraw-container');
    if (!container) return null;

    const containerRect = container.getBoundingClientRect();
    const { width: targetWidth, height: targetHeight } = dimensions;
    const targetAspect = targetWidth / targetHeight;

    // Calculate the largest frame that fits in the container with the target aspect ratio
    let frameWidth, frameHeight;
    const containerAspect = containerRect.width / containerRect.height;

    if (containerAspect > targetAspect) {
      // Container is wider - fit to height
      frameHeight = containerRect.height * 0.9; // 90% of container height
      frameWidth = frameHeight * targetAspect;
    } else {
      // Container is taller - fit to width
      frameWidth = containerRect.width * 0.9; // 90% of container width
      frameHeight = frameWidth / targetAspect;
    }

    const centerX = anchorFrame ? anchorFrame.x + anchorFrame.width / 2 : containerRect.width / 2;
    const centerY = anchorFrame ? anchorFrame.y + anchorFrame.height / 2 : containerRect.height / 2;
    const x = clampNumber(centerX - frameWidth / 2, 0, containerRect.width - frameWidth);
    const y = clampNumber(centerY - frameHeight / 2, 0, containerRect.height - frameHeight);

    return { x, y, width: frameWidth, height: frameHeight };
  }, []);

  const calculateRecordingFrame = useCallback(() => (
    calculateRecordingFrameForDimensions(
      getRecordingDimensionsForSettings(settingsRef.current),
      recordingFrameRef.current,
    )
  ), [calculateRecordingFrameForDimensions]);

  // Get recording dimensions from settings
  const getRecordingDimensions = useCallback(() => {
    return getRecordingDimensionsForSettings(settingsRef.current);
  }, []);

  // Parse gradient for canvas drawing
  const parseGradient = (ctx: CanvasRenderingContext2D, gradientStr: string, width: number, height: number) => {
    if (!gradientStr.includes('gradient')) {
      return gradientStr;
    }

    const match = gradientStr.match(/linear-gradient\((\d+)deg,\s*([^,]+)\s+\d+%,\s*([^)]+)\s+\d+%/);
    if (!match) return '#ffffff';

    const angle = parseInt(match[1]);
    const color1 = match[2].trim();
    const color2 = match[3].trim().split(' ')[0];

    const angleRad = (angle - 90) * Math.PI / 180;
    const x1 = width / 2 - Math.cos(angleRad) * width;
    const y1 = height / 2 - Math.sin(angleRad) * height;
    const x2 = width / 2 + Math.cos(angleRad) * width;
    const y2 = height / 2 + Math.sin(angleRad) * height;

    const gradient = ctx.createLinearGradient(x1, y1, x2, y2);
    gradient.addColorStop(0, color1);
    gradient.addColorStop(1, color2);
    return gradient;
  };

  // Render loop
  const renderCompositeFrame = useCallback(() => {
    const canvas = compositeCanvasRef.current;
    const ctx = canvas?.getContext('2d');
    const currentSettings = settingsRef.current;
    const frame = recordingFrameRef.current;

    if (!canvas || !ctx) {
      if (isRecordingRef.current) {
        animationFrameRef.current = requestAnimationFrame(renderCompositeFrame);
      }
      return;
    }

    const padding = currentSettings.padding;

    // Draw background (image, gradient, solid, or none)
    if (currentSettings.backgroundType === 'none' || currentSettings.background === 'none') {
      // No wallpaper - just clear to white
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    } else if (currentSettings.backgroundType === 'image' && backgroundImageRef.current && backgroundImageLoadedRef.current) {
      // Draw background image with the same cover, scale, and pan model as the settings preview.
      const img = backgroundImageRef.current;
      const imgAspect = img.width / img.height;
      const canvasAspect = canvas.width / canvas.height;
      const imageScale = Math.max(1, currentSettings.backgroundScale || 1);

      let drawWidth, drawHeight;
      if (imgAspect > canvasAspect) {
        // Image is wider - fit to height
        drawHeight = canvas.height * imageScale;
        drawWidth = drawHeight * imgAspect;
      } else {
        // Image is taller - fit to width
        drawWidth = canvas.width * imageScale;
        drawHeight = drawWidth / imgAspect;
      }

      const maxOffsetX = Math.max(0, (drawWidth - canvas.width) / 2);
      const maxOffsetY = Math.max(0, (drawHeight - canvas.height) / 2);
      const drawX = (canvas.width - drawWidth) / 2
        + (currentSettings.backgroundOffsetX / 100) * maxOffsetX;
      const drawY = (canvas.height - drawHeight) / 2
        + (currentSettings.backgroundOffsetY / 100) * maxOffsetY;
      ctx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
    } else {
      // Draw gradient or solid color
      const bgFill = parseGradient(ctx, currentSettings.background, canvas.width, canvas.height);
      ctx.fillStyle = bgFill;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    const cornerRadius = currentSettings.cornerRadius;
    const contentX = padding;
    const contentY = padding;
    const contentW = canvas.width - padding * 2;
    const contentH = canvas.height - padding * 2;

    // Helper function to draw rounded rectangle path
    const roundedRectPath = (x: number, y: number, w: number, h: number, r: number) => {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r);
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    };

    // Draw drop shadow for content area (only if there's padding)
    if (padding > 0) {
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.35)';
      ctx.shadowBlur = 80;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 20;
      ctx.fillStyle = '#ffffff';
      roundedRectPath(contentX, contentY, contentW, contentH, cornerRadius);
      ctx.fill();
      ctx.restore();
    }

    // Draw white content area with rounded corners
    ctx.fillStyle = '#ffffff';
    roundedRectPath(contentX, contentY, contentW, contentH, cornerRadius);
    ctx.fill();

    // Clip to rounded rectangle for Excalidraw content
    ctx.save();
    roundedRectPath(contentX, contentY, contentW, contentH, cornerRadius);
    ctx.clip();

    // Draw Excalidraw content - capture from the visible frame area
    const excalidrawWrapper = document.querySelector('.excalidraw');
    if (excalidrawWrapper && frame) {
      const canvases = excalidrawWrapper.querySelectorAll('canvas');

      canvases.forEach((srcCanvas) => {
        if (srcCanvas.width > 0 && srcCanvas.height > 0) {
          // Calculate source rectangle (what part of Excalidraw canvas to capture)
          // This maps the recording frame position to the source canvas
          const container = document.querySelector('.excalidraw-container');
          if (!container) return;

          const containerRect = container.getBoundingClientRect();

          // Scale factors between source canvas and container
          const scaleX = srcCanvas.width / containerRect.width;
          const scaleY = srcCanvas.height / containerRect.height;

          // Source rectangle in canvas coordinates
          const srcX = frame.x * scaleX;
          const srcY = frame.y * scaleY;
          const srcW = frame.width * scaleX;
          const srcH = frame.height * scaleY;

          // Destination is the recording canvas (minus padding)
          ctx.drawImage(srcCanvas, srcX, srcY, srcW, srcH, contentX, contentY, contentW, contentH);
        }
      });
    }

    ctx.restore(); // Remove clipping

    // Draw webcam bubble (only if camera is enabled)
    const videoEl = webcamVideoRef.current;
    const pos = bubblePositionRef.current;
    const size = currentSettings.webcamSize;

    if (currentSettings.showCamera && videoEl && videoEl.readyState >= 2 && videoEl.videoWidth > 0 && frame) {
      // Convert bubble position from screen to recording canvas coordinates
      const scaleX = (canvas.width - padding * 2) / frame.width;
      const scaleY = (canvas.height - padding * 2) / frame.height;

      // Bubble position relative to the recording frame
      const relX = pos.x - frame.x;
      const relY = pos.y - frame.y;

      const x = padding + relX * scaleX;
      const y = padding + relY * scaleY;
      const scaledSize = size * Math.min(scaleX, scaleY);

      // Crop webcam for aspect ratio
      const videoWidth = videoEl.videoWidth;
      const videoHeight = videoEl.videoHeight;
      const videoAspect = videoWidth / videoHeight;

      let srcX = 0, srcY = 0, srcW = videoWidth, srcH = videoHeight;
      if (videoAspect > 1) {
        srcW = videoHeight;
        srcX = (videoWidth - srcW) / 2;
      } else {
        srcH = videoWidth;
        srcY = (videoHeight - srcH) / 2;
      }

      // Draw webcam in the selected shape
      ctx.save();
      if (currentSettings.webcamShape === 'circle') {
        ctx.beginPath();
        ctx.arc(x + scaledSize/2, y + scaledSize/2, scaledSize/2, 0, Math.PI * 2);
        ctx.closePath();
      } else {
        roundedRectPath(x, y, scaledSize, scaledSize, Math.min(24, scaledSize * 0.16));
      }
      ctx.clip();

      ctx.translate(x + scaledSize, y);
      ctx.scale(-1, 1);
      ctx.drawImage(videoEl, srcX, srcY, srcW, srcH, 0, 0, scaledSize, scaledSize);
      ctx.restore();

    }

    // Draw cursor effect if enabled - minimalist transparent circle
    if (currentSettings.showCursor && frame) {
      const mousePos = mousePositionRef.current;

      // Check if mouse is within the recording frame
      if (mousePos.x >= frame.x && mousePos.x <= frame.x + frame.width &&
          mousePos.y >= frame.y && mousePos.y <= frame.y + frame.height) {

        // Convert mouse position to canvas coordinates
        const scaleX = contentW / frame.width;
        const scaleY = contentH / frame.height;
        const cursorX = contentX + (mousePos.x - frame.x) * scaleX;
        const cursorY = contentY + (mousePos.y - frame.y) * scaleY;

        // Simple transparent filled circle
        ctx.beginPath();
        ctx.arc(cursorX, cursorY, 18, 0, Math.PI * 2);
        ctx.fillStyle = currentSettings.cursorColor + '80'; // 50% opacity
        ctx.fill();
      }
    }

    drawExportWatermark(ctx, {
      x: contentX,
      y: contentY,
      width: contentW,
      height: contentH,
    });

    // Add frame to WebCodecs recorder if recording
    if (isRecordingRef.current && webCodecsRecorderRef.current && canvas) {
      webCodecsRecorderRef.current.addFrame(canvas);
    }

    if (isRecordingRef.current) {
      animationFrameRef.current = requestAnimationFrame(renderCompositeFrame);
    }
  }, []);

  // Helper function to snap bubble into a frame
  const snapBubbleToFrame = useCallback((frame: RecordingFrame) => {
    const size = settingsRef.current.webcamSize;
    const currentPos = bubblePositionRef.current;
    const constrainedX = Math.max(frame.x, Math.min(currentPos.x, frame.x + frame.width - size));
    const constrainedY = Math.max(frame.y, Math.min(currentPos.y, frame.y + frame.height - size));
    setBubblePosition({ x: constrainedX, y: constrainedY });
  }, []);

  const applyRecordingFrame = useCallback((frame: RecordingFrame) => {
    setRecordingFrame(frame);
    recordingFrameRef.current = frame;
    snapBubbleToFrame(frame);
  }, [snapBubbleToFrame]);

  const getSortedSlideElements = useCallback(() => {
    if (!excalidrawApi) {
      return [] as Array<OrderedExcalidrawElement & ExcalidrawFrameElement>;
    }

    return (excalidrawApi.getSceneElements() as readonly OrderedExcalidrawElement[])
      .filter(isSlideFrameElement)
      .sort((firstSlide, secondSlide) => firstSlide.x - secondSlide.x);
  }, [excalidrawApi]);

  const applyRecordingSizeFromSlideFrame = useCallback((slide: Pick<SlideFrame, 'width' | 'height'>) => {
    const nextSize = getRecordingSizeFromSlideAspect(slide);

    setSettings((currentSettings) => {
      if (
        currentSettings.aspectRatio === nextSize.aspectRatio &&
        currentSettings.customWidth === nextSize.customWidth &&
        currentSettings.customHeight === nextSize.customHeight
      ) {
        return currentSettings;
      }

      trackSettingsChanged('aspect_ratio', nextSize.aspectRatio);
      return {
        ...currentSettings,
        ...nextSize,
      };
    });
  }, []);

  const getViewportFrameFromSlide = useCallback((slide: Pick<SlideFrame, 'x' | 'y' | 'width' | 'height'>): RecordingFrame | null => {
    const container = document.querySelector<HTMLElement>('.excalidraw-container');
    const appState = excalidrawApi?.getAppState();

    if (!container || !appState) {
      return null;
    }

    const viewportState = {
      zoom: appState.zoom,
      offsetLeft: appState.offsetLeft,
      offsetTop: appState.offsetTop,
      scrollX: appState.scrollX,
      scrollY: appState.scrollY,
    };
    const topLeft = sceneCoordsToViewportCoords(
      { sceneX: slide.x, sceneY: slide.y },
      viewportState,
    );
    const bottomRight = sceneCoordsToViewportCoords(
      { sceneX: slide.x + slide.width, sceneY: slide.y + slide.height },
      viewportState,
    );
    const containerRect = container.getBoundingClientRect();

    return {
      x: topLeft.x - containerRect.left,
      y: topLeft.y - containerRect.top,
      width: bottomRight.x - topLeft.x,
      height: bottomRight.y - topLeft.y,
    };
  }, [excalidrawApi]);

  const getSceneFrameFromRecordingFrame = useCallback((frame: RecordingFrame): Pick<SlideFrame, 'x' | 'y' | 'width' | 'height'> | null => {
    const container = document.querySelector<HTMLElement>('.excalidraw-container');
    const appState = excalidrawApi?.getAppState();

    if (!container || !appState) {
      return null;
    }

    const containerRect = container.getBoundingClientRect();
    const viewportState = {
      zoom: appState.zoom,
      offsetLeft: appState.offsetLeft,
      offsetTop: appState.offsetTop,
      scrollX: appState.scrollX,
      scrollY: appState.scrollY,
    };
    const topLeft = viewportCoordsToSceneCoords(
      {
        clientX: containerRect.left + frame.x,
        clientY: containerRect.top + frame.y,
      },
      viewportState,
    );
    const bottomRight = viewportCoordsToSceneCoords(
      {
        clientX: containerRect.left + frame.x + frame.width,
        clientY: containerRect.top + frame.y + frame.height,
      },
      viewportState,
    );

    return {
      x: topLeft.x,
      y: topLeft.y,
      width: Math.max(1, bottomRight.x - topLeft.x),
      height: Math.max(1, bottomRight.y - topLeft.y),
    };
  }, [excalidrawApi]);

  const applySlideRecordingFrame = useCallback((slideId: string) => {
    if (activeSlideIdRef.current && activeSlideIdRef.current !== slideId) {
      return;
    }

    const slide = getSortedSlideElements().find((slideElement) => slideElement.id === slideId);

    if (!slide) {
      return;
    }

    applyRecordingSizeFromSlideFrame(slide);
    const viewportFrame = getViewportFrameFromSlide(slide);

    if (viewportFrame) {
      applyRecordingFrame(viewportFrame);
    }
  }, [applyRecordingFrame, applyRecordingSizeFromSlideFrame, getSortedSlideElements, getViewportFrameFromSlide]);

  const scheduleSlideRecordingFrame = useCallback((slideId: string, delay = 120) => {
    const run = () => applySlideRecordingFrame(slideId);

    requestAnimationFrame(() => {
      requestAnimationFrame(run);
    });
    window.setTimeout(run, delay);
    window.setTimeout(run, delay + 140);
  }, [applySlideRecordingFrame]);

  const syncActiveSlideRecordingFrame = useCallback(() => {
    const slideId = activeSlideIdRef.current;

    if (!slideId || (!isRecordingRef.current && !isPreviewingRef.current)) {
      return;
    }

    requestAnimationFrame(() => applySlideRecordingFrame(slideId));
  }, [applySlideRecordingFrame]);

  const goToSlide = useCallback((index: number, options?: { applyFrame?: boolean; animate?: boolean }) => {
    const slideElements = getSortedSlideElements();
    const slide = slideElements[index];

    if (!slide || !excalidrawApi) {
      return;
    }

    activeSlideIdRef.current = slide.id;
    currentSlideIndexRef.current = index;
    setCurrentSlideIndex(index);
    applyRecordingSizeFromSlideFrame(slide);

    const animate = options?.animate ?? !(isRecording || isPreviewing);
    excalidrawApi.scrollToContent(slide, {
      fitToViewport: true,
      viewportZoomFactor: 0.76,
      animate,
      duration: animate ? 220 : 0,
    });

    if (options?.applyFrame || isRecording || isPreviewing) {
      scheduleSlideRecordingFrame(slide.id, animate ? 260 : 70);
    }
  }, [
    applyRecordingSizeFromSlideFrame,
    excalidrawApi,
    getSortedSlideElements,
    isPreviewing,
    isRecording,
    scheduleSlideRecordingFrame,
  ]);

  const goToAdjacentSlide = useCallback((direction: 1 | -1) => {
    const slideElements = getSortedSlideElements();

    if (slideElements.length < 2) {
      return false;
    }

    const activeIndex = currentSlideIndexRef.current;
    const baseIndex = activeIndex >= 0
      ? activeIndex
      : direction > 0
        ? -1
        : slideElements.length;
    const nextIndex = Math.max(0, Math.min(slideElements.length - 1, baseIndex + direction));

    if (nextIndex === activeIndex) {
      return false;
    }

    goToSlide(nextIndex, { applyFrame: true, animate: false });
    return true;
  }, [getSortedSlideElements, goToSlide]);

  const addSlide = useCallback(() => {
    if (!excalidrawApi) {
      return;
    }

    const appState = excalidrawApi.getAppState();
    const elements = excalidrawApi.getSceneElements() as readonly OrderedExcalidrawElement[];
    const slides = getSlideFramesFromElements(elements);
    const dimensions = getRecordingDimensionsForSettings(settingsRef.current);
    const targetAspect = dimensions.width / dimensions.height;
    const lastSlide = slides.at(-1);
    const previewSceneFrame = !lastSlide && recordingFrameRef.current
      ? getSceneFrameFromRecordingFrame(recordingFrameRef.current)
      : null;

    let width = previewSceneFrame?.width ?? lastSlide?.width ?? SLIDE_FRAME_DEFAULT_WIDTH;
    let height = previewSceneFrame?.height ?? lastSlide?.height ?? width / targetAspect;
    let x = previewSceneFrame?.x ?? 0;
    let y = previewSceneFrame?.y ?? 0;

    if (lastSlide) {
      x = lastSlide.x + lastSlide.width + SLIDE_FRAME_GAP;
      y = lastSlide.y;
    } else if (!previewSceneFrame) {
      const contentBounds = getSceneBounds(elements);

      if (contentBounds) {
        const contentWidth = Math.max(1, contentBounds.maxX - contentBounds.minX);
        const contentHeight = Math.max(1, contentBounds.maxY - contentBounds.minY);
        const contentAspect = contentWidth / contentHeight;

        if (contentAspect > targetAspect) {
          width = Math.max(SLIDE_FRAME_MIN_WIDTH, contentWidth * 1.35);
          height = width / targetAspect;
        } else {
          height = Math.max(SLIDE_FRAME_MIN_WIDTH / targetAspect, contentHeight * 1.35);
          width = height * targetAspect;
        }

        x = (contentBounds.minX + contentBounds.maxX) / 2 - width / 2;
        y = (contentBounds.minY + contentBounds.maxY) / 2 - height / 2;
      } else {
        const container = document.querySelector<HTMLElement>('.excalidraw-container');
        const containerRect = container?.getBoundingClientRect();

        if (containerRect) {
          const center = viewportCoordsToSceneCoords(
            {
              clientX: containerRect.left + containerRect.width / 2,
              clientY: containerRect.top + containerRect.height / 2,
            },
            {
              zoom: appState.zoom,
              offsetLeft: appState.offsetLeft,
              offsetTop: appState.offsetTop,
              scrollX: appState.scrollX,
              scrollY: appState.scrollY,
            },
          );
          const visibleSceneWidth = containerRect.width / appState.zoom.value;
          const visibleSceneHeight = containerRect.height / appState.zoom.value;

          width = Math.max(
            SLIDE_FRAME_MIN_WIDTH,
            Math.min(SLIDE_FRAME_DEFAULT_WIDTH, visibleSceneWidth * SLIDE_FRAME_VIEWPORT_RATIO),
          );
          height = width / targetAspect;

          if (height > visibleSceneHeight * SLIDE_FRAME_VIEWPORT_RATIO) {
            height = Math.max(
              SLIDE_FRAME_MIN_WIDTH / targetAspect,
              visibleSceneHeight * SLIDE_FRAME_VIEWPORT_RATIO,
            );
            width = height * targetAspect;
          }

          x = center.x - width / 2;
          y = center.y - height / 2;
        }
      }
    }

    const nextSlideIndex = slides.length;
    const [frame] = convertToExcalidrawElements([
      {
        type: 'frame',
        x,
        y,
        width,
        height,
        name: getSlideFrameLabel(nextSlideIndex + 1, language),
        children: [],
      },
    ], { regenerateIds: true });

    excalidrawApi.updateScene({
      elements: [...elements, frame],
      captureUpdate: CaptureUpdateAction.IMMEDIATELY,
    });
    currentSlideIndexRef.current = nextSlideIndex;
    setCurrentSlideIndex(nextSlideIndex);
    window.setTimeout(() => {
      goToSlide(nextSlideIndex, {
        applyFrame: isPreviewing,
        animate: !isPreviewing,
      });
    }, 60);
  }, [excalidrawApi, getSceneFrameFromRecordingFrame, goToSlide, isPreviewing, language]);

  const deleteSlide = useCallback((index: number) => {
    if (!excalidrawApi) {
      return;
    }

    const slideElements = getSortedSlideElements();
    const slide = slideElements[index];

    if (!slide) {
      return;
    }

    const elements = excalidrawApi.getSceneElements() as readonly OrderedExcalidrawElement[];
    excalidrawApi.updateScene({
      elements: elements.map((element) => (
        element.id === slide.id ? { ...element, isDeleted: true } : element
      )),
      captureUpdate: CaptureUpdateAction.IMMEDIATELY,
    });

    const nextIndex = Math.min(Math.max(0, index - 1), slideElements.length - 2);
    currentSlideIndexRef.current = slideElements.length > 1 ? nextIndex : -1;
    activeSlideIdRef.current = slideElements.length > 1 ? slideElements[nextIndex]?.id ?? null : null;
    setCurrentSlideIndex(slideElements.length > 1 ? nextIndex : -1);

    if (slideElements.length > 1) {
      window.setTimeout(() => goToSlide(nextIndex), 80);
    }
  }, [excalidrawApi, getSortedSlideElements, goToSlide]);

  useEffect(() => {
    if (slideFrames.length < 2 || (!isPreviewing && !isRecording)) {
      return;
    }

    const handleSlideKeyDown = (event: KeyboardEvent) => {
      if (isEditableShortcutTarget(event.target)) {
        return;
      }

      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      goToAdjacentSlide(event.key === 'ArrowRight' ? 1 : -1);
    };

    window.addEventListener('keydown', handleSlideKeyDown, true);

    return () => {
      window.removeEventListener('keydown', handleSlideKeyDown, true);
    };
  }, [goToAdjacentSlide, isPreviewing, isRecording, slideFrames.length]);

  useEffect(() => {
    if (slideFrames.length < 2 || !isRecording) {
      return;
    }

    const resetSwipeDelta = () => {
      slideSwipeDeltaRef.current = 0;

      if (slideSwipeResetTimeoutRef.current !== null) {
        window.clearTimeout(slideSwipeResetTimeoutRef.current);
        slideSwipeResetTimeoutRef.current = null;
      }
    };

    const handleSlideWheel = (event: WheelEvent) => {
      if (
        nativeDialog ||
        showSettings ||
        showLibraryBrowser ||
        showAboutDialog ||
        showGuideDialog ||
        isEditableShortcutTarget(event.target)
      ) {
        return;
      }

      const absoluteDeltaX = Math.abs(event.deltaX);
      const absoluteDeltaY = Math.abs(event.deltaY);

      if (absoluteDeltaX < 1 || absoluteDeltaX < absoluteDeltaY * 1.15) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      const now = window.performance.now();

      if (now - slideSwipeLastNavigationRef.current < SLIDE_SWIPE_COOLDOWN_MS) {
        return;
      }

      slideSwipeDeltaRef.current += event.deltaX;

      if (slideSwipeResetTimeoutRef.current !== null) {
        window.clearTimeout(slideSwipeResetTimeoutRef.current);
      }

      slideSwipeResetTimeoutRef.current = window.setTimeout(resetSwipeDelta, SLIDE_SWIPE_RESET_MS);

      if (Math.abs(slideSwipeDeltaRef.current) < SLIDE_SWIPE_THRESHOLD) {
        return;
      }

      const direction = slideSwipeDeltaRef.current > 0 ? 1 : -1;

      if (goToAdjacentSlide(direction)) {
        slideSwipeLastNavigationRef.current = now;
      }

      resetSwipeDelta();
    };

    window.addEventListener('wheel', handleSlideWheel, { capture: true, passive: false });

    return () => {
      window.removeEventListener('wheel', handleSlideWheel, true);
      resetSwipeDelta();
    };
  }, [
    goToAdjacentSlide,
    isRecording,
    nativeDialog,
    showAboutDialog,
    showGuideDialog,
    showLibraryBrowser,
    showSettings,
    slideFrames.length,
  ]);

  // Enter preview mode - show frame for positioning before recording
  const enterPreviewMode = useCallback(() => {
    const slideElements = getSortedSlideElements();
    const slideIndex = currentSlideIndex >= 0 ? currentSlideIndex : 0;
    const slide = slideElements[slideIndex];

    if (slide) {
      setCurrentSlideIndex(slideIndex);
      setIsPreviewing(true);
      goToSlide(slideIndex, { applyFrame: true, animate: false });
      return;
    }

    const frame = calculateRecordingFrame();
    if (!frame) return;
    activeSlideIdRef.current = null;
    currentSlideIndexRef.current = -1;
    applyRecordingFrame(frame);
    setIsPreviewing(true);
  }, [applyRecordingFrame, calculateRecordingFrame, currentSlideIndex, getSortedSlideElements, goToSlide]);

  // Cancel preview mode
  const cancelPreview = useCallback(() => {
    trackRecordingCancelled('preview');
    activeSlideIdRef.current = null;
    setIsPreviewing(false);
    setRecordingFrame(null);
    recordingFrameRef.current = null;
  }, []);

  // Actually start recording (after preview/positioning)
  const confirmRecording = useCallback(async () => {
    const { width, height } = getRecordingDimensions();

    setIsPreviewing(false);

    let canvas = compositeCanvasRef.current;
    if (!canvas) {
      canvas = document.createElement('canvas');
      compositeCanvasRef.current = canvas;
    }
    canvas.width = width;
    canvas.height = height;

    // Check if WebCodecs is supported (Chrome, Edge, Safari 16.4+)
    const useWebCodecs = isWebCodecsSupported();
    console.log('[Recording] WebCodecs supported:', useWebCodecs);

    if (useWebCodecs) {
      const audioTracks = settings.useMicrophone
        ? webcamStream?.getAudioTracks().filter((track) => track.readyState === 'live') || []
        : [];
      const audioStream = audioTracks.length > 0 ? new MediaStream(audioTracks) : undefined;

      // Use WebCodecs for direct MP4 recording (fast, no conversion needed)
      const recorder = new WebCodecsRecorder({
        width,
        height,
        frameRate: 30,
        videoBitrate: 5_000_000,
        audioStream,
      });

      webCodecsRecorderRef.current = recorder;

      try {
        await recorder.start();
        console.log('[Recording] WebCodecs recorder started');
      } catch (error) {
        console.error('[Recording] WebCodecs failed to start:', error);
        webCodecsRecorderRef.current = null;
        showNativeErrorDialog(text.alerts.recordingStartFailed, error);
        return;
      }
    } else {
      // Fallback: WebM recording (will need conversion)
      console.log('[Recording] Falling back to MediaRecorder (WebM)');
      showNativeErrorDialog(text.alerts.webmFallback);
      return;
    }

    // Start rendering loop
    setIsRecording(true);

    // Track recording started
    recordingStartTimeRef.current = Date.now();
    usedTeleprompterRef.current = showTeleprompter;
    usedPauseRef.current = false;
    trackRecordingStarted({
      aspectRatio: settings.aspectRatio,
      background: settings.backgroundId || 'custom',
      webcamEnabled: settings.showCamera,
      webcamPosition: 'bottom-right'
    });

    // Render a few frames before starting
    const preRenderFrames = () => {
      renderCompositeFrame();
      renderCompositeFrame();
      renderCompositeFrame();
    };

    setTimeout(() => {
      preRenderFrames();
      animationFrameRef.current = requestAnimationFrame(renderCompositeFrame);
    }, 100);
  }, [
    webcamStream,
    renderCompositeFrame,
    getRecordingDimensions,
    showNativeErrorDialog,
    showTeleprompter,
    settings,
    text.alerts.recordingStartFailed,
    text.alerts.webmFallback,
  ]);

  const syncRecordingSizeToCustomFrame = useCallback((frame: RecordingFrame) => {
    const customWidth = toEvenRecordingDimension(frame.width);
    const customHeight = toEvenRecordingDimension(frame.height);

    setSettings((currentSettings) => {
      if (
        currentSettings.aspectRatio === 'custom' &&
        currentSettings.customWidth === customWidth &&
        currentSettings.customHeight === customHeight
      ) {
        return currentSettings;
      }

      if (currentSettings.aspectRatio !== 'custom') {
        trackSettingsChanged('aspect_ratio', 'custom');
      }

      return {
        ...currentSettings,
        aspectRatio: 'custom',
        customWidth,
        customHeight,
      };
    });
  }, []);

  // Handle dragging the recording frame during preview
  const handleFrameDrag = useCallback((e: React.MouseEvent) => {
    if (!isPreviewing || !recordingFrame) return;
    e.stopPropagation();

    const startX = e.clientX;
    const startY = e.clientY;
    const startFrame = { ...recordingFrame };

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = moveEvent.clientX - startX;
      const deltaY = moveEvent.clientY - startY;

      const container = document.querySelector('.excalidraw-container');
      if (!container) return;
      const containerRect = container.getBoundingClientRect();

      // Constrain to container bounds
      const newX = Math.max(0, Math.min(startFrame.x + deltaX, containerRect.width - startFrame.width));
      const newY = Math.max(0, Math.min(startFrame.y + deltaY, containerRect.height - startFrame.height));

      const newFrame = { ...startFrame, x: newX, y: newY };
      applyRecordingFrame(newFrame);
    };

    const handleMouseUp = () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  }, [applyRecordingFrame, isPreviewing, recordingFrame]);

  // Handle resizing the recording frame (maintains aspect ratio)
  const handleFrameResize = useCallback((e: React.MouseEvent, corner: string) => {
    if (!isPreviewing || !recordingFrame) return;
    e.stopPropagation();
    e.preventDefault();

    const startX = e.clientX;
    const startFrame = { ...recordingFrame };
    const aspectRatio = startFrame.width / startFrame.height;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = moveEvent.clientX - startX;
      // Note: We only use deltaX and maintain aspect ratio

      const container = document.querySelector('.excalidraw-container');
      if (!container) return;
      const containerRect = container.getBoundingClientRect();

      let newWidth = startFrame.width;
      let newHeight = startFrame.height;
      let newX = startFrame.x;
      let newY = startFrame.y;

      // Calculate new size based on which corner is being dragged
      if (corner === 'se') {
        // Southeast - expand from bottom-right
        newWidth = Math.max(320, startFrame.width + deltaX);
        newHeight = newWidth / aspectRatio;
      } else if (corner === 'sw') {
        // Southwest - expand from bottom-left
        newWidth = Math.max(320, startFrame.width - deltaX);
        newHeight = newWidth / aspectRatio;
        newX = startFrame.x + startFrame.width - newWidth;
      } else if (corner === 'ne') {
        // Northeast - expand from top-right
        newWidth = Math.max(320, startFrame.width + deltaX);
        newHeight = newWidth / aspectRatio;
        newY = startFrame.y + startFrame.height - newHeight;
      } else if (corner === 'nw') {
        // Northwest - expand from top-left
        newWidth = Math.max(320, startFrame.width - deltaX);
        newHeight = newWidth / aspectRatio;
        newX = startFrame.x + startFrame.width - newWidth;
        newY = startFrame.y + startFrame.height - newHeight;
      }

      // Constrain to container bounds
      if (newX < 0) {
        newX = 0;
        newWidth = startFrame.x + startFrame.width;
        newHeight = newWidth / aspectRatio;
      }
      if (newY < 0) {
        newY = 0;
        newHeight = startFrame.y + startFrame.height;
        newWidth = newHeight * aspectRatio;
      }
      if (newX + newWidth > containerRect.width) {
        newWidth = containerRect.width - newX;
        newHeight = newWidth / aspectRatio;
      }
      if (newY + newHeight > containerRect.height) {
        newHeight = containerRect.height - newY;
        newWidth = newHeight * aspectRatio;
      }

      const newFrame = { x: newX, y: newY, width: newWidth, height: newHeight };
      applyRecordingFrame(newFrame);
      syncRecordingSizeToCustomFrame(newFrame);
    };

    const handleMouseUp = () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  }, [applyRecordingFrame, isPreviewing, recordingFrame, syncRecordingSizeToCustomFrame]);

  // Pause/Resume recording
  const togglePause = useCallback(() => {
    const recorder = webCodecsRecorderRef.current;
    if (!recorder) return;

    if (isPaused) {
      // Resume recording
      recorder.resume();
      setIsPaused(false);
    } else {
      // Pause recording - track that pause was used
      usedPauseRef.current = true;
      recorder.pause();
      setIsPaused(true);
    }
  }, [isPaused]);

  // Stop recording
  const stopRecording = useCallback(async () => {
    // Track recording completed with duration
    if (recordingStartTimeRef.current) {
      const durationSeconds = Math.round((Date.now() - recordingStartTimeRef.current) / 1000);
      trackRecordingCompleted({
        durationSeconds,
        aspectRatio: settingsRef.current.aspectRatio,
        background: settingsRef.current.backgroundId || 'custom',
        webcamEnabled: settingsRef.current.showCamera,
        usedTeleprompter: usedTeleprompterRef.current,
        usedPause: usedPauseRef.current
      });
      recordingStartTimeRef.current = null;
    }

    setIsRecording(false);
    setIsPaused(false);
    activeSlideIdRef.current = null;
    setRecordingFrame(null);
    recordingFrameRef.current = null;

    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }

    // Stop WebCodecs recorder and get the MP4 blob
    const recorder = webCodecsRecorderRef.current;
    if (recorder && recorder.recording) {
      setIsConverting(true);
      setConvertingMessage(text.status.finalizingVideo);

      try {
        const mp4Blob = await recorder.stop();

        // Download the MP4
        const url = URL.createObjectURL(mp4Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `excalicord-${Date.now()}.mp4`;
        a.click();
        URL.revokeObjectURL(url);

        console.log('[Recording] MP4 saved, size:', (mp4Blob.size / 1024 / 1024).toFixed(2), 'MB');
      } catch (error) {
        console.error('[Recording] Failed to stop recorder:', error);
        showNativeErrorDialog(text.alerts.saveFailed, error);
      } finally {
        setIsConverting(false);
        setConvertingMessage('');
        webCodecsRecorderRef.current = null;
      }
    }
  }, [showNativeErrorDialog, text.alerts.saveFailed, text.status.finalizingVideo]);

  const handleBubbleDrag = useCallback((pos: { x: number; y: number }) => {
    const frame = recordingFrameRef.current;
    const size = settingsRef.current.webcamSize;

    setHasBubbleCustomPosition(true);

    // If we have a recording frame (preview or recording), constrain bubble to it
    if (frame) {
      const constrainedX = Math.max(frame.x, Math.min(pos.x, frame.x + frame.width - size));
      const constrainedY = Math.max(frame.y, Math.min(pos.y, frame.y + frame.height - size));
      setBubblePosition({ x: constrainedX, y: constrainedY });
    } else {
      setBubblePosition(clampBubblePosition(pos, size, sidebarAvoidanceRight));
    }
  }, [sidebarAvoidanceRight]);

  const updateWebcamShape = useCallback((webcamShape: RecordingSettings['webcamShape']) => {
    setSettings((currentSettings) => {
      if (currentSettings.webcamShape === webcamShape) {
        return currentSettings;
      }

      trackSettingsChanged('webcam_shape', webcamShape);
      return {
        ...currentSettings,
        webcamShape,
      };
    });
  }, []);

  const updateWebcamSize = useCallback((webcamSize: number) => {
    const nextSize = Math.round(clampNumber(webcamSize, CAMERA_SIZE_MIN, CAMERA_SIZE_MAX));

    setSettings((currentSettings) => {
      if (currentSettings.webcamSize === nextSize) {
        return currentSettings;
      }

      return {
        ...currentSettings,
        webcamSize: nextSize,
      };
    });
  }, []);

  const updateRecordingSize = useCallback((nextSize: {
    aspectRatio: string;
    customWidth: number;
    customHeight: number;
  }) => {
    const normalizedSize = {
      ...nextSize,
      customWidth: toEvenRecordingDimension(nextSize.customWidth),
      customHeight: toEvenRecordingDimension(nextSize.customHeight),
    };

    if (isPreviewing) {
      const nextFrame = calculateRecordingFrameForDimensions(
        { width: normalizedSize.customWidth, height: normalizedSize.customHeight },
        recordingFrameRef.current,
      );

      if (nextFrame) {
        applyRecordingFrame(nextFrame);
      }
    }

    setSettings((currentSettings) => {
      if (
        currentSettings.aspectRatio === normalizedSize.aspectRatio &&
        currentSettings.customWidth === normalizedSize.customWidth &&
        currentSettings.customHeight === normalizedSize.customHeight
      ) {
        return currentSettings;
      }

      trackSettingsChanged('aspect_ratio', normalizedSize.aspectRatio);

      return {
        ...currentSettings,
        ...normalizedSize,
      };
    });
  }, [applyRecordingFrame, calculateRecordingFrameForDimensions, isPreviewing]);

  const handleEditorChange = useCallback((elements: readonly OrderedExcalidrawElement[], appState: AppState) => {
    const nextHasCanvasContent = elements.some((element) => !element.isDeleted);
    const nextSlideFrames = getSlideFramesFromElements(elements);
    const nextIsWelcomeViewActive = getIsWelcomeScreenActive(appState, nextHasCanvasContent);

    setIsWelcomeViewActive((currentIsWelcomeViewActive) => (
      currentIsWelcomeViewActive === nextIsWelcomeViewActive
        ? currentIsWelcomeViewActive
        : nextIsWelcomeViewActive
    ));

    setHasCanvasContent((currentHasCanvasContent) => (
      currentHasCanvasContent === nextHasCanvasContent ? currentHasCanvasContent : nextHasCanvasContent
    ));

    setSlideFrames((currentSlideFrames) => (
      areSlideFramesEqual(currentSlideFrames, nextSlideFrames) ? currentSlideFrames : nextSlideFrames
    ));

    setCurrentSlideIndex((currentIndex) => {
      if (nextSlideFrames.length === 0) {
        return -1;
      }

      const selectedElementIds = Object.keys(appState.selectedElementIds || {})
        .filter((elementId) => appState.selectedElementIds[elementId]);

      if (selectedElementIds.length > 0) {
        const selectedSlideIndex = nextSlideFrames.findIndex((slide) => selectedElementIds.includes(slide.id));

        if (selectedSlideIndex >= 0) {
          return selectedSlideIndex;
        }

        const selectedChildSlideIndex = elements.find((element) => (
          selectedElementIds.includes(element.id) && element.frameId
        ));

        if (selectedChildSlideIndex?.frameId) {
          const frameIndex = nextSlideFrames.findIndex((slide) => slide.id === selectedChildSlideIndex.frameId);

          if (frameIndex >= 0) {
            return frameIndex;
          }
        }
      }

      if (currentIndex < 0) {
        return 0;
      }

      return Math.min(currentIndex, nextSlideFrames.length - 1);
    });

    const nextPreferences = getEditorPreferenceState(appState);

    setEditorPreferenceState((currentPreferences) => (
      currentPreferences.gridModeEnabled === nextPreferences.gridModeEnabled &&
      currentPreferences.zenModeEnabled === nextPreferences.zenModeEnabled &&
      currentPreferences.viewModeEnabled === nextPreferences.viewModeEnabled &&
      currentPreferences.objectsSnapModeEnabled === nextPreferences.objectsSnapModeEnabled &&
      currentPreferences.toolLocked === nextPreferences.toolLocked &&
      currentPreferences.arrowBindingEnabled === nextPreferences.arrowBindingEnabled &&
      currentPreferences.statsOpen === nextPreferences.statsOpen
        ? currentPreferences
        : nextPreferences
    ));
  }, []);

  const updateEditorAppState = useCallback((appState: Partial<AppState>) => {
    if (!excalidrawApi) {
      return;
    }

    excalidrawApi.updateScene({
      appState: {
        ...excalidrawApi.getAppState(),
        ...appState,
      },
      captureUpdate: CaptureUpdateAction.EVENTUALLY,
    });
  }, [excalidrawApi]);

  const closeExcalidrawHelpDialog = useCallback(() => {
    if (excalidrawApi?.getAppState().openDialog?.name === 'help') {
      const currentAppState = excalidrawApi.getAppState();
      excalidrawApi.updateScene({
        appState: {
          ...currentAppState,
          openDialog: null,
        },
        captureUpdate: CaptureUpdateAction.NEVER,
      });
      return;
    }

    document
      .querySelector<HTMLElement>('.excalidraw-modal-container .Modal.HelpDialog .Modal__background')
      ?.click();
  }, [excalidrawApi]);

  const toggleGridMode = useCallback(() => {
    const appState = excalidrawApi?.getAppState();
    const nextGridModeEnabled = !(appState?.gridModeEnabled ?? editorPreferenceState.gridModeEnabled);

    updateEditorAppState({
      gridModeEnabled: nextGridModeEnabled,
      objectsSnapModeEnabled: false,
    });
    setEditorPreferenceState((currentPreferences) => ({
      ...currentPreferences,
      gridModeEnabled: nextGridModeEnabled,
      objectsSnapModeEnabled: false,
    }));
  }, [editorPreferenceState.gridModeEnabled, excalidrawApi, updateEditorAppState]);

  const toggleObjectsSnapMode = useCallback(() => {
    const appState = excalidrawApi?.getAppState();
    const nextObjectsSnapModeEnabled = !(appState?.objectsSnapModeEnabled ?? editorPreferenceState.objectsSnapModeEnabled);

    updateEditorAppState({
      objectsSnapModeEnabled: nextObjectsSnapModeEnabled,
      gridModeEnabled: false,
    });
    setEditorPreferenceState((currentPreferences) => ({
      ...currentPreferences,
      objectsSnapModeEnabled: nextObjectsSnapModeEnabled,
      gridModeEnabled: false,
    }));
  }, [editorPreferenceState.objectsSnapModeEnabled, excalidrawApi, updateEditorAppState]);

  const toggleEditorBooleanPreference = useCallback((
    key: 'zenModeEnabled' | 'viewModeEnabled' | 'isBindingEnabled',
    stateKey: 'zenModeEnabled' | 'viewModeEnabled' | 'arrowBindingEnabled',
  ) => {
    const appState = excalidrawApi?.getAppState();
    const currentValue = key === 'isBindingEnabled'
      ? (appState?.isBindingEnabled ?? editorPreferenceState.arrowBindingEnabled)
      : (appState?.[key] ?? editorPreferenceState[stateKey]);
    const nextValue = !currentValue;

    updateEditorAppState({ [key]: nextValue } as Partial<AppState>);
    setEditorPreferenceState((currentPreferences) => ({
      ...currentPreferences,
      [stateKey]: nextValue,
    }));
  }, [editorPreferenceState, excalidrawApi, updateEditorAppState]);

  const toggleToolLock = useCallback(() => {
    const appState = excalidrawApi?.getAppState();
    if (!appState) {
      return;
    }

    const nextToolLocked = !appState.activeTool.locked;
    updateEditorAppState({
      activeTool: {
        ...appState.activeTool,
        locked: nextToolLocked,
      },
    } as Partial<AppState>);
    setEditorPreferenceState((currentPreferences) => ({
      ...currentPreferences,
      toolLocked: nextToolLocked,
    }));
  }, [excalidrawApi, updateEditorAppState]);

  const toggleStatsPanel = useCallback(() => {
    const appState = excalidrawApi?.getAppState();
    const stats = appState?.stats ?? { open: editorPreferenceState.statsOpen, panels: 0 };
    const nextStatsOpen = !stats.open;

    updateEditorAppState({
      stats: {
        ...stats,
        open: nextStatsOpen,
      },
    });
    setEditorPreferenceState((currentPreferences) => ({
      ...currentPreferences,
      statsOpen: nextStatsOpen,
    }));
  }, [editorPreferenceState.statsOpen, excalidrawApi, updateEditorAppState]);

  const toggleTeleprompter = useCallback(() => {
    const nextShowTeleprompter = !showTeleprompter;

    if (nextShowTeleprompter) {
      setHasTeleprompterCustomPosition(false);
      setTeleprompterPosition(getDefaultTeleprompterPosition(recordingFrameRef.current, sidebarAvoidanceRight));
    }

    setShowTeleprompter(nextShowTeleprompter);
    trackTeleprompterUsed(nextShowTeleprompter ? 'opened' : 'closed');
    if (nextShowTeleprompter && isRecording) {
      usedTeleprompterRef.current = true;
    }
  }, [isRecording, showTeleprompter, sidebarAvoidanceRight]);

  const openRecordingSettings = useCallback(() => {
    setSettingsScope('recording');
    setShowSettings(true);
  }, []);

  const openShortcutSettings = useCallback(() => {
    setSettingsScope('preferences');
    setShowPreferencesSubmenu(false);
    setShowSettings(true);
  }, []);

  const openAboutDialog = useCallback(() => {
    setShowPreferencesSubmenu(false);
    setShowAboutDialog(true);
  }, []);

  const openGuideDialog = useCallback(() => {
    setShowPreferencesSubmenu(false);
    setShowGuideDialog(true);
  }, []);

  const activateExcalidrawTool = useCallback((tool: ToolType) => {
    if (!excalidrawApi) {
      return;
    }

    const locked = excalidrawApi.getAppState().activeTool.locked;

    if (tool === 'image') {
      excalidrawApi.setActiveTool({ type: 'image', locked });
      return;
    }

    excalidrawApi.setActiveTool({
      type: tool as Exclude<ToolType, 'image'>,
      locked,
    });
  }, [excalidrawApi]);

  const triggerShortcutAction = useCallback((action: ShortcutActionId) => {
    switch (action) {
      case 'toolSelection':
        activateExcalidrawTool('selection');
        return;

      case 'toolHand':
        activateExcalidrawTool('hand');
        return;

      case 'toolRectangle':
        activateExcalidrawTool('rectangle');
        return;

      case 'toolDiamond':
        activateExcalidrawTool('diamond');
        return;

      case 'toolEllipse':
        activateExcalidrawTool('ellipse');
        return;

      case 'toolArrow':
        activateExcalidrawTool('arrow');
        return;

      case 'toolLine':
        activateExcalidrawTool('line');
        return;

      case 'toolDraw':
        activateExcalidrawTool('freedraw');
        return;

      case 'toolText':
        activateExcalidrawTool('text');
        return;

      case 'toolImage':
        activateExcalidrawTool('image');
        return;

      case 'toolEraser':
        activateExcalidrawTool('eraser');
        return;

      case 'toolFrame':
        activateExcalidrawTool('frame');
        return;

      case 'toolEmbeddable':
        activateExcalidrawTool('embeddable');
        return;

      case 'toolLaser':
        activateExcalidrawTool('laser');
        return;

      case 'record':
        if (isConverting || isRecording) {
          return;
        }
        if (isPreviewing) {
          void confirmRecording();
          return;
        }
        enterPreviewMode();
        return;

      case 'cancelPreview':
        if (isPreviewing) {
          cancelPreview();
        }
        return;

      case 'pauseResume':
        if (isRecording) {
          togglePause();
        }
        return;

      case 'stopRecording':
        if (isRecording) {
          void stopRecording();
        }
        return;

      case 'openSettings':
        openRecordingSettings();
        return;

      case 'openShortcutSettings':
        openShortcutSettings();
        return;

      case 'openLibrary':
        openLibrary();
        return;

      case 'toggleTeleprompter':
        toggleTeleprompter();
        return;

      case 'toggleCursor':
        setSettings((currentSettings) => ({
          ...currentSettings,
          showCursor: !currentSettings.showCursor,
        }));
        return;

      case 'toggleCamera':
        setSettings((currentSettings) => ({
          ...currentSettings,
          showCamera: !currentSettings.showCamera,
        }));
        return;

      case 'toolLock':
        toggleToolLock();
        return;

      case 'toggleGrid':
        toggleGridMode();
        return;

      case 'objectsSnap':
        toggleObjectsSnapMode();
        return;

      case 'zenMode':
        toggleEditorBooleanPreference('zenModeEnabled', 'zenModeEnabled');
        return;

      case 'viewMode':
        toggleEditorBooleanPreference('viewModeEnabled', 'viewModeEnabled');
        return;

      case 'arrowBinding':
        toggleEditorBooleanPreference('isBindingEnabled', 'arrowBindingEnabled');
        return;

      case 'properties':
        toggleStatsPanel();
        return;
    }
  }, [
    activateExcalidrawTool,
    cancelPreview,
    confirmRecording,
    enterPreviewMode,
    isConverting,
    isPreviewing,
    isRecording,
    openLibrary,
    openRecordingSettings,
    openShortcutSettings,
    stopRecording,
    toggleEditorBooleanPreference,
    toggleGridMode,
    toggleObjectsSnapMode,
    togglePause,
    toggleStatsPanel,
    toggleTeleprompter,
    toggleToolLock,
  ]);

  useEffect(() => {
    const handleGlobalShortcut = (event: KeyboardEvent) => {
      if (nativeDialog || showSettings || isEditableShortcutTarget(event.target)) {
        return;
      }

      const shortcutAction = (Object.entries(shortcuts) as Array<[ShortcutActionId, string]>)
        .find(([, shortcut]) => matchesShortcut(event, shortcut))?.[0];

      if (!shortcutAction) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      triggerShortcutAction(shortcutAction);
    };

    window.addEventListener('keydown', handleGlobalShortcut, true);

    return () => {
      window.removeEventListener('keydown', handleGlobalShortcut, true);
    };
  }, [nativeDialog, shortcuts, showSettings, triggerShortcutAction]);

  // Teleprompter drag handler
  const handleTeleprompterDrag = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;

    const isHeaderDrag = Boolean(target.closest('.teleprompter-header'));
    const isMinimalEdgeDrag = Boolean(target.closest('.smart-teleprompter-minimal-drag-edge'));

    if ((!isHeaderDrag && !isMinimalEdgeDrag) || target.closest('button')) return;
    e.preventDefault();

    const startX = e.clientX;
    const startY = e.clientY;
    const startPos = { ...teleprompterPosition };
    const panelWidth = getTeleprompterWidth(recordingFrameRef.current);

    setHasTeleprompterCustomPosition(true);
    setIsTeleprompterDragging(true);

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = moveEvent.clientX - startX;
      const deltaY = moveEvent.clientY - startY;

      setTeleprompterPosition(clampTeleprompterPosition({
        x: startPos.x + deltaX,
        y: startPos.y + deltaY,
      }, panelWidth, sidebarAvoidanceRight));
    };

    const handleMouseUp = () => {
      setIsTeleprompterDragging(false);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  }, [sidebarAvoidanceRight, teleprompterPosition]);

  const hasCameraStream = Boolean(
    webcamStream?.getVideoTracks().some((track) => track.readyState === 'live'),
  );
  const hasMicrophoneStream = Boolean(
    webcamStream?.getAudioTracks().some((track) => track.readyState === 'live'),
  );
  const displayWebcamStream = webcamStream;
  const cameraEffectsClass = '';
  const webcamQuickControlsStyle = useMemo(() => {
    const viewport = getBubbleViewport();
    const availableWidth = Math.max(
      WEBCAM_QUICK_PANEL_WIDTH + WEBCAM_QUICK_PANEL_MARGIN * 2,
      viewport.width - Math.max(0, sidebarAvoidanceRight),
    );
    const left = clampNumber(
      bubblePosition.x + settings.webcamSize / 2 - WEBCAM_QUICK_PANEL_WIDTH / 2,
      WEBCAM_QUICK_PANEL_MARGIN,
      Math.max(
        WEBCAM_QUICK_PANEL_MARGIN,
        availableWidth - WEBCAM_QUICK_PANEL_WIDTH - WEBCAM_QUICK_PANEL_MARGIN,
      ),
    );
    const hasRoomAbove = bubblePosition.y > WEBCAM_QUICK_PANEL_HEIGHT + WEBCAM_QUICK_PANEL_MARGIN * 2;
    const top = hasRoomAbove
      ? Math.max(WEBCAM_QUICK_PANEL_MARGIN, bubblePosition.y - 12)
      : Math.min(
        Math.max(WEBCAM_QUICK_PANEL_MARGIN, bubblePosition.y + settings.webcamSize + 12),
        Math.max(
          WEBCAM_QUICK_PANEL_MARGIN,
          viewport.height - WEBCAM_QUICK_PANEL_HEIGHT - WEBCAM_QUICK_PANEL_MARGIN,
        ),
      );

    return {
      left,
      top,
      width: WEBCAM_QUICK_PANEL_WIDTH,
      transform: hasRoomAbove ? 'translateY(-100%)' : 'none',
    };
  }, [bubblePosition.x, bubblePosition.y, settings.webcamSize, sidebarAvoidanceRight]);

  useEffect(() => {
    if (!showWebcamQuickControls) {
      return;
    }

    const closeWebcamQuickControls = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;

      if (
        target?.closest('.webcam-bubble') ||
        target?.closest('.webcam-quick-controls')
      ) {
        return;
      }

      setShowWebcamQuickControls(false);
    };

    document.addEventListener('mousedown', closeWebcamQuickControls);

    return () => {
      document.removeEventListener('mousedown', closeWebcamQuickControls);
    };
  }, [showWebcamQuickControls]);

  useEffect(() => {
    if (!settings.showCamera || !hasCameraStream) {
      setShowWebcamQuickControls(false);
    }
  }, [hasCameraStream, settings.showCamera]);

  const positionPreferencesSubmenu = useCallback((trigger: HTMLElement) => {
    const rect = trigger.getBoundingClientRect();
    const canOpenRight = rect.right + PREFERENCES_SUBMENU_GAP + PREFERENCES_SUBMENU_WIDTH <= (
      window.innerWidth - PREFERENCES_SUBMENU_VIEWPORT_PADDING
    );
    const left = canOpenRight
      ? rect.right + PREFERENCES_SUBMENU_GAP
      : Math.max(
        PREFERENCES_SUBMENU_VIEWPORT_PADDING,
        rect.left - PREFERENCES_SUBMENU_GAP - PREFERENCES_SUBMENU_WIDTH,
      );
    const top = clampNumber(
      rect.top,
      PREFERENCES_SUBMENU_VIEWPORT_PADDING,
      Math.max(
        PREFERENCES_SUBMENU_VIEWPORT_PADDING,
        window.innerHeight - PREFERENCES_SUBMENU_HEIGHT - PREFERENCES_SUBMENU_VIEWPORT_PADDING,
      ),
    );

    setPreferencesSubmenuPosition({
      left: Math.round(left),
      top: Math.round(top),
    });
  }, []);

  useEffect(() => {
    if (!showPreferencesSubmenu) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;

      if (
        target?.closest('.excalicord-preferences-menu') ||
        target?.closest('.excalicord-preferences-popover')
      ) {
        return;
      }

      setShowPreferencesSubmenu(false);
    };

    const closePreferencesSubmenu = () => {
      setShowPreferencesSubmenu(false);
    };

    document.addEventListener('pointerdown', handlePointerDown, true);
    window.addEventListener('resize', closePreferencesSubmenu);
    window.addEventListener('scroll', closePreferencesSubmenu, true);

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
      window.removeEventListener('resize', closePreferencesSubmenu);
      window.removeEventListener('scroll', closePreferencesSubmenu, true);
    };
  }, [showPreferencesSubmenu]);

  const preferenceMenuItems = [
    {
      id: 'tool-lock',
      label: text.preferences.toolLock,
      selected: editorPreferenceState.toolLocked,
      shortcut: formatShortcut(shortcuts.toolLock, language),
      onSelect: toggleToolLock,
    },
    {
      id: 'objects-snap',
      label: text.preferences.objectsSnap,
      selected: editorPreferenceState.objectsSnapModeEnabled,
      shortcut: formatShortcut(shortcuts.objectsSnap, language),
      onSelect: toggleObjectsSnapMode,
    },
    {
      id: 'toggle-grid',
      label: text.preferences.toggleGrid,
      selected: editorPreferenceState.gridModeEnabled,
      shortcut: formatShortcut(shortcuts.toggleGrid, language),
      onSelect: toggleGridMode,
    },
    {
      id: 'zen-mode',
      label: text.preferences.zenMode,
      selected: editorPreferenceState.zenModeEnabled,
      shortcut: formatShortcut(shortcuts.zenMode, language),
      onSelect: () => toggleEditorBooleanPreference('zenModeEnabled', 'zenModeEnabled'),
    },
    {
      id: 'view-mode',
      label: text.preferences.viewMode,
      selected: editorPreferenceState.viewModeEnabled,
      shortcut: formatShortcut(shortcuts.viewMode, language),
      onSelect: () => toggleEditorBooleanPreference('viewModeEnabled', 'viewModeEnabled'),
    },
    {
      id: 'properties',
      label: text.preferences.properties,
      selected: editorPreferenceState.statsOpen,
      shortcut: formatShortcut(shortcuts.properties, language),
      onSelect: toggleStatsPanel,
    },
    {
      id: 'arrow-binding',
      label: text.preferences.arrowBinding,
      selected: editorPreferenceState.arrowBindingEnabled,
      shortcut: formatShortcut(shortcuts.arrowBinding, language),
      onSelect: () => toggleEditorBooleanPreference('isBindingEnabled', 'arrowBindingEnabled'),
    },
  ];
  const showWelcomeGuideHints = isWelcomeViewActive &&
    !hasCanvasContent &&
    !showSettings &&
    !showAboutDialog &&
    !showGuideDialog &&
    !showPreferencesSubmenu &&
    !showWebcamQuickControls &&
    !nativeDialog &&
    !isPreviewing &&
    !isRecording &&
    !isConverting;

  // If on mobile, show the landing page with email capture after all hooks have run.
  if (isMobile) {
    return <MobileLanding language={language} onLanguageChange={setLanguage} />;
  }

  return (
    <div
      ref={appContainerRef}
      className="app-container"
      data-appearance={appearanceMode}
      data-language={language}
      data-theme={editorTheme}
      style={{ '--sidebar-avoidance-right': `${sidebarAvoidanceRight}px` } as CSSProperties}
    >
      <WelcomeModal language={language} />
      <GlobalTooltip />
      {nativeDialog && (
        <div
          className="native-dialog-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setNativeDialog(null);
            }
          }}
        >
          <section
            className="native-dialog-card"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="native-dialog-title"
            aria-describedby="native-dialog-message"
          >
            <div className="native-dialog-icon" aria-hidden="true">
              !
            </div>
            <div className="native-dialog-content">
              <h2 id="native-dialog-title">{nativeDialog.title}</h2>
              <p id="native-dialog-message">{nativeDialog.message}</p>
              {nativeDialog.detail && (
                <p className="native-dialog-detail">{nativeDialog.detail}</p>
              )}
            </div>
            <button
              type="button"
              className="native-dialog-action"
              onClick={() => setNativeDialog(null)}
              autoFocus
            >
              {text.alerts.ok}
            </button>
          </section>
        </div>
      )}
      <RecordingControls
        isRecording={isRecording}
        isPreviewing={isPreviewing}
        isPaused={isPaused}
        isConverting={isConverting}
        convertingMessage={convertingMessage}
        showCursor={settings.showCursor}
        aspectRatios={ASPECT_RATIOS}
        aspectRatio={settings.aspectRatio}
        customWidth={settings.customWidth}
        customHeight={settings.customHeight}
        onStartRecording={enterPreviewMode}
        onStopRecording={stopRecording}
        onTogglePause={togglePause}
        onToggleCursor={() => setSettings(prev => ({ ...prev, showCursor: !prev.showCursor }))}
        onConfirmRecording={confirmRecording}
        onCancelPreview={cancelPreview}
        onRecordingSizeChange={updateRecordingSize}
        onOpenSettings={openRecordingSettings}
        onOpenLibrary={openLibrary}
        onToggleTeleprompter={toggleTeleprompter}
        showTeleprompter={showTeleprompter}
        language={language}
      />

      <SettingsPanel
        isOpen={showSettings}
        scope={settingsScope}
        settings={settings}
        shortcuts={shortcuts}
        onSettingsChange={(newSettings) => {
          // Track significant setting changes
          if (newSettings.aspectRatio !== settings.aspectRatio) {
            trackSettingsChanged('aspect_ratio', newSettings.aspectRatio);
          }
          if (newSettings.backgroundId !== settings.backgroundId) {
            trackSettingsChanged('background', newSettings.backgroundId || 'custom');
          }
          if (newSettings.showCamera !== settings.showCamera) {
            trackSettingsChanged('webcam', newSettings.showCamera ? 'enabled' : 'disabled');
          }
          if (newSettings.useMicrophone !== settings.useMicrophone) {
            trackSettingsChanged('microphone', newSettings.useMicrophone ? 'enabled' : 'disabled');
          }
          if (newSettings.enableSound !== settings.enableSound) {
            trackSettingsChanged('sound', newSettings.enableSound ? 'enabled' : 'disabled');
          }
          const sanitizedSettings = disableCameraEffects(newSettings);
          if (sanitizedSettings.webcamShape !== settings.webcamShape) {
            trackSettingsChanged('webcam_shape', sanitizedSettings.webcamShape);
          }
          setSettings(sanitizedSettings);
        }}
        onShortcutsChange={setShortcuts}
        onClose={() => setShowSettings(false)}
        language={language}
        devicePermissions={devicePermissions}
        hasCameraStream={hasCameraStream}
        hasMicrophoneStream={hasMicrophoneStream}
        cameraPreviewStream={webcamStream}
        mediaDevices={mediaDevices}
        audioOutputSupported={audioOutputSupported}
      />

      {showLibraryBrowser && (
        <LibraryBrowserPanel
          url={libraryBrowserUrl}
          language={language}
          isPinned={isLibraryBrowserPinned}
          onAddLibrary={addPublicLibrary}
          onClose={closeLibraryBrowser}
          onPinnedChange={setIsLibraryBrowserPinned}
        />
      )}

      {showWelcomeGuideHints && (
        <div className="xiangrui-site-hint excalifont" aria-hidden="true">
          <svg viewBox="0 0 83 70" fill="none" focusable="false">
            <path
              d="M76.814 61.413C62.623 58.781 43.42 53.595 34.376 42.138 25.37 30.73 29.745 13.905 35.542 2.141"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <path
              fillRule="evenodd"
              clipRule="evenodd"
              d="M35.418.917 23.43 11.87l14.083 1.624L35.418.917Z"
              fill="currentColor"
            />
            <path
              d="M35.418.917c-2.903 2.654-5.801 5.3-11.988 10.953m11.988-10.953c-4.714 4.309-9.43 8.626-11.988 10.953m0 0c3.73.43 7.452.854 14.083 1.624m-14.083-1.624c5.342.616 10.694 1.243 14.083 1.624m0 0c-.812-5.253-1.612-10.504-2.095-12.577"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          <span>{text.settings.xiangruiSiteHint}</span>
        </div>
      )}

      {showWelcomeGuideHints && (
        <div className="about-corner-hint excalifont" aria-hidden="true">
          <span>
            {text.settings.aboutHint.split('\n').map((line) => (
              <span key={line}>{line}</span>
            ))}
          </span>
          <svg viewBox="0 0 85 71" fill="none" focusable="false">
            <path
              d="M18.026 1.232c-5.268 13.125-5.548 33.555 3.285 42.311 8.823 8.75 33.31 12.304 42.422 13.523"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <path
              fillRule="evenodd"
              clipRule="evenodd"
              d="m72.181 59.247-13.058-10-2.948 13.62 16.006-3.62Z"
              fill="currentColor"
            />
            <path
              d="M72.181 59.247c-3.163-2.429-6.337-4.856-13.058-10m13.058 10c-5.145-3.936-10.292-7.882-13.058-10m0 0c-.78 3.603-1.563 7.196-2.948 13.62m2.948-13.62c-1.126 5.168-2.24 10.346-2.948 13.62m0 0c5.168-1.166 10.334-2.343 16.006-3.62m-16.006 3.62c5.51-1.248 11.01-2.495 16.006-3.62"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </div>
      )}

      <button
        type="button"
        className="about-corner-button"
        aria-label={text.settings.aboutTab}
        data-tooltip={text.settings.aboutTab}
        onClick={openAboutDialog}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v6" />
          <path d="M12 7.4h.01" />
        </svg>
      </button>

      <a
        className="xiangrui-site-button"
        href={XIANGRUI_WEBSITE_URL}
        target="_blank"
        rel="noreferrer"
        aria-label={text.settings.xiangruiSiteAria}
        data-tooltip={text.settings.xiangruiSiteAria}
      >
        <span className="xiangrui-site-button-label">{text.settings.xiangruiSite}</span>
        <span className="xiangrui-site-button-arrow" aria-hidden="true">↗</span>
      </a>

      <div className="excalidraw-container">
        <Excalidraw
          excalidrawAPI={setExcalidrawApi}
          libraryReturnUrl={`${window.location.origin}${window.location.pathname}`}
          theme={editorTheme}
          langCode={getExcalidrawLanguage(language)}
          detectScroll={false}
          handleKeyboardGlobally={true}
          autoFocus={true}
          validateEmbeddable={true}
          aiEnabled={false}
          onChange={handleEditorChange}
          onScrollChange={syncActiveSlideRecordingFrame}
          UIOptions={{
            canvasActions: {
              changeViewBackgroundColor: true,
              clearCanvas: true,
              export: { saveFileToDisk: true },
              loadScene: true,
              saveAsImage: true,
              saveToActiveFile: true,
              toggleTheme: true,
            },
            tools: {
              image: true,
            },
          }}
          onLinkOpen={(element, event) => {
            if (element.link && isElementLink(element.link)) {
              event.preventDefault();
              excalidrawApi?.scrollToContent(element.link, { animate: true });
            }
          }}
        >
          <MainMenu>
            <MainMenu.DefaultItems.LoadScene />
            <MainMenu.DefaultItems.SaveToActiveFile />
            <MainMenu.DefaultItems.Export />
            <MainMenu.DefaultItems.SaveAsImage />
            {language === 'en' && <MainMenu.DefaultItems.SearchMenu />}
            <MainMenu.DefaultItems.Help />
            <MainMenu.DefaultItems.ClearCanvas />

            <MainMenu.Separator />
            <MainMenu.Item
              icon={<LibraryMenuIcon />}
              shortcut={formatShortcut(shortcuts.openLibrary, language)}
              onClick={openLibrary}
            >
              {text.controls.library}
            </MainMenu.Item>
            <MainMenu.Item
              icon={<ShortcutSettingsMenuIcon />}
              shortcut={formatShortcut(shortcuts.openShortcutSettings, language)}
              onClick={openShortcutSettings}
            >
              {text.preferences.shortcutSettings}
            </MainMenu.Item>
            <MainMenu.Item
              icon={<AboutMenuIcon />}
              onClick={openAboutDialog}
            >
              {text.settings.aboutTab}
            </MainMenu.Item>

            <MainMenu.Separator />
            <MainMenu.ItemCustom className="excalicord-native-menu-item">
              <div
                className="excalicord-preferences-menu"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  className={`dropdown-menu-item-base dropdown-menu-item-bare excalicord-preferences-trigger ${showPreferencesSubmenu ? 'active' : ''}`}
                  aria-expanded={showPreferencesSubmenu}
                  aria-label={text.preferences.openMenu}
                  onClick={(event) => {
                    const nextOpen = !showPreferencesSubmenu;

                    if (nextOpen) {
                      positionPreferencesSubmenu(event.currentTarget);
                    }

                    setShowPreferencesSubmenu(nextOpen);
                  }}
                >
                  <span className="dropdown-menu-item__text">
                    {text.preferences.menuTitle}
                  </span>
                  <svg
                    className="excalicord-preferences-arrow"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                    focusable="false"
                  >
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </button>
              </div>
            </MainMenu.ItemCustom>

            <MainMenu.Separator />
            <MainMenu.Group title={text.language.menuTitle}>
              <MainMenu.ItemCustom className="excalicord-native-menu-item">
                <div
                  className="dropdown-menu-item-base dropdown-menu-item-bare excalicord-language-menu-content"
                  onClick={(event) => event.stopPropagation()}
                  onPointerDown={(event) => event.stopPropagation()}
                >
                  <label className="dropdown-menu-item__text" htmlFor="excalicord-language-select">
                    {text.language.menuLabel}
                  </label>
                  <select
                    id="excalicord-language-select"
                    className="dropdown-select dropdown-select__language excalicord-language-select"
                    value={language}
                    aria-label={text.language.ariaLabel}
                    onChange={(event) => setLanguage(event.target.value as LanguageCode)}
                  >
                    {languageOptions.map((option) => (
                      <option
                        key={option.code}
                        value={option.code}
                      >
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
              </MainMenu.ItemCustom>
            </MainMenu.Group>

            <MainMenu.Separator />
            <MainMenu.Group title={text.appearance.menuTitle}>
              <div className="excalicord-theme-menu-item">
                <MainMenu.DefaultItems.ToggleTheme
                  allowSystemTheme
                  theme={appearanceMode}
                  onSelect={(theme) => setAppearanceMode(theme)}
                />
              </div>
            </MainMenu.Group>

            <MainMenu.Separator />
            <MainMenu.DefaultItems.ChangeCanvasBackground />
          </MainMenu>

          <WelcomeScreen>
            <WelcomeScreen.Hints.MenuHint />
            <WelcomeScreen.Hints.ToolbarHint />
            <WelcomeScreen.Hints.HelpHint />
            <WelcomeScreen.Center>
              <WelcomeScreen.Center.Logo />
              <WelcomeScreen.Center.Heading>
                {text.welcome.officialHeading}
              </WelcomeScreen.Center.Heading>
              <WelcomeScreen.Center.Menu>
                <WelcomeScreen.Center.MenuItemLoadScene />
                <WelcomeScreen.Center.MenuItemHelp />
                <WelcomeScreen.Center.MenuItem
                  icon={<LibraryMenuIcon />}
                  shortcut={formatShortcut(shortcuts.openLibrary, language)}
                  onSelect={openLibrary}
                >
                  {text.controls.library}
                </WelcomeScreen.Center.MenuItem>
              </WelcomeScreen.Center.Menu>
            </WelcomeScreen.Center>
          </WelcomeScreen>

          <TTDDialogTrigger />
        </Excalidraw>

        <ExcalidrawHelpCloseButton
          language={language}
          label={text.common.closeHelpDialog}
          shortcuts={shortcuts}
          onClose={closeExcalidrawHelpDialog}
        />

        <SlideStrip
          slides={slideFrames.map((slide): SlideFrameItem => ({ id: slide.id, name: slide.name }))}
          currentSlideIndex={currentSlideIndex}
          isRecording={isRecording}
          isPreviewing={isPreviewing}
          settingsOpen={showSettings || showAboutDialog || showGuideDialog || Boolean(nativeDialog)}
          language={language}
          onAddSlide={addSlide}
          onGoToSlide={goToSlide}
          onDeleteSlide={deleteSlide}
        />

        {/* Recording frame overlay - shows the area being recorded */}
        {recordingFrame && (isRecording || isPreviewing) && (
          <>
            {/* Darkened areas outside the recording frame */}
            <div className="recording-overlay recording-overlay-top" style={{
              height: recordingFrame.y,
            }} />
            <div className="recording-overlay recording-overlay-bottom" style={{
              top: recordingFrame.y + recordingFrame.height,
              height: `calc(100% - ${recordingFrame.y + recordingFrame.height}px)`,
            }} />
            <div className="recording-overlay recording-overlay-left" style={{
              top: recordingFrame.y,
              width: recordingFrame.x,
              height: recordingFrame.height,
            }} />
            <div className="recording-overlay recording-overlay-right" style={{
              top: recordingFrame.y,
              left: recordingFrame.x + recordingFrame.width,
              width: `calc(100% - ${recordingFrame.x + recordingFrame.width}px)`,
              height: recordingFrame.height,
            }} />
            {/* Recording frame border */}
            <div
              className={`recording-frame-border ${isPreviewing ? 'preview-mode' : ''}`}
              style={{
                left: recordingFrame.x,
                top: recordingFrame.y,
                width: recordingFrame.width,
                height: recordingFrame.height,
                cursor: isPreviewing && slideFrames.length === 0 ? 'move' : 'default',
              }}
              onMouseDown={isPreviewing && slideFrames.length === 0 ? handleFrameDrag : undefined}
            >
              {isRecording && <span className="recording-badge">{text.preview.rec}</span>}
              {isPreviewing && (
                <>
                  <div className="preview-instructions">
                    <span className="preview-hint">
                      {slideFrames.length > 0 ? text.preview.hintSlides : text.preview.hint}
                    </span>
                  </div>
                  {/* Resize handles */}
                  {slideFrames.length === 0 && (
                    <>
                      <div
                        className="resize-handle resize-handle-corner resize-handle-nw"
                        onMouseDown={(e) => handleFrameResize(e, 'nw')}
                      />
                      <div
                        className="resize-handle resize-handle-corner resize-handle-ne"
                        onMouseDown={(e) => handleFrameResize(e, 'ne')}
                      />
                      <div
                        className="resize-handle resize-handle-corner resize-handle-sw"
                        onMouseDown={(e) => handleFrameResize(e, 'sw')}
                      />
                      <div
                        className="resize-handle resize-handle-corner resize-handle-se"
                        onMouseDown={(e) => handleFrameResize(e, 'se')}
                      />
                    </>
                  )}
                </>
              )}
            </div>
          </>
        )}

        {/* Teleprompter */}
        {showTeleprompter && (
          <TeleprompterPanel
            language={language}
            value={teleprompterText}
            position={teleprompterPosition}
            isDragging={isTeleprompterDragging}
            frameWidth={recordingFrame?.width}
            sidebarAvoidanceRight={sidebarAvoidanceRight}
            microphoneDeviceId={settings.microphoneDeviceId}
            onChange={setTeleprompterText}
            onClose={() => setShowTeleprompter(false)}
            onMouseDown={handleTeleprompterDrag}
          />
        )}

        {displayWebcamStream && settings.showCamera && hasCameraStream && (
          <WebcamBubble
            stream={displayWebcamStream}
            position={bubblePosition}
            size={settings.webcamSize}
            shape={settings.webcamShape}
            effectsClass={cameraEffectsClass}
            onDrag={handleBubbleDrag}
            onActivate={() => setShowWebcamQuickControls((isVisible) => !isVisible)}
            videoRef={webcamVideoRef}
          />
        )}

        {displayWebcamStream && settings.showCamera && hasCameraStream && showWebcamQuickControls && (
          <div
            className="webcam-quick-controls"
            style={webcamQuickControlsStyle}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="webcam-quick-header">
              <span>{text.settings.camera}</span>
              <span>{settings.webcamSize}px</span>
            </div>
            <div
              className="webcam-quick-shape-row"
              role="group"
              aria-label={text.settings.cameraShape}
            >
              <button
                type="button"
                className={`webcam-quick-shape-btn ${settings.webcamShape === 'circle' ? 'active' : ''}`}
                onClick={() => updateWebcamShape('circle')}
              >
                <span className="webcam-quick-shape-mark circle" aria-hidden="true" />
                <span>{text.settings.circle}</span>
              </button>
              <button
                type="button"
                className={`webcam-quick-shape-btn ${settings.webcamShape === 'square' ? 'active' : ''}`}
                onClick={() => updateWebcamShape('square')}
              >
                <span className="webcam-quick-shape-mark square" aria-hidden="true" />
                <span>{text.settings.square}</span>
              </button>
            </div>
            <label className="webcam-quick-size-label" htmlFor="webcam-quick-size">
              <span>{text.settings.cameraSize}</span>
              <span>{settings.webcamSize}px</span>
            </label>
            <input
              id="webcam-quick-size"
              className="webcam-quick-size-slider"
              type="range"
              min={CAMERA_SIZE_MIN}
              max={CAMERA_SIZE_MAX}
              value={settings.webcamSize}
              onChange={(event) => updateWebcamSize(Number(event.target.value))}
            />
            <div className="webcam-quick-size-scale">
              <span>{text.settings.small}</span>
              <span>{text.settings.large}</span>
            </div>
          </div>
        )}

        {/* Live cursor indicator - shows during recording when cursor effect is on */}
        {isRecording && settings.showCursor && recordingFrame &&
         mousePosition.x >= recordingFrame.x &&
         mousePosition.x <= recordingFrame.x + recordingFrame.width &&
         mousePosition.y >= recordingFrame.y &&
         mousePosition.y <= recordingFrame.y + recordingFrame.height && (
          <div
            className="cursor-indicator"
            style={{
              left: mousePosition.x,
              top: mousePosition.y,
              backgroundColor: settings.cursorColor + '80',
            }}
          />
        )}
      </div>

      {showPreferencesSubmenu && createPortal(
        <div
          className="excalicord-preferences-popover"
          role="menu"
          aria-label={text.preferences.menuTitle}
          style={{
            left: preferencesSubmenuPosition.left,
            top: preferencesSubmenuPosition.top,
          }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {preferenceMenuItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`excalicord-preferences-popover-item ${item.selected ? 'selected' : ''}`}
              role="menuitemcheckbox"
              aria-checked={item.selected}
              onClick={(event) => {
                event.stopPropagation();
                item.onSelect();
              }}
            >
              <span className="excalicord-preferences-check" aria-hidden="true">
                {item.selected ? '✓' : ''}
              </span>
              <span className="excalicord-preferences-label">
                {item.label}
              </span>
              {item.shortcut && (
                <span className="excalicord-preferences-shortcut">
                  {item.shortcut}
                </span>
              )}
            </button>
          ))}
        </div>,
        appContainerRef.current ?? document.body,
      )}
      {(showAboutDialog || showGuideDialog) && createPortal(
        <div className="app-dialog-portal" data-theme={editorTheme}>
          {showAboutDialog && (
            <AboutDialog
              language={language}
              onOpenGuide={openGuideDialog}
              onClose={() => setShowAboutDialog(false)}
            />
          )}
          {showGuideDialog && (
            <GuideDialog
              language={language}
              onClose={() => setShowGuideDialog(false)}
            />
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}

export default App;
