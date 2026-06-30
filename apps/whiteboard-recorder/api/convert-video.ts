/**
 * Video Conversion API - Converts WebM to MP4 server-side
 *
 * This runs on Vercel serverless functions using FFmpeg.
 * Much more reliable than browser-based conversion.
 */

import type { VercelRequest, VercelResponse } from '@vercel/node';
import ffmpeg from 'fluent-ffmpeg';
import ffmpegStatic from 'ffmpeg-static';
import { tmpdir } from 'os';
import { join } from 'path';
import { writeFile, unlink, readFile } from 'fs/promises';
import { randomUUID } from 'crypto';

// Set FFmpeg path
ffmpeg.setFfmpegPath(ffmpegStatic as string);

// Max file size: 100MB (Vercel has limits)
const MAX_FILE_SIZE = 100 * 1024 * 1024;

export const config = {
  api: {
    bodyParser: {
      sizeLimit: '100mb',
    },
  },
  // Increase timeout for video conversion (max 60s on Pro plan)
  maxDuration: 60,
};

export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Only allow POST
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    // Get the video data from request body
    const contentType = req.headers['content-type'] || '';

    if (!contentType.includes('video/webm') && !contentType.includes('application/octet-stream')) {
      return res.status(400).json({ error: 'Expected video/webm content type' });
    }

    // Read the body as a buffer
    const chunks: Buffer[] = [];
    for await (const chunk of req) {
      chunks.push(Buffer.from(chunk));
    }
    const videoBuffer = Buffer.concat(chunks);

    if (videoBuffer.length === 0) {
      return res.status(400).json({ error: 'No video data received' });
    }

    if (videoBuffer.length > MAX_FILE_SIZE) {
      return res.status(400).json({ error: 'File too large. Max 100MB.' });
    }

    console.log(`[convert-video] Received ${(videoBuffer.length / 1024 / 1024).toFixed(2)}MB video`);

    // Create temp files
    const tempId = randomUUID();
    const inputPath = join(tmpdir(), `input-${tempId}.webm`);
    const outputPath = join(tmpdir(), `output-${tempId}.mp4`);

    // Write input file
    await writeFile(inputPath, videoBuffer);
    console.log('[convert-video] Written input file');

    // Convert using FFmpeg
    await new Promise<void>((resolve, reject) => {
      ffmpeg(inputPath)
        .outputOptions([
          '-c:v libx264',       // H.264 video codec
          '-preset ultrafast',  // Fastest encoding (Vercel has limited CPU)
          '-crf 28',            // Slightly lower quality for speed
          '-c:a aac',           // AAC audio
          '-b:a 96k',           // Lower audio bitrate
          '-movflags +faststart', // Optimize for streaming
          '-pix_fmt yuv420p',   // Compatibility
          '-threads 1',         // Single thread (serverless)
        ])
        .output(outputPath)
        .on('start', () => {
          console.log('[convert-video] FFmpeg started');
        })
        .on('end', () => {
          console.log('[convert-video] Conversion complete');
          resolve();
        })
        .on('error', (err) => {
          console.error('[convert-video] FFmpeg error:', err);
          reject(err);
        })
        .run();
    });

    // Read the output file
    const mp4Buffer = await readFile(outputPath);
    console.log(`[convert-video] Output size: ${(mp4Buffer.length / 1024 / 1024).toFixed(2)}MB`);

    // Clean up temp files
    await Promise.all([
      unlink(inputPath).catch(() => {}),
      unlink(outputPath).catch(() => {}),
    ]);

    // Send the MP4 back
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Length', mp4Buffer.length);
    res.setHeader('Content-Disposition', `attachment; filename="xiangrui-whiteboard-${Date.now()}.mp4"`);
    res.send(mp4Buffer);

  } catch (error) {
    console.error('[convert-video] Error:', error);
    res.status(500).json({
      error: 'Conversion failed',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
