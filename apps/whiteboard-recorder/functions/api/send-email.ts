/**
 * Cloudflare Pages Function: Send email via Resend
 *
 * This serverless function receives an email address and sends a link
 * to Xiangrui Whiteboard Recorder. Runs on Cloudflare's edge network.
 *
 * Environment variable required:
 *   RESEND_API_KEY - Your Resend API key (set in Cloudflare dashboard)
 */

interface Env {
  RESEND_API_KEY: string;
}

interface RequestBody {
  email: string;
  url: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  // CORS headers for the response
  const headers = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  };

  try {
    // Parse the request body
    const body: RequestBody = await context.request.json();
    const { email, url } = body;

    // Validate email
    if (!email || !email.includes('@')) {
      return new Response(
        JSON.stringify({ error: 'Invalid email address' }),
        { status: 400, headers }
      );
    }

    // Check for API key
    if (!context.env.RESEND_API_KEY) {
      console.error('RESEND_API_KEY not configured');
      return new Response(
        JSON.stringify({ error: 'Email service not configured' }),
        { status: 500, headers }
      );
    }

    // Send email via Resend
    const resendResponse = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${context.env.RESEND_API_KEY}`,
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
      return new Response(
        JSON.stringify({ error: 'Failed to send email' }),
        { status: 500, headers }
      );
    }

    return new Response(
      JSON.stringify({ success: true }),
      { status: 200, headers }
    );

  } catch (error) {
    console.error('Function error:', error);
    return new Response(
      JSON.stringify({ error: 'Internal server error' }),
      { status: 500, headers }
    );
  }
};

// Handle CORS preflight requests
export const onRequestOptions: PagesFunction = async () => {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
};
