/**
 * WebcamBubble Component - The draggable circular webcam overlay
 *
 * This is like a "floating head" window that shows your face while you draw.
 * You can drag it around to position it anywhere on the whiteboard.
 *
 * How dragging works:
 * 1. When you press down on the bubble, we start "listening" for mouse movements
 * 2. As you move your mouse, we calculate the new position
 * 3. When you release, we stop listening
 *
 * The circle effect is achieved with CSS border-radius: 50%
 * (turns any square into a circle)
 */

import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, MutableRefObject } from 'react';
import './WebcamBubble.css';

interface WebcamBubbleProps {
  stream: MediaStream;           // The video stream from your camera
  position: { x: number; y: number };  // Current position {x, y}
  size: number;                  // Diameter of the bubble in pixels
  shape: 'circle' | 'square';    // Visual crop shape
  effectsClass: string;          // Camera effect classes
  lightStyle?: CSSProperties; // Custom camera light variables
  onDrag: (position: { x: number; y: number }) => void;  // Callback when dragged
  onActivate?: () => void; // Callback when clicked without dragging
  videoRef: MutableRefObject<HTMLVideoElement | null>;  // Reference to pass up to parent
}

function WebcamBubble({ stream, position, size, shape, effectsClass, lightStyle, onDrag, onActivate, videoRef }: WebcamBubbleProps) {
  // Local ref for the video element (we'll sync this with the parent's ref)
  const localVideoRef = useRef<HTMLVideoElement>(null);

  // Track whether we're currently dragging
  const [isDragging, setIsDragging] = useState(false);

  // Remember where the mouse was when we started dragging
  // This helps us calculate the "offset" so the bubble doesn't jump
  const dragStartRef = useRef({ x: 0, y: 0 });
  const positionStartRef = useRef({ x: 0, y: 0 });
  const hasDraggedRef = useRef(false);

  /**
   * Connect the webcam stream to the video element
   * This runs whenever the stream changes
   */
  useEffect(() => {
    const video = localVideoRef.current;
    if (video && stream) {
      video.srcObject = stream;  // Connect stream to video element
      // Handle play() promise to avoid uncaught errors
      video.play().catch(() => {
        // Ignore AbortError - happens when stream changes quickly
      });
    }

    if (localVideoRef.current) {
      videoRef.current = localVideoRef.current;
    }
  }, [stream, videoRef]);

  /**
   * Handle mouse down - start dragging
   */
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();  // Prevent text selection while dragging
    e.stopPropagation();
    setIsDragging(true);
    hasDraggedRef.current = false;

    // Remember where we started
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    positionStartRef.current = { ...position };
  };

  /**
   * Handle mouse move - update position while dragging
   * We use a useEffect with a window listener so we can track the mouse
   * even when it moves outside the bubble element
   */
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      // Calculate how far the mouse has moved from the start
      const deltaX = e.clientX - dragStartRef.current.x;
      const deltaY = e.clientY - dragStartRef.current.y;

      if (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4) {
        hasDraggedRef.current = true;
      }

      if (!hasDraggedRef.current) {
        return;
      }

      // Apply that movement to the original position
      const newX = positionStartRef.current.x + deltaX;
      const newY = positionStartRef.current.y + deltaY;

      // Notify the parent of the new position
      onDrag({ x: newX, y: newY });
    };

    const handleMouseUp = () => {
      if (!hasDraggedRef.current) {
        onActivate?.();
      }

      setIsDragging(false);
    };

    // Listen for mouse events on the whole window
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    // Cleanup when we stop dragging
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, onActivate, onDrag]);

  return (
    <div
      className={`webcam-bubble ${shape} ${effectsClass} ${isDragging ? 'dragging' : ''}`}
      style={{
        // Position the bubble absolutely within its container
        left: position.x,
        top: position.y,
        width: size,
        height: size,
        ...lightStyle,
      }}
      onMouseDown={handleMouseDown}
    >
      {/* The video element that shows your webcam feed */}
      <video
        ref={localVideoRef}
        className="webcam-video"
        autoPlay        // Start playing as soon as stream is connected
        playsInline     // Required for iOS to work properly
        muted           // Muted to prevent audio feedback loop
      />

      {/* Visual indicator that you can drag this */}
      <div className="drag-handle">
        <svg viewBox="0 0 24 24" fill="currentColor">
          <circle cx="8" cy="8" r="2" />
          <circle cx="16" cy="8" r="2" />
          <circle cx="8" cy="16" r="2" />
          <circle cx="16" cy="16" r="2" />
        </svg>
      </div>
    </div>
  );
}

export default WebcamBubble;
