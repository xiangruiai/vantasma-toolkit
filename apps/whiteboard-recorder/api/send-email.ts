/**
 * Vercel Serverless Function: Send email via Resend
 *
 * This function receives an email address from mobile users and sends them
 * a link to open Xiangrui Whiteboard Recorder on their desktop.
 *
 * Environment variable required:
 *   RESEND_API_KEY - Your Resend API key (set in Vercel dashboard)
 */

import type { VercelRequest, VercelResponse } from '@vercel/node';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(200).end();
  }

  // Only allow POST
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { email, url } = req.body;

    // Validate email
    if (!email || !email.includes('@')) {
      return res.status(400).json({ error: 'Invalid email address' });
    }

    // Check for API key
    if (!process.env.RESEND_API_KEY) {
      console.error('RESEND_API_KEY not configured');
      return res.status(500).json({ error: 'Email service not configured' });
    }

    // Send email via Resend
    const resendResponse = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: '祥瑞白板录制工具 <li@xiangruiai.com>',
        to: email,
        subject: '你的祥瑞白板录制工具链接',
        html: `
          <!DOCTYPE html>
          <html>
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
          </head>
          <body style="margin: 0; padding: 0; background-color: #1c1917; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #1c1917; padding: 40px 20px;">
              <tr>
                <td align="center">
                  <table width="100%" max-width="480" cellpadding="0" cellspacing="0" style="max-width: 480px;">
                    <!-- Header -->
                    <tr>
                      <td style="padding-bottom: 32px; text-align: center;">
                        <h1 style="margin: 0; font-size: 28px; font-weight: 700; color: #fefcf9;">
                          祥瑞白板录制工具
                        </h1>
                      </td>
                    </tr>

                    <!-- Main content card -->
                    <tr>
                      <td style="background-color: #292524; border-radius: 16px; padding: 32px;">
                        <p style="margin: 0 0 24px; font-size: 16px; line-height: 1.6; color: #d6d3d1;">
                          你请求了一个桌面端打开链接。点击下面的按钮，开始录制白板讲解视频。
                        </p>

                        <!-- CTA Button -->
                        <table width="100%" cellpadding="0" cellspacing="0">
                          <tr>
                            <td align="center" style="padding: 8px 0 24px;">
                              <a href="${url}"
                                 style="display: inline-block; padding: 14px 32px; background-color: #fefcf9; color: #1c1917; font-size: 15px; font-weight: 600; text-decoration: none; border-radius: 10px;">
                                打开祥瑞白板录制工具
                              </a>
                            </td>
                          </tr>
                        </table>

                        <p style="margin: 0; font-size: 13px; color: #78716c;">
                          Or copy this link:<br>
                          <a href="${url}" style="color: #a8a29e; word-break: break-all;">${url}</a>
                        </p>
                      </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                      <td style="padding-top: 24px; text-align: center;">
                        <p style="margin: 0; font-size: 12px; color: #57534e;">
                          This is a one-time link you requested. No spam, ever.
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </body>
          </html>
        `,
      }),
    });

    if (!resendResponse.ok) {
      const errorData = await resendResponse.json();
      console.error('Resend error:', errorData);
      return res.status(500).json({ error: 'Failed to send email' });
    }

    return res.status(200).json({ success: true });

  } catch (error) {
    console.error('Function error:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
}
