/**
 * RecordingControls - Native record dock
 */

import { useCallback, useState, useEffect, useRef } from 'react';
import './RecordingControls.css';
import { UI_TEXT, type LanguageCode } from '../i18n';
import { toEvenRecordingDimension } from '../utils/recordingDimensions';

type AspectRatioOption = {
  id: string;
  name: string;
  desc: string;
  width: number;
  height: number;
};

interface RecordingControlsProps {
  isRecording: boolean;
  isPreviewing: boolean;
  isPaused: boolean;
  isConverting: boolean;
  convertingMessage?: string;
  showCursor: boolean;
  aspectRatios: AspectRatioOption[];
  aspectRatio: string;
  customWidth: number;
  customHeight: number;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onTogglePause: () => void;
  onToggleCursor: () => void;
  onConfirmRecording: () => void;
  onCancelPreview: () => void;
  onRecordingSizeChange: (nextSize: {
    aspectRatio: string;
    customWidth: number;
    customHeight: number;
  }) => void;
  onOpenSettings: () => void;
  onOpenLibrary: () => void;
  onToggleTeleprompter: () => void;
  showTeleprompter: boolean;
  language: LanguageCode;
}

type ToolbarPosition = { x: number; y: number };
type DockPlacement = { top: number; right: number };

const TOOLBAR_MARGIN = 14;
const DOCK_TOP = 16;
const DOCK_RIGHT = 24;

function RecordingControls({
  isRecording,
  isPreviewing,
  isPaused,
  isConverting,
  convertingMessage,
  showCursor,
  aspectRatios,
  aspectRatio,
  customWidth,
  customHeight,
  onStartRecording,
  onStopRecording,
  onTogglePause,
  onToggleCursor,
  onConfirmRecording,
  onCancelPreview,
  onRecordingSizeChange,
  onOpenSettings,
  onOpenLibrary,
  onToggleTeleprompter,
  showTeleprompter,
  language
}: RecordingControlsProps) {
  const text = UI_TEXT[language].controls;
  const settingsText = UI_TEXT[language].settings;
  const statusText = UI_TEXT[language].status;
  const aspectDescriptions = settingsText.aspectDescriptions as Record<string, string>;
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [position, setPosition] = useState<ToolbarPosition | null>(null);
  const [dockPlacement, setDockPlacement] = useState<DockPlacement>({ top: DOCK_TOP, right: DOCK_RIGHT });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const positionStartRef = useRef({ x: 0, y: 0 });
  const controlsRef = useRef<HTMLDivElement>(null);

  const clampToolbarPosition = useCallback((nextPosition: ToolbarPosition): ToolbarPosition => {
    const rect = controlsRef.current?.getBoundingClientRect();
    const width = rect?.width || 360;
    const height = rect?.height || 56;

    return {
      x: Math.max(TOOLBAR_MARGIN, Math.min(window.innerWidth - width - TOOLBAR_MARGIN, nextPosition.x)),
      y: Math.max(TOOLBAR_MARGIN, Math.min(window.innerHeight - height - TOOLBAR_MARGIN, nextPosition.y)),
    };
  }, []);

  const updateDockPlacement = useCallback(() => {
    const toolbarRect = controlsRef.current?.getBoundingClientRect();
    const toolbarWidth = toolbarRect?.width || 300;
    const sidebar = document.querySelector('.library-browser-panel, .excalidraw-container .default-sidebar');
    let right = DOCK_RIGHT;

    if (sidebar) {
      const sidebarRect = sidebar.getBoundingClientRect();
      const sidebarStyle = window.getComputedStyle(sidebar);
      const isSidebarOpen = sidebarStyle.display !== 'none' && sidebarRect.width > 1 && sidebarRect.left < window.innerWidth;

      if (isSidebarOpen) {
        right = Math.max(DOCK_RIGHT, window.innerWidth - sidebarRect.left + DOCK_RIGHT);
      }
    }

    const toolbarLeft = window.innerWidth - right - toolbarWidth;
    const toolbarRight = window.innerWidth - right;
    const excalidrawToolbar = document.querySelector('.App-toolbar-container');
    const excalidrawToolbarRect = excalidrawToolbar?.getBoundingClientRect();
    const overlapsTopToolbar = Boolean(
      excalidrawToolbarRect &&
      toolbarLeft < excalidrawToolbarRect.right + 12 &&
      toolbarRight > excalidrawToolbarRect.left - 12
    );
    const top = overlapsTopToolbar && excalidrawToolbarRect
      ? Math.round(excalidrawToolbarRect.bottom + 16)
      : DOCK_TOP;

    setDockPlacement(prev => prev.top === top && prev.right === right ? prev : { top, right });
  }, []);

  useEffect(() => {
    let animationFrame: number | null = null;
    const scheduleUpdate = () => {
      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame);
      }
      animationFrame = requestAnimationFrame(updateDockPlacement);
    };

    scheduleUpdate();
    window.addEventListener('resize', scheduleUpdate);

    const mutationObserver = new MutationObserver(scheduleUpdate);
    mutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'data-state'],
    });

    const resizeObserver = new ResizeObserver(scheduleUpdate);
    const excalidrawContainer = document.querySelector('.excalidraw-container');
    if (excalidrawContainer) {
      resizeObserver.observe(excalidrawContainer);
    }

    return () => {
      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame);
      }
      window.removeEventListener('resize', scheduleUpdate);
      mutationObserver.disconnect();
      resizeObserver.disconnect();
    };
  }, [updateDockPlacement]);

  // Timer - pauses when recording is paused
  useEffect(() => {
    if (!isRecording || isPaused) {
      return;
    }

    const interval = setInterval(() => setElapsedSeconds(prev => prev + 1), 1000);
    return () => clearInterval(interval);
  }, [isRecording, isPaused]);

  // Constrain dragged position when the toolbar shape or viewport changes.
  useEffect(() => {
    if (!position) {
      return;
    }

    const constrain = () => setPosition(prev => prev ? clampToolbarPosition(prev) : prev);
    constrain();
    window.addEventListener('resize', constrain);
    return () => window.removeEventListener('resize', constrain);
  }, [position, isPreviewing, isRecording, isConverting, clampToolbarPosition]);

  const handleDragStart = (e: React.MouseEvent) => {
    if (e.button !== 0) return;

    const target = e.target as HTMLElement;
    if (target.closest('button, a, input, textarea, select, [role="button"], .recording-size-popover')) {
      return;
    }

    const rect = controlsRef.current?.getBoundingClientRect();
    if (!rect) return;

    e.preventDefault();
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    positionStartRef.current = { x: rect.left, y: rect.top };
    setPosition({ x: rect.left, y: rect.top });
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - dragStartRef.current.x;
      const deltaY = e.clientY - dragStartRef.current.y;

      // Get actual element dimensions
      const rect = controlsRef.current?.getBoundingClientRect();
      const width = rect?.width || 300;
      const height = rect?.height || 50;

      setPosition({
        x: Math.max(TOOLBAR_MARGIN, Math.min(window.innerWidth - width - TOOLBAR_MARGIN, positionStartRef.current.x + deltaX)),
        y: Math.max(TOOLBAR_MARGIN, Math.min(window.innerHeight - height - TOOLBAR_MARGIN, positionStartRef.current.y + deltaY))
      });
    };

    const handleMouseUp = () => setIsDragging(false);

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    return `${m.toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;
  };

  const updateDimension = (dimension: 'width' | 'height', value: number) => {
    if (!Number.isFinite(value)) {
      return;
    }

    const sanitizedValue = toEvenRecordingDimension(value);

    onRecordingSizeChange({
      aspectRatio: 'custom',
      customWidth: dimension === 'width' ? sanitizedValue : toEvenRecordingDimension(customWidth),
      customHeight: dimension === 'height' ? sanitizedValue : toEvenRecordingDimension(customHeight),
    });
  };

  const selectAspectRatio = (ratio: AspectRatioOption) => {
    onRecordingSizeChange({
      aspectRatio: ratio.id,
      customWidth: ratio.width,
      customHeight: ratio.height,
    });
  };

  const handleConfirmRecording = () => {
    setElapsedSeconds(0);
    onConfirmRecording();
  };

  const sizePopover = (
    <div className="recording-size-popover" onMouseDown={(event) => event.stopPropagation()}>
      <div className="recording-size-row">
        <span className="recording-size-label">{settingsText.width}</span>
        <input
          className="recording-size-input"
          type="number"
          min={320}
          max={7680}
          value={customWidth}
          onChange={(event) => updateDimension('width', Number(event.target.value))}
        />
        <span className="recording-size-cross">×</span>
        <input
          className="recording-size-input"
          type="number"
          min={320}
          max={7680}
          value={customHeight}
          onChange={(event) => updateDimension('height', Number(event.target.value))}
        />
        <span className="recording-size-unit">px</span>
      </div>

      <div className="recording-aspect-grid" aria-label={settingsText.aspectRatio}>
        {aspectRatios.map((ratio) => (
          <button
            key={ratio.id}
            className={`recording-aspect-option ${aspectRatio === ratio.id ? 'active' : ''}`}
            onClick={() => selectAspectRatio(ratio)}
          >
            <span>{ratio.id === 'custom' && language === 'zh-CN' ? '自定义' : ratio.name}</span>
            <small>{aspectDescriptions[ratio.id] || ratio.desc}</small>
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div
      ref={controlsRef}
      className={`recording-controls ${position ? 'recording-controls--dragged' : 'recording-controls--docked'} ${isDragging ? 'dragging' : ''}`}
      style={position ? { left: position.x, top: position.y } : {
        '--recording-dock-top': `${dockPlacement.top}px`,
        '--recording-dock-right': `${dockPlacement.right}px`,
      } as React.CSSProperties}
      onMouseDown={handleDragStart}
    >
      {/* Settings button */}
      <button
        className="icon-btn settings-btn"
        onClick={onOpenSettings}
        aria-label={text.settings}
        title={text.settings}
        data-tooltip={text.settings}
        disabled={isRecording || isConverting || isPreviewing}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>

      {/* Library button */}
      <button
        className="icon-btn library-btn"
        onClick={onOpenLibrary}
        aria-label={text.library}
        title={text.library}
        data-tooltip={text.library}
        disabled={isConverting}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          <path d="M8 6h8"/>
          <path d="M8 10h7"/>
        </svg>
      </button>

      {/* Teleprompter toggle */}
      <button
        className={`icon-btn teleprompter-btn ${showTeleprompter ? 'active' : ''}`}
        onClick={onToggleTeleprompter}
        aria-label={text.teleprompter}
        title={text.teleprompter}
        data-tooltip={text.teleprompter}
        disabled={isConverting}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="4" width="14" height="13" rx="2.5" />
          <path d="M8 8h8" />
          <path d="M8 11h6.5" />
          <path d="M8 14h5" />
          <path d="M12 17v3" />
          <path d="M9 20h6" />
        </svg>
      </button>

      {isPreviewing && sizePopover}

      {isConverting ? (
        <div className="converting-status">
          <span className="spinner"></span>
          {convertingMessage || statusText.converting}
        </div>
      ) : isRecording ? (
        <>
          {/* Cursor toggle - icon button */}
          <button
            className={`icon-btn cursor-toggle-btn ${showCursor ? 'active' : ''}`}
            onClick={onToggleCursor}
            aria-label={showCursor ? text.hideCursor : text.showCursor}
            title={showCursor ? text.hideCursor : text.showCursor}
            data-tooltip={showCursor ? text.hideCursor : text.showCursor}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="12" cy="12" r="4"/>
            </svg>
          </button>
          <button className="control-button pause-button" onClick={onTogglePause}>
            {isPaused ? `▶ ${text.resume}` : `⏸ ${text.pause}`}
          </button>
          <button className="control-button stop-button" onClick={onStopRecording}>
            ■ {text.stop}
          </button>
          <div className={`recording-timer ${isPaused ? 'paused' : ''}`}>
            <span className={`recording-dot ${isPaused ? 'paused' : ''}`}></span>
            <span>{formatTime(elapsedSeconds)}</span>
          </div>
        </>
      ) : isPreviewing ? (
        <>
          <button className="control-button cancel-button" onClick={onCancelPreview}>
            ✕ {text.cancel}
          </button>
          <button className="control-button confirm-button" onClick={handleConfirmRecording}>
            ● {text.startRecording}
          </button>
        </>
      ) : (
        <button className="control-button record-button" onClick={onStartRecording}>
          ● {text.record}
        </button>
      )}
    </div>
  );
}

export default RecordingControls;
