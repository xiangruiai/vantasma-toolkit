/**
 * SettingsPanel - Customize recording appearance
 */

import type { ChangeEvent, KeyboardEvent as ReactKeyboardEvent, PointerEvent } from 'react';
import { useEffect, useRef, useState } from 'react';
import './SettingsPanel.css';
import { UI_TEXT, type LanguageCode } from '../i18n';
import {
  DEFAULT_SHORTCUTS,
  SHORTCUT_GROUPS,
  formatShortcut,
  shortcutFromKeyboardEvent,
  type ShortcutActionId,
  type ShortcutGroupId,
  type ShortcutSettings,
} from '../shortcuts';
import { toEvenRecordingDimension } from '../utils/recordingDimensions';

// Background categories
const BACKGROUND_CATEGORIES = ['All', 'Vibrant', 'Pastel', 'Dark', 'Minimal'] as const;

// Background presets - using Unsplash gradient images
const GRADIENT_PRESETS = [
  // === NO WALLPAPER ===
  {
    id: 'no-wallpaper',
    name: 'No Wallpaper',
    value: 'none',
    preview: 'repeating-conic-gradient(#e5e5e5 0% 25%, #fff 0% 50%) 50% / 12px 12px',
    type: 'none',
    category: 'Minimal'
  },
  {
    id: 'white',
    name: 'Clean White',
    value: '#ffffff',
    preview: '#ffffff',
    type: 'solid',
    category: 'Minimal'
  },
  {
    id: 'dark',
    name: 'Dark',
    value: '#1a1a1a',
    preview: '#1a1a1a',
    type: 'solid',
    category: 'Minimal'
  },

  // === VIBRANT (Unsplash images) ===
  {
    id: 'vibrant-1',
    name: 'Purple Pink Waves',
    value: 'url(https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-2',
    name: 'Rainbow Gradient',
    value: 'url(https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-3',
    name: 'Blue Purple Mesh',
    value: 'url(https://images.unsplash.com/photo-1557683316-973673baf926?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557683316-973673baf926?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-4',
    name: 'Colorful Abstract',
    value: 'url(https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-5',
    name: 'Pink Orange Swirl',
    value: 'url(https://images.unsplash.com/photo-1558591710-4b4a1ae0f04d?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1558591710-4b4a1ae0f04d?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-6',
    name: 'Neon Glow',
    value: 'url(https://images.unsplash.com/photo-1614850523459-c2f4c699c52e?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1614850523459-c2f4c699c52e?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-7',
    name: 'Liquid Colors',
    value: 'url(https://images.unsplash.com/photo-1614851099175-e5b30eb6f696?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1614851099175-e5b30eb6f696?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },
  {
    id: 'vibrant-8',
    name: 'Holographic',
    value: 'url(https://images.unsplash.com/photo-1620121692029-d088224ddc74?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1620121692029-d088224ddc74?w=200&q=60)',
    type: 'image',
    category: 'Vibrant'
  },

  // === PASTEL ===
  {
    id: 'pastel-1',
    name: 'Soft Pink Blue',
    value: 'url(https://images.unsplash.com/photo-1557682224-5b8590cd9ec5?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557682224-5b8590cd9ec5?w=200&q=60)',
    type: 'image',
    category: 'Pastel'
  },
  {
    id: 'pastel-2',
    name: 'Dreamy Clouds',
    value: 'url(https://images.unsplash.com/photo-1557683311-eac922347aa1?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557683311-eac922347aa1?w=200&q=60)',
    type: 'image',
    category: 'Pastel'
  },
  {
    id: 'pastel-3',
    name: 'Cotton Candy',
    value: 'url(https://images.unsplash.com/photo-1579546929662-711aa81148cf?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1579546929662-711aa81148cf?w=200&q=60)',
    type: 'image',
    category: 'Pastel'
  },
  {
    id: 'pastel-4',
    name: 'Soft Gradient',
    value: 'url(https://images.unsplash.com/photo-1557682260-96773eb01377?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557682260-96773eb01377?w=200&q=60)',
    type: 'image',
    category: 'Pastel'
  },
  {
    id: 'pastel-5',
    name: 'Lavender Dream',
    value: 'url(https://images.unsplash.com/photo-1618556450994-a6a128ef0d9d?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1618556450994-a6a128ef0d9d?w=200&q=60)',
    type: 'image',
    category: 'Pastel'
  },
  {
    id: 'pastel-6',
    name: 'Peachy',
    value: 'url(https://images.unsplash.com/photo-1618556450991-2f1af64e8191?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1618556450991-2f1af64e8191?w=200&q=60)',
    type: 'image',
    category: 'Pastel'
  },

  // === DARK ===
  {
    id: 'dark-1',
    name: 'Deep Purple',
    value: 'url(https://images.unsplash.com/photo-1557683304-673a23048d34?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557683304-673a23048d34?w=200&q=60)',
    type: 'image',
    category: 'Dark'
  },
  {
    id: 'dark-2',
    name: 'Midnight Blue',
    value: 'url(https://images.unsplash.com/photo-1557682268-e3955ed5d83f?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1557682268-e3955ed5d83f?w=200&q=60)',
    type: 'image',
    category: 'Dark'
  },
  {
    id: 'dark-3',
    name: 'Galaxy',
    value: 'url(https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=200&q=60)',
    type: 'image',
    category: 'Dark'
  },
  {
    id: 'dark-4',
    name: 'Aurora Dark',
    value: 'url(https://images.unsplash.com/photo-1519751138087-5bf79df62d5b?w=1920&q=80)',
    preview: 'url(https://images.unsplash.com/photo-1519751138087-5bf79df62d5b?w=200&q=60)',
    type: 'image',
    category: 'Dark'
  },
];

// Aspect ratio presets
const ASPECT_RATIOS = [
  { id: '16:9', name: '16:9', desc: 'YouTube', width: 1920, height: 1080 },
  { id: '4:3', name: '4:3', desc: 'Classic', width: 1440, height: 1080 },
  { id: '3:4', name: '3:4', desc: 'RedNote', width: 1080, height: 1440 },
  { id: '9:16', name: '9:16', desc: 'TikTok', width: 1080, height: 1920 },
  { id: '1:1', name: '1:1', desc: 'Square', width: 1080, height: 1080 },
  { id: 'custom', name: 'Custom', desc: 'Your size', width: 1920, height: 1080 },
];

export interface RecordingSettings {
  aspectRatio: string;
  customWidth: number;
  customHeight: number;
  background: string;
  backgroundId: string;
  backgroundType: 'solid' | 'gradient' | 'image' | 'none';
  backgroundScale: number;
  backgroundOffsetX: number;
  backgroundOffsetY: number;
  webcamSize: number;
  webcamShape: 'circle' | 'square';
  padding: number;
  cornerRadius: number;
  showCursor: boolean;
  cursorColor: string;
  // Camera settings
  showCamera: boolean;
  useMicrophone: boolean;
  enableSound: boolean;
  cameraDeviceId: string;
  microphoneDeviceId: string;
  audioOutputDeviceId: string;
  cameraPersonCenter: boolean;
  cameraPortrait: boolean;
  cameraStudioLight: boolean;
  cameraEdgeLight: boolean;
  cameraEdgeLightMode: 'manual' | 'auto';
  cameraEdgeLightIntensity: number;
  cameraEdgeLightSize: number;
  cameraEdgeLightColor: 'warm' | 'neutral' | 'cool';
  cameraReactions: boolean;
  cameraBackground: boolean;
  cameraBackgroundMode: 'blur' | 'studio' | 'gradient' | 'soft' | 'accent';
  cameraMattingThreshold: number;
  cameraMattingSoftness: number;
  cameraDeskView: boolean;
  microphoneMode: 'standard' | 'voiceIsolation' | 'wideSpectrum';
}

export type DevicePermissionState = 'checking' | 'granted' | 'prompt' | 'denied' | 'unsupported';

export interface DevicePermissionStatus {
  camera: DevicePermissionState;
  microphone: DevicePermissionState;
}

export interface MediaDeviceOption {
  deviceId: string;
  groupId: string;
  kind: MediaDeviceKind;
  label: string;
}

type PreviewImageSize = {
  width: number;
  height: number;
};

type PreviewBoxSize = {
  width: number;
  height: number;
};

type BackgroundDragState = {
  pointerId: number;
  startX: number;
  startY: number;
  offsetX: number;
  offsetY: number;
};

interface SettingsPanelProps {
  isOpen: boolean;
  scope: SettingsPanelScope;
  settings: RecordingSettings;
  shortcuts: ShortcutSettings;
  onSettingsChange: (settings: RecordingSettings) => void;
  onShortcutsChange: (shortcuts: ShortcutSettings) => void;
  onClose: () => void;
  language: LanguageCode;
  devicePermissions: DevicePermissionStatus;
  hasCameraStream: boolean;
  hasMicrophoneStream: boolean;
  cameraPreviewStream: MediaStream | null;
  mediaDevices: MediaDeviceOption[];
  audioOutputSupported: boolean;
}

const CURSOR_COLORS = [
  { id: 'red', color: '#ef4444' },
  { id: 'orange', color: '#f97316' },
  { id: 'yellow', color: '#eab308' },
  { id: 'blue', color: '#3b82f6' },
  { id: 'purple', color: '#a855f7' },
  { id: 'pink', color: '#ec4899' },
];

type SettingsTab = 'recording' | 'camera' | 'audio' | 'cursor' | 'shortcuts';
export type SettingsPanelScope = 'recording' | 'preferences';

const clampBackgroundOffset = (value: number) => Math.max(-100, Math.min(100, value));
export const CAMERA_SIZE_MIN = 100;
export const CAMERA_SIZE_MAX = 280;

const getCameraPreviewSize = (size: number) => {
  return Math.round(Math.max(CAMERA_SIZE_MIN, Math.min(CAMERA_SIZE_MAX, size)));
};

const getBackgroundUrl = (background: string) => {
  const urlMatch = background.match(/url\(['"]?([^'"]+)['"]?\)/);
  return urlMatch?.[1] || '';
};

function CameraSettingsPreview({
  stream,
  enabled,
  shape,
  size,
  labels,
}: {
  stream: MediaStream | null;
  enabled: boolean;
  shape: RecordingSettings['webcamShape'];
  size: number;
  labels: {
    off: string;
    waiting: string;
    live: string;
  };
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const hasLiveVideo = enabled && Boolean(stream?.getVideoTracks().some(track => track.readyState === 'live'));
  const previewSize = getCameraPreviewSize(size);

  useEffect(() => {
    const video = videoRef.current;

    if (!video) {
      return;
    }

    if (!hasLiveVideo || !stream) {
      video.srcObject = null;
      return;
    }

    video.srcObject = stream;
    void video.play().catch(() => undefined);
  }, [hasLiveVideo, stream]);

  return (
    <div className="camera-preview-stage">
      <div
        className={`camera-preview-feed ${shape} ${hasLiveVideo ? 'is-live' : 'is-empty'}`}
        style={{
          width: `${previewSize}px`,
          height: `${previewSize}px`,
        }}
      >
        {hasLiveVideo ? (
          <video
            ref={videoRef}
            className="camera-preview-video"
            autoPlay
            playsInline
            muted
          />
        ) : (
          <span>{enabled ? labels.waiting : labels.off}</span>
        )}
      </div>
    </div>
  );
}

function SettingsPanel({
  isOpen,
  scope,
  settings,
  shortcuts,
  onSettingsChange,
  onShortcutsChange,
  onClose,
  language,
  devicePermissions,
  hasCameraStream,
  hasMicrophoneStream,
  cameraPreviewStream,
  mediaDevices,
  audioOutputSupported,
}: SettingsPanelProps) {
  const text = UI_TEXT[language].settings;
  const categoryLabels = text.categories as Record<string, string>;
  const aspectDescriptions = text.aspectDescriptions as Record<string, string>;
  const backgroundNames = text.backgrounds as Record<string, string>;
  const shortcutGroupLabels = text.shortcutGroups as Record<ShortcutGroupId, string>;
  const shortcutActionLabels = text.shortcutActions as Record<ShortcutActionId, string>;
  const [customWidth, setCustomWidth] = useState(settings.customWidth);
  const [customHeight, setCustomHeight] = useState(settings.customHeight);
  const [bgCategory, setBgCategory] = useState<typeof BACKGROUND_CATEGORIES[number]>('All');
  const [activeTab, setActiveTab] = useState<SettingsTab>('recording');
  const [recordingShortcutAction, setRecordingShortcutAction] = useState<ShortcutActionId | null>(null);
  const controlsColumnRef = useRef<HTMLDivElement | null>(null);
  const previewBackdropRef = useRef<HTMLDivElement | null>(null);
  const backgroundFileInputRef = useRef<HTMLInputElement | null>(null);
  const backgroundDragRef = useRef<BackgroundDragState | null>(null);
  const [previewImageSize, setPreviewImageSize] = useState<PreviewImageSize | null>(null);
  const [previewBoxSize, setPreviewBoxSize] = useState<PreviewBoxSize | null>(null);
  const allTabs: Array<{ id: SettingsTab; label: string; icon: string }> = [
    { id: 'recording', label: text.recordingTab, icon: '●' },
    { id: 'camera', label: text.cameraTab, icon: '▣' },
    { id: 'audio', label: text.audioTab, icon: '◉' },
    { id: 'cursor', label: text.cursorTab, icon: '⌖' },
    { id: 'shortcuts', label: text.shortcutsTab, icon: '⌘' },
  ];
  const tabs = scope === 'preferences'
    ? allTabs.filter(tab => tab.id === 'shortcuts')
    : allTabs.filter(tab => tab.id !== 'shortcuts');
  const defaultTab = scope === 'preferences' ? 'shortcuts' : 'recording';
  const activeTabInScope = tabs.some(tab => tab.id === activeTab) ? activeTab : defaultTab;
  const hasRecordingPreview = activeTabInScope === 'recording';
  const hasCameraPreview = activeTabInScope === 'camera';
  const hasVisualPreview = hasRecordingPreview || hasCameraPreview;
  const panelTitle = scope === 'preferences' ? text.shortcutsTab : text.title;
  const backgroundUrl = getBackgroundUrl(settings.background);
  const isImageBackground = settings.backgroundType === 'image' && Boolean(backgroundUrl);

  useEffect(() => {
    controlsColumnRef.current?.scrollTo({ top: 0 });
  }, [activeTabInScope]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setActiveTab(scope === 'preferences' ? 'shortcuts' : 'recording');
    setRecordingShortcutAction(null);
  }, [isOpen, scope]);

  useEffect(() => {
    if (!isOpen || !hasRecordingPreview) {
      return;
    }

    const node = previewBackdropRef.current;
    if (!node) {
      return;
    }

    const updatePreviewBox = () => {
      const rect = node.getBoundingClientRect();
      setPreviewBoxSize({ width: rect.width, height: rect.height });
    };

    updatePreviewBox();
    const resizeObserver = new ResizeObserver(updatePreviewBox);
    resizeObserver.observe(node);

    return () => {
      resizeObserver.disconnect();
    };
  }, [hasRecordingPreview, isOpen]);

  useEffect(() => {
    if (!isImageBackground) {
      setPreviewImageSize(null);
      return;
    }

    let cancelled = false;
    const image = new Image();
    image.onload = () => {
      if (!cancelled) {
        setPreviewImageSize({
          width: image.naturalWidth,
          height: image.naturalHeight,
        });
      }
    };
    image.onerror = () => {
      if (!cancelled) {
        setPreviewImageSize(null);
      }
    };
    image.src = backgroundUrl;

    return () => {
      cancelled = true;
    };
  }, [backgroundUrl, isImageBackground]);

  if (!isOpen) return null;

  // Filter backgrounds by category
  const filteredBackgrounds = bgCategory === 'All'
    ? GRADIENT_PRESETS
    : GRADIENT_PRESETS.filter(g => g.category === bgCategory);

  // Pick a random background
  const pickRandomBackground = () => {
    const randomIndex = Math.floor(Math.random() * GRADIENT_PRESETS.length);
    const randomBg = GRADIENT_PRESETS[randomIndex];
    onSettingsChange({
      ...settings,
      background: randomBg.value,
      backgroundId: randomBg.id,
      backgroundType: randomBg.type as 'solid' | 'gradient' | 'image' | 'none',
      backgroundScale: 1,
      backgroundOffsetX: 0,
      backgroundOffsetY: 0,
    });
  };

  const handleAspectChange = (ratioId: string) => {
    const ratio = ASPECT_RATIOS.find(r => r.id === ratioId);
    if (ratio) {
      onSettingsChange({
        ...settings,
        aspectRatio: ratioId,
        customWidth: ratio.width,
        customHeight: ratio.height,
        ...(isImageBackground
          ? {
              backgroundScale: 1,
              backgroundOffsetX: 0,
              backgroundOffsetY: 0,
            }
          : {}),
      });
      setCustomWidth(ratio.width);
      setCustomHeight(ratio.height);
    }
  };

  const handleCustomDimension = (dimension: 'width' | 'height', value: number) => {
    const sanitizedValue = toEvenRecordingDimension(value);

    if (dimension === 'width') {
      setCustomWidth(sanitizedValue);
      onSettingsChange({
        ...settings,
        customWidth: sanitizedValue,
        customHeight: toEvenRecordingDimension(settings.customHeight),
        aspectRatio: 'custom',
        ...(isImageBackground
          ? {
              backgroundScale: 1,
              backgroundOffsetX: 0,
              backgroundOffsetY: 0,
            }
          : {}),
      });
    } else {
      setCustomHeight(sanitizedValue);
      onSettingsChange({
        ...settings,
        customWidth: toEvenRecordingDimension(settings.customWidth),
        customHeight: sanitizedValue,
        aspectRatio: 'custom',
        ...(isImageBackground
          ? {
              backgroundScale: 1,
              backgroundOffsetX: 0,
              backgroundOffsetY: 0,
            }
          : {}),
      });
    }
  };

  const handleBackgroundChange = (gradientId: string) => {
    const gradient = GRADIENT_PRESETS.find(g => g.id === gradientId);
    if (gradient) {
      onSettingsChange({
        ...settings,
        background: gradient.value,
        backgroundId: gradientId,
        backgroundType: gradient.type as 'solid' | 'gradient' | 'image' | 'none',
        backgroundScale: 1,
        backgroundOffsetX: 0,
        backgroundOffsetY: 0,
      });
    }
  };

  const handleBackgroundUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';

    if (!file || !file.type.startsWith('image/')) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';

      if (!result) {
        return;
      }

      onSettingsChange({
        ...settings,
        background: `url("${result}")`,
        backgroundId: `upload-${Date.now()}`,
        backgroundType: 'image',
        backgroundScale: 1,
        backgroundOffsetX: 0,
        backgroundOffsetY: 0,
      });
    };
    reader.readAsDataURL(file);
  };

  const fitBackgroundToRecordingSize = () => {
    onSettingsChange({
      ...settings,
      backgroundScale: 1,
      backgroundOffsetX: 0,
      backgroundOffsetY: 0,
    });
  };

  const getPermissionLabel = (status: DevicePermissionState) => {
    switch (status) {
      case 'granted':
        return text.permissionGranted;
      case 'prompt':
        return text.permissionPrompt;
      case 'denied':
        return text.permissionDenied;
      case 'unsupported':
        return text.permissionUnsupported;
      default:
        return text.permissionChecking;
    }
  };

  const cameraStatus = hasCameraStream ? 'granted' : devicePermissions.camera;
  const microphoneStatus = hasMicrophoneStream ? 'granted' : devicePermissions.microphone;
  const soundStatus: DevicePermissionState = audioOutputSupported
    ? (settings.enableSound ? 'granted' : 'prompt')
    : 'unsupported';
  const selectedBackground = GRADIENT_PRESETS.find(g => g.id === settings.backgroundId);
  const selectedPreviewBackground = selectedBackground?.preview || settings.background;
  const selectedRatio = ASPECT_RATIOS.find(r => r.id === settings.aspectRatio);
  const previewAspectWidth = selectedRatio?.width || settings.customWidth;
  const previewAspectHeight = selectedRatio?.height || settings.customHeight;
  const previewPadding = Math.round(Math.max(0, Math.min(settings.padding / 8, 18)));
  const previewCornerRadius = Math.round(Math.max(0, Math.min(settings.cornerRadius / 2, 24)));
  const previewCameraSize = Math.round(Math.max(18, Math.min(settings.webcamSize / 7, 38)));
  const cameraDevices = mediaDevices.filter(device => device.kind === 'videoinput' && device.deviceId !== 'default');
  const microphoneDevices = mediaDevices.filter(device => device.kind === 'audioinput' && device.deviceId !== 'default');
  const audioOutputDevices = mediaDevices.filter(device => device.kind === 'audiooutput' && device.deviceId !== 'default');
  const shortcutConflictMap = Object.entries(shortcuts).reduce<Record<string, number>>((acc, [, shortcut]) => {
    if (shortcut) {
      acc[shortcut] = (acc[shortcut] || 0) + 1;
    }

    return acc;
  }, {});

  const updateShortcut = (action: ShortcutActionId, shortcut: string) => {
    onShortcutsChange({
      ...shortcuts,
      [action]: shortcut,
    });
  };

  const handleShortcutCapture = (event: ReactKeyboardEvent<HTMLButtonElement>, action: ShortcutActionId) => {
    if (recordingShortcutAction !== action) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    if ((event.key === 'Backspace' || event.key === 'Delete') && !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey) {
      updateShortcut(action, '');
      setRecordingShortcutAction(null);
      return;
    }

    const nextShortcut = shortcutFromKeyboardEvent(event);

    if (!nextShortcut) {
      return;
    }

    updateShortcut(action, nextShortcut);
    setRecordingShortcutAction(null);
  };

  const getDeviceName = (device: MediaDeviceOption, fallback: string, index: number) => {
    const name = device.label || `${fallback} ${index + 1}`;
    return /iphone|continuity/i.test(name) ? `${name} · ${text.continuityDevice}` : name;
  };

  const renderDeviceOptions = (devices: MediaDeviceOption[], fallback: string) => (
    <>
      <option value="">{text.defaultDevice}</option>
      {devices.map((device, index) => (
        <option key={`${device.kind}-${device.deviceId}`} value={device.deviceId}>
          {getDeviceName(device, fallback, index)}
        </option>
      ))}
    </>
  );
  const previewBackdropStyle = isImageBackground
    ? {
        backgroundColor: '#f5f5f4',
        aspectRatio: `${previewAspectWidth} / ${previewAspectHeight}`,
      }
    : {
        background: selectedPreviewBackground,
        aspectRatio: `${previewAspectWidth} / ${previewAspectHeight}`,
      };
  const getPreviewImageStyle = () => {
    if (!previewImageSize || !previewBoxSize) {
      return undefined;
    }

    const fitScale = Math.max(
      previewBoxSize.width / previewImageSize.width,
      previewBoxSize.height / previewImageSize.height,
    ) * settings.backgroundScale;
    const width = previewImageSize.width * fitScale;
    const height = previewImageSize.height * fitScale;
    const maxOffsetX = Math.max(0, (width - previewBoxSize.width) / 2);
    const maxOffsetY = Math.max(0, (height - previewBoxSize.height) / 2);
    const x = (previewBoxSize.width - width) / 2
      + (settings.backgroundOffsetX / 100) * maxOffsetX;
    const y = (previewBoxSize.height - height) / 2
      + (settings.backgroundOffsetY / 100) * maxOffsetY;

    return {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${x}px, ${y}px)`,
    };
  };
  const updateBackgroundOffset = (event: PointerEvent<HTMLDivElement>) => {
    const dragState = backgroundDragRef.current;
    const box = previewBoxSize;

    if (!dragState || !box) {
      return;
    }

    const nextOffsetX = clampBackgroundOffset(
      dragState.offsetX + ((event.clientX - dragState.startX) / box.width) * 200,
    );
    const nextOffsetY = clampBackgroundOffset(
      dragState.offsetY + ((event.clientY - dragState.startY) / box.height) * 200,
    );

    onSettingsChange({
      ...settings,
      backgroundOffsetX: nextOffsetX,
      backgroundOffsetY: nextOffsetY,
    });
  };
  const handleBackgroundPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!isImageBackground || event.button !== 0) {
      return;
    }

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    backgroundDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: settings.backgroundOffsetX,
      offsetY: settings.backgroundOffsetY,
    };
  };
  const handleBackgroundPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (backgroundDragRef.current?.pointerId !== event.pointerId) {
      return;
    }

    updateBackgroundOffset(event);
  };
  const handleBackgroundPointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    if (backgroundDragRef.current?.pointerId !== event.pointerId) {
      return;
    }

    updateBackgroundOffset(event);
    backgroundDragRef.current = null;
  };

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={e => e.stopPropagation()}>
        <div className="settings-header">
          <h2>{panelTitle}</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className={`settings-body ${hasVisualPreview ? 'with-recording-preview' : ''}`}>
            <nav className="settings-nav" aria-label={panelTitle}>
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  type="button"
                  className={`settings-nav-item ${activeTabInScope === tab.id ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                <span className="settings-nav-icon">{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </nav>

          {hasVisualPreview && (
            <aside className="settings-preview-pane">
              <div className="recording-preview-title">
                {hasCameraPreview ? text.cameraPreview : text.recordingPreview}
              </div>
              {hasCameraPreview ? (
                <div className="camera-preview-shell">
                  <CameraSettingsPreview
                    stream={cameraPreviewStream}
                    enabled={settings.showCamera}
                    shape={settings.webcamShape}
                    size={settings.webcamSize}
                    labels={{
                      off: text.cameraPreviewOff,
                      waiting: text.cameraPreviewWaiting,
                      live: text.cameraPreviewLive,
                    }}
                  />
                </div>
              ) : (
                <div
                  ref={previewBackdropRef}
                  className={`recording-preview-backdrop ${isImageBackground ? 'draggable-background' : ''}`}
                  style={previewBackdropStyle}
                  onPointerDown={handleBackgroundPointerDown}
                  onPointerMove={handleBackgroundPointerMove}
                  onPointerUp={handleBackgroundPointerEnd}
                  onPointerCancel={handleBackgroundPointerEnd}
                >
                  {isImageBackground && (
                    <img
                      className="recording-preview-background-image"
                      src={selectedBackground?.preview ? getBackgroundUrl(selectedBackground.preview) : backgroundUrl}
                      alt=""
                      draggable={false}
                      style={getPreviewImageStyle()}
                    />
                  )}
                  <div
                    className="recording-preview-surface"
                    style={{
                      inset: `${previewPadding}px`,
                      borderRadius: `${previewCornerRadius}px`,
                    }}
                  >
                    <div className="recording-preview-content">
                      <span className="preview-line long" />
                      <span className="preview-line medium" />
                      <span className="preview-line short" />
                      {settings.showCursor && (
                        <span
                          className="preview-cursor"
                          style={{ backgroundColor: settings.cursorColor }}
                        />
                      )}
                      {settings.showCamera && (
                        <span
                          className={`preview-camera ${settings.webcamShape}`}
                          style={{
                            width: `${previewCameraSize}px`,
                            height: `${previewCameraSize}px`,
                          }}
                        />
                      )}
                    </div>
                  </div>
                </div>
              )}
            </aside>
          )}

          <div className="settings-controls-column" ref={controlsColumnRef}>
            {activeTabInScope === 'recording' && (
              <>
                <div className="settings-section">
                  <h3>{text.aspectRatio}</h3>
                  <div className="aspect-grid">
                    {ASPECT_RATIOS.map(ratio => (
                      <button
                        key={ratio.id}
                        className={`aspect-btn ${settings.aspectRatio === ratio.id ? 'active' : ''}`}
                        onClick={() => handleAspectChange(ratio.id)}
                      >
                        <span className="ratio-name">
                          {ratio.id === 'custom' && language === 'zh-CN' ? '自定义' : ratio.name}
                        </span>
                        <span className="ratio-desc">{aspectDescriptions[ratio.id] || ratio.desc}</span>
                      </button>
                    ))}
                  </div>

                  {settings.aspectRatio === 'custom' && (
                    <div className="custom-dimensions">
                      <label>
                        {text.width}
                        <input
                          type="number"
                          value={customWidth}
                          onChange={e => handleCustomDimension('width', parseInt(e.target.value) || 1920)}
                          min={640}
                          max={3840}
                        />
                      </label>
                      <span className="dimension-x">×</span>
                      <label>
                        {text.height}
                        <input
                          type="number"
                          value={customHeight}
                          onChange={e => handleCustomDimension('height', parseInt(e.target.value) || 1080)}
                          min={480}
                          max={2160}
                        />
                      </label>
                    </div>
                  )}
                </div>

                <div className="settings-section">
                  <h3>{text.background}</h3>
                  <input
                    ref={backgroundFileInputRef}
                    type="file"
                    accept="image/*"
                    className="background-upload-input"
                    onChange={handleBackgroundUpload}
                  />
                  <div className="background-actions">
                    <button
                      type="button"
                      className="background-upload-btn"
                      onClick={() => backgroundFileInputRef.current?.click()}
                    >
                      {text.uploadBackground}
                    </button>
                    {isImageBackground && (
                      <button
                        type="button"
                        className="background-reset-btn"
                        onClick={fitBackgroundToRecordingSize}
                      >
                        {text.fitToRecordingSize}
                      </button>
                    )}
                  </div>
                  {isImageBackground && (
                    <div className="background-adjust-panel">
                      <div className="background-adjust-heading">{text.dragBackground}</div>
                      <input
                        type="range"
                        min={1}
                        max={3}
                        step={0.05}
                        value={settings.backgroundScale}
                        onChange={e => onSettingsChange({
                          ...settings,
                          backgroundScale: parseFloat(e.target.value),
                        })}
                        className="slider"
                      />
                      <div className="slider-labels">
                        <span>{text.fit}</span>
                        <span>{text.zoom}</span>
                      </div>
                    </div>
                  )}
                  <div className="bg-category-tabs">
                    {BACKGROUND_CATEGORIES.map(cat => (
                      <button
                        key={cat}
                        className={`bg-category-tab ${bgCategory === cat ? 'active' : ''}`}
                        onClick={() => setBgCategory(cat)}
                      >
                        {categoryLabels[cat] || cat}
                      </button>
                    ))}
                  </div>

                  <button className="random-bg-btn" onClick={pickRandomBackground}>
                    {text.randomWallpaper}
                  </button>

                  <div className="gradient-grid">
                    {filteredBackgrounds.map(gradient => (
                      <button
                        key={gradient.id}
                        className={`gradient-btn ${settings.backgroundId === gradient.id ? 'active' : ''}`}
                        style={{ background: gradient.preview }}
                        onClick={() => handleBackgroundChange(gradient.id)}
                        title={backgroundNames[gradient.id] || gradient.name}
                      >
                        {settings.backgroundId === gradient.id && <span className="check">✓</span>}
                      </button>
                    ))}
                  </div>
                  <p className="gradient-name">
                    {(() => {
                      const selected = GRADIENT_PRESETS.find(g => g.id === settings.backgroundId);
                      return selected ? backgroundNames[selected.id] || selected.name : text.uploadedBackground;
                    })()}
                  </p>
                </div>

                <div className="settings-section">
                  <h3>{text.cornerRadius}: {settings.cornerRadius}px</h3>
                  <input
                    type="range"
                    min={0}
                    max={40}
                    value={settings.cornerRadius}
                    onChange={e => onSettingsChange({ ...settings, cornerRadius: parseInt(e.target.value) })}
                    className="slider"
                  />
                  <div className="slider-labels">
                    <span>{text.sharp}</span>
                    <span>{text.rounded}</span>
                  </div>
                </div>

                <div className="settings-section">
                  <h3>{text.canvasPadding}: {settings.padding}px</h3>
                  <input
                    type="range"
                    min={0}
                    max={120}
                    value={settings.padding}
                    onChange={e => onSettingsChange({ ...settings, padding: parseInt(e.target.value) })}
                    className="slider"
                  />
                  <div className="slider-labels">
                    <span>{text.none}</span>
                    <span>{text.large}</span>
                  </div>
                </div>
              </>
            )}

            {activeTabInScope === 'camera' && (
              <div className="settings-section camera-settings-section">
                <h3>{text.cameraTab}</h3>
                <div className="device-row camera-source-card">
                  <span className="device-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" focusable="false">
                      <path d="M4 7h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z" />
                      <path d="m16 10 5-3v10l-5-3" />
                    </svg>
                  </span>
                  <div className="device-copy">
                    <span className="device-title">{text.camera}</span>
                    <span className={`permission-badge ${cameraStatus}`}>
                      {getPermissionLabel(cameraStatus)}
                    </span>
                  </div>
                  <label className="toggle-label compact-toggle" aria-label={text.showCamera}>
                    <input
                      type="checkbox"
                      checked={settings.showCamera}
                      onChange={e => onSettingsChange({ ...settings, showCamera: e.target.checked })}
                    />
                    <span className="toggle-switch"></span>
                  </label>
                  <div className="device-select-wrap camera-source-select">
                    <label className="device-select-label" htmlFor="camera-device-select">
                      {text.videoSource}
                    </label>
                    <select
                      id="camera-device-select"
                      className="device-select"
                      value={settings.cameraDeviceId}
                      disabled={!settings.showCamera}
                      onChange={e => onSettingsChange({ ...settings, cameraDeviceId: e.target.value })}
                    >
                      {renderDeviceOptions(cameraDevices, text.camera)}
                    </select>
                  </div>

                  <div className="camera-display-options">
                    <div className="camera-option-block">
                      <div className="camera-option-heading">{text.cameraShape}</div>
                      <div className="camera-shape-toggle">
                        <button
                          type="button"
                          className={`camera-shape-btn ${settings.webcamShape === 'circle' ? 'active' : ''}`}
                          onClick={() => onSettingsChange({ ...settings, webcamShape: 'circle' })}
                        >
                          <span className="camera-shape-icon circle" aria-hidden="true" />
                          <span>{text.circle}</span>
                        </button>
                        <button
                          type="button"
                          className={`camera-shape-btn ${settings.webcamShape === 'square' ? 'active' : ''}`}
                          onClick={() => onSettingsChange({ ...settings, webcamShape: 'square' })}
                        >
                          <span className="camera-shape-icon square" aria-hidden="true" />
                          <span>{text.square}</span>
                        </button>
                      </div>
                    </div>

                    <div className="camera-option-block">
                      <div className="camera-option-heading">
                        {text.cameraSize}: {settings.webcamSize}px
                      </div>
                      <input
                        type="range"
                        min={CAMERA_SIZE_MIN}
                        max={CAMERA_SIZE_MAX}
                        value={settings.webcamSize}
                        onChange={e => onSettingsChange({ ...settings, webcamSize: parseInt(e.target.value) })}
                        className="slider camera-size-slider"
                      />
                      <div className="slider-labels">
                        <span>{text.small}</span>
                        <span>{text.large}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTabInScope === 'audio' && (
              <div className="settings-section">
                <h3>{text.audioTab}</h3>
                <div className="device-permissions">
                  <div className="device-row">
                    <span className="device-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" focusable="false">
                        <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" />
                        <path d="M5 11a7 7 0 0 0 14 0" />
                        <path d="M12 18v3" />
                        <path d="M8 21h8" />
                      </svg>
                    </span>
                    <div className="device-copy">
                      <span className="device-title">{text.microphone}</span>
                      <span className={`permission-badge ${microphoneStatus}`}>
                        {getPermissionLabel(microphoneStatus)}
                      </span>
                    </div>
                    <label className="toggle-label compact-toggle" aria-label={text.useMicrophone}>
                      <input
                        type="checkbox"
                        checked={settings.useMicrophone}
                        onChange={e => onSettingsChange({ ...settings, useMicrophone: e.target.checked })}
                      />
                      <span className="toggle-switch"></span>
                    </label>
                    <div className="device-select-wrap">
                      <label className="device-select-label" htmlFor="microphone-device-select">
                        {text.audioSource}
                      </label>
                      <select
                        id="microphone-device-select"
                        className="device-select"
                        value={settings.microphoneDeviceId}
                        disabled={!settings.useMicrophone}
                        onChange={e => onSettingsChange({ ...settings, microphoneDeviceId: e.target.value })}
                      >
                        {renderDeviceOptions(microphoneDevices, text.microphone)}
                      </select>
                    </div>
                  </div>

                  <div className="device-row">
                    <span className="device-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" focusable="false">
                        <path d="M4 9v6h4l5 4V5L8 9H4Z" />
                        <path d="M17 9.5a4 4 0 0 1 0 5" />
                        <path d="M20 7a8 8 0 0 1 0 10" />
                      </svg>
                    </span>
                    <div className="device-copy">
                      <span className="device-title">{text.sound}</span>
                      <span className={`permission-badge ${soundStatus}`}>
                        {audioOutputSupported
                          ? (settings.enableSound ? text.soundEnabled : text.soundOff)
                          : text.soundOutputUnsupported}
                      </span>
                    </div>
                    <label className="toggle-label compact-toggle" aria-label={text.enableSound}>
                      <input
                        type="checkbox"
                        checked={settings.enableSound}
                        onChange={e => onSettingsChange({ ...settings, enableSound: e.target.checked })}
                      />
                      <span className="toggle-switch"></span>
                    </label>
                    <div className="device-select-wrap">
                      <label className="device-select-label" htmlFor="sound-device-select">
                        {text.soundSource}
                      </label>
                      <select
                        id="sound-device-select"
                        className="device-select"
                        value={settings.audioOutputDeviceId}
                        disabled={!settings.enableSound || !audioOutputSupported}
                        onChange={e => onSettingsChange({ ...settings, audioOutputDeviceId: e.target.value })}
                      >
                        {renderDeviceOptions(audioOutputDevices, text.sound)}
                      </select>
                    </div>
                  </div>

                  <div className="microphone-mode-row">
                    <span className="microphone-mode-label">{text.microphoneMode}</span>
                    <select
                      className="device-select microphone-mode-select"
                      value={settings.microphoneMode}
                      onChange={e => onSettingsChange({
                        ...settings,
                        microphoneMode: e.target.value as RecordingSettings['microphoneMode'],
                      })}
                    >
                      <option value="standard">{text.microphoneModeStandard}</option>
                      <option value="voiceIsolation">{text.microphoneModeVoiceIsolation}</option>
                      <option value="wideSpectrum">{text.microphoneModeWideSpectrum}</option>
                    </select>
                  </div>

                </div>
              </div>
            )}

            {activeTabInScope === 'cursor' && (
              <div className="settings-section">
                <h3>{text.mouseCursorEffect}</h3>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={settings.showCursor}
                    onChange={e => onSettingsChange({ ...settings, showCursor: e.target.checked })}
                  />
                  <span className="toggle-switch"></span>
                  {text.showCursor}
                </label>

                {settings.showCursor && (
                  <div className="cursor-colors">
                    <span className="color-label">{text.cursorColor}</span>
                    {CURSOR_COLORS.map(c => (
                      <button
                        key={c.id}
                        className={`color-btn ${settings.cursorColor === c.color ? 'active' : ''}`}
                        style={{ background: c.color }}
                        onClick={() => onSettingsChange({ ...settings, cursorColor: c.color })}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTabInScope === 'shortcuts' && (
              <div className="settings-section shortcuts-settings-section">
                <div className="shortcuts-heading-row">
                  <div>
                    <h3>{text.shortcutsTab}</h3>
                    <p className="shortcuts-intro">{text.shortcutsIntro}</p>
                  </div>
                  <button
                    type="button"
                    className="shortcut-reset-btn"
                    onClick={() => {
                      onShortcutsChange(DEFAULT_SHORTCUTS);
                      setRecordingShortcutAction(null);
                    }}
                  >
                    {text.shortcutResetAll}
                  </button>
                </div>

                <div className="shortcut-groups">
                  {SHORTCUT_GROUPS.map((group) => (
                    <section className="shortcut-group" key={group.id}>
                      <div className="shortcut-group-title">
                        {shortcutGroupLabels[group.id]}
                      </div>
                      <div className="shortcut-list">
                        {group.actions.map((action) => {
                          const shortcut = shortcuts[action];
                          const hasConflict = Boolean(shortcut) && shortcutConflictMap[shortcut] > 1;
                          const isRecordingShortcut = recordingShortcutAction === action;

                          return (
                            <div className={`shortcut-row ${hasConflict ? 'has-conflict' : ''}`} key={action}>
                              <div className="shortcut-action-copy">
                                <span className="shortcut-action-label">
                                  {shortcutActionLabels[action]}
                                </span>
                                {hasConflict && (
                                  <span className="shortcut-conflict">
                                    {text.shortcutConflict}
                                  </span>
                                )}
                              </div>
                              <button
                                type="button"
                                className={`shortcut-capture-btn ${isRecordingShortcut ? 'recording' : ''} ${!shortcut ? 'empty' : ''}`}
                                onClick={() => setRecordingShortcutAction(action)}
                                onKeyDown={(event) => handleShortcutCapture(event, action)}
                              >
                                {isRecordingShortcut
                                  ? text.shortcutRecorderHint
                                  : formatShortcut(shortcut, language)}
                              </button>
                              <button
                                type="button"
                                className="shortcut-clear-btn"
                                onClick={() => {
                                  updateShortcut(action, '');
                                  if (recordingShortcutAction === action) {
                                    setRecordingShortcutAction(null);
                                  }
                                }}
                              >
                                {text.shortcutClear}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              </div>
            )}

            <button className="done-btn" onClick={onClose}>
              {text.done}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default SettingsPanel;
export { GRADIENT_PRESETS, ASPECT_RATIOS };
